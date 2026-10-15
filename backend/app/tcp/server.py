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
from app.diagnostics.recorder import DiagnosticEvent, record as record_diagnostic
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
_active      = 0      # open connections in this process (event-loop only, no lock needed)


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Coroutine spawned for each inbound TCP connection."""
    settings  = get_settings()
    peer      = writer.get_extra_info("peername")
    source_ip = peer[0] if peer else "unknown"
    global _active
    if _active >= settings.TCP_MAX_CONNECTIONS:
        logger.warning("TCP connection from %s refused: TCP_MAX_CONNECTIONS=%d reached",
                       source_ip, settings.TCP_MAX_CONNECTIONS)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass
        return
    _active += 1
    logger.info("TCP connection from %s", source_ip)

    device_id = None
    diag: DiagnosticEvent | None = None     # Protocol Test Log entry for the packet in flight
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

                received_at = now_ist()          # server receipt time (authoritative)
                diag = DiagnosticEvent(protocol="TCP", received_at=received_at, raw=bytes(raw),
                                       parsed_ok=False, source_ip=source_ip)
                ack_strategy = get_ack_strategy()
                logger.debug(
                    "TCP RX from %s: %d bytes | ack_strategy=%s",
                    source_ip, len(raw), ack_strategy.describe()
                )

                # 1. Archive raw message always
                raw_record = RawMessageRepository.create(
                    db,
                    Protocol   = "TCP",
                    ReceivedAt = received_at,
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
                    diag.parsed_ok = True
                    diag.device_id = telemetry.device_id
                    diag.site_id = telemetry.site_id

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
                    diag.outcome = status

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
                    diag.outcome = "PARSE_ERROR"
                    diag.error_reason = f"{ve.error.code.value}: {ve}"

                db.commit()
                record_diagnostic(diag)          # own session; never raises
                diag = None

                if ack:
                    writer.write(ack)
                    await writer.drain()

    except Exception as exc:
        logger.exception("Unhandled TCP error from %s: %s", source_ip, exc)
        if diag is not None:                     # packet in flight when the error happened
            diag.outcome = "SERVER_ERROR"
            diag.error_reason = f"{type(exc).__name__}: {exc}"
            record_diagnostic(diag)
    finally:
        _active -= 1
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

# ─────────────────────────────────────────────────────────────────────────────
# Standalone entry point:  python -m app.tcp.server
# Runs ONLY the RTU TCP listener (no FastAPI, no MQTT consumer). Used by the
# Docker "storm-tcp" service and by the optional storm-rtu-tcp systemd unit.
# The listener, parser and persistence path are exactly the ones used when the
# listener runs inside the unified uvicorn process.
# ─────────────────────────────────────────────────────────────────────────────

def _configure_standalone_logging(level: str) -> None:
    import sys
    from app.timezone import ISTFormatter

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ISTFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))
    logging.basicConfig(level=getattr(logging, level, logging.INFO), handlers=[handler], force=True)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if level == "DEBUG" else logging.WARNING
    )


async def _run_standalone() -> None:
    import signal
    from app.database.database import check_database_connection, engine

    settings = get_settings()
    loop = asyncio.get_running_loop()

    logger.info("Storm RTU TCP listener starting (env=%s v=%s)", settings.APP_ENV, settings.APP_VERSION)

    # Report database reachability honestly; keep listening either way so the
    # port stays up and connections are visible in logs. Telemetry cannot be
    # persisted (and no ACK is sent) while SQL Server is unreachable.
    if not await loop.run_in_executor(None, check_database_connection):
        logger.critical(
            "SQL Server unreachable at startup (SQL_SERVER=%s:%s) — TCP listener will accept "
            "connections but telemetry CANNOT be stored until the database is reachable",
            settings.SQL_SERVER, settings.SQL_PORT,
        )

    server = TCPServer()
    await server.start()

    stop_event = asyncio.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except (NotImplementedError, RuntimeError):  # e.g. Windows event loop
            pass

    serve_task = asyncio.create_task(server.serve_forever())
    stop_wait = asyncio.create_task(stop_event.wait())
    await asyncio.wait({serve_task, stop_wait}, return_when=asyncio.FIRST_COMPLETED)

    logger.info("Storm RTU TCP listener shutting down …")
    await server.stop()
    for task in (serve_task, stop_wait):
        task.cancel()
    engine.dispose()
    logger.info("TCP listener shutdown complete")


def main() -> None:
    settings = get_settings()
    _configure_standalone_logging(settings.LOG_LEVEL)
    try:
        asyncio.run(_run_standalone())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
