"""
Storm Energy RTU Platform — Async TCP listener.
Accepts raw connections from RTUs, routes packets through the TCP parser,
and submits telemetry to the shared TelemetryService.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from app.timezone import now_ist

from app.config import get_settings
from app.database.database import db_session
from app.database.repository import RawMessageRepository, TCPMessageRepository
from app.protocol.tcp_parser import get_ack_strategy, parse_tcp_packet
from app.protocol.validation import PayloadValidationError
from app.services.event_service import EventService
from app.services.telemetry_service import TelemetryService
from app.tcp.connection import TCPConnectionRegistry

logger = logging.getLogger(__name__)

_registry    = TCPConnectionRegistry()
_telemetry   = TelemetryService()


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Coroutine spawned for each inbound TCP connection."""
    settings  = get_settings()
    peer      = writer.get_extra_info("peername")
    source_ip = peer[0] if peer else "unknown"
    logger.info("TCP connection from %s", source_ip)

    device_id = None
    _registry.add(source_ip, writer)

    try:
        with db_session() as db:
            while True:
                try:
                    raw = await asyncio.wait_for(
                        reader.read(settings.TCP_BUFFER_SIZE),
                        timeout=float(settings.TCP_TIMEOUT),
                    )
                except asyncio.TimeoutError:
                    logger.info("TCP timeout for %s (device=%s)", source_ip, device_id)
                    if device_id:
                        EventService.record(
                            db,
                            device_id   = device_id,
                            event_type  = "TCP_DISCONNECTED",
                            description = f"Timeout after {settings.TCP_TIMEOUT}s",
                            protocol    = "TCP",
                            severity    = "WARNING",
                        )
                        db.commit()
                    break

                if not raw:
                    logger.info("TCP connection closed by %s (device=%s)", source_ip, device_id)
                    break

                raw_stripped = raw.strip()
                if not raw_stripped:
                    continue

                ack_strategy = get_ack_strategy()
                logger.debug(
                    "TCP RX from %s: %d bytes | ack_strategy=%s",
                    source_ip, len(raw), ack_strategy.describe()
                )

                # 1. Archive raw message always
                raw_record = RawMessageRepository.create(
                    db,
                    Protocol   = "TCP",
                    ReceivedAt = now_ist(),
                    SourceIP   = source_ip,
                    Payload    = raw.decode("utf-8", errors="replace"),
                    DeviceId   = device_id,
                    IsValid    = True,
                )
                db.flush()
                raw_id = raw_record.Id

                # 2. Parse
                ack: bytes = b""
                try:
                    telemetry = parse_tcp_packet(raw_stripped, source_ip)
                    telemetry.raw_message_id = raw_id
                    device_id = telemetry.device_id

                    # Update raw record with now-known device ID
                    raw_record.DeviceId = device_id
                    db.flush()

                    # 3. Persist TCP message record
                    tcp_msg = TCPMessageRepository.create(
                        db,
                        DeviceId     = device_id,
                        SourceIP     = source_ip,
                        Payload      = raw.decode("utf-8", errors="replace"),
                        Status       = "RECEIVED",
                        RawMessageId = raw_id,
                    )

                    # 4. Ingest telemetry
                    result = _telemetry.ingest(db, telemetry)
                    status = "PROCESSED" if result["status"] == "stored" else result["status"].upper()
                    TCPMessageRepository.update_status(db, tcp_msg.Id, status)

                    # 5. ACK
                    ts = telemetry.timestamp
                    ack = ack_strategy.build_ack(device_id, ts, success=True)

                    logger.info(
                        "TCP telemetry ingested: device=%s ts=%s status=%s",
                        device_id, ts, result["status"]
                    )

                except PayloadValidationError as ve:
                    raw_record.IsValid     = False
                    raw_record.ErrorMessage = str(ve)
                    TCPMessageRepository.create(
                        db,
                        DeviceId     = device_id,
                        SourceIP     = source_ip,
                        Payload      = raw.decode("utf-8", errors="replace"),
                        Status       = "INVALID",
                        RawMessageId = raw_id,
                    )
                    ack = ack_strategy.build_ack(device_id or "unknown", now_ist(), success=False)
                    logger.warning("TCP parse error [%s] from %s: %s", ve.error.code, source_ip, ve)
                    db.flush()

                db.commit()

                if ack:
                    writer.write(ack)
                    await writer.drain()

    except Exception as exc:
        logger.exception("Unhandled TCP error from %s: %s", source_ip, exc)
    finally:
        _registry.remove(source_ip)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        logger.info("TCP connection closed: %s (device=%s)", source_ip, device_id)


class TCPServer:
    """Manages the asyncio TCP server lifecycle."""

    def __init__(self):
        self._server: asyncio.Server | None = None
        self._settings = get_settings()

    async def start(self) -> None:
        s = self._settings
        self._server = await asyncio.start_server(
            handle_client,
            host   = s.TCP_HOST,
            port   = s.TCP_PORT,
            limit  = s.TCP_BUFFER_SIZE,
        )
        addrs = [str(sock.getsockname()) for sock in self._server.sockets]
        logger.info("TCP server listening on %s", addrs)

    async def stop(self) -> None:
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("TCP server stopped")

    @property
    def connection_count(self) -> int:
        return _registry.count

    async def serve_forever(self) -> None:
        if self._server:
            async with self._server:
                await self._server.serve_forever()
