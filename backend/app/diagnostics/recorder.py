"""
Storm Energy RTU Platform - Protocol Test Log recorder.

Called by the EXISTING ingestion paths (app.tcp.server / app.mqtt.consumer) after they
have handled a message, with the parser's own result. It classifies the message:

    INVALID         the parser rejected it (or the topic/frame is not recognised)
    UNKNOWN_DEVICE  the parser accepted it, but the device is not in the Devices registry
    VALID           the parser accepted it and the device is registered

and writes ONE row to dbo.ProtocolDiagnosticLogs in its OWN session/transaction.

Guarantees:
  * Never raises: a diagnostic failure can never break or alter ingestion.
  * Never writes to any table other than ProtocolDiagnosticLogs (the Devices registry
    is only READ, to classify and to show the registered IMEI / name / site).
  * Rate-limited per process (DIAG_MAX_WRITES_PER_MINUTE) so a flood of probing
    traffic cannot grow the table without bound; skipped writes are counted and logged.
  * The timestamp is the SERVER receipt time (now_ist()) captured by the caller.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from app.config import get_settings
from app.diagnostics.payload import render_payload

logger = logging.getLogger(__name__)

STATUS_VALID = "VALID"
STATUS_INVALID = "INVALID"
STATUS_UNKNOWN_DEVICE = "UNKNOWN_DEVICE"


@dataclass
class DiagnosticEvent:
    protocol: str                       # "TCP" | "MQTT"
    received_at: datetime               # server IST, captured at receipt
    raw: bytes
    parsed_ok: bool                     # parser accepted the message
    device_id: Optional[str] = None     # as identified by the parser / topic
    site_id: Optional[str] = None
    source_ip: Optional[str] = None
    topic: Optional[str] = None
    qos: Optional[int] = None
    outcome: Optional[str] = None       # pipeline result (PROCESSED, DUPLICATE, ...)
    error_reason: Optional[str] = None


class _MinuteLimiter:
    """Fixed-window limiter: at most `limit` writes per 60 s window (thread-safe)."""

    def __init__(self, limit: int):
        self.limit = limit
        self._window = 0
        self._count = 0
        self._dropped = 0
        self._lock = threading.Lock()

    def allow(self) -> bool:
        now = int(time.monotonic() // 60)
        with self._lock:
            if now != self._window:
                if self._dropped:
                    logger.warning("Protocol diagnostics: %d record(s) skipped by rate limit (%d/min)",
                                   self._dropped, self.limit)
                self._window, self._count, self._dropped = now, 0, 0
            if self._count >= self.limit:
                self._dropped += 1
                return False
            self._count += 1
            return True


_limiter: Optional[_MinuteLimiter] = None
_limiter_lock = threading.Lock()


def _get_limiter() -> _MinuteLimiter:
    global _limiter
    with _limiter_lock:
        if _limiter is None:
            _limiter = _MinuteLimiter(get_settings().DIAG_MAX_WRITES_PER_MINUTE)
        return _limiter


def _session_factory():
    """Indirection so tests can supply their own session factory."""
    from app.database.database import SessionLocal
    return SessionLocal()


def _clip(value: Optional[str], n: int) -> Optional[str]:
    if value is None:
        return None
    value = str(value)
    return value if len(value) <= n else value[: n - 1] + "…"


def build_row(ev: DiagnosticEvent, device, max_chars: int):
    """Pure classification + row construction (no I/O). `device` is the registry row or None."""
    from app.database.models import ProtocolDiagnosticLog

    payload = render_payload(ev.raw, max_chars)
    if not ev.parsed_ok:
        status = STATUS_INVALID
    elif device is None:
        status = STATUS_UNKNOWN_DEVICE
    else:
        status = STATUS_VALID
    registered = ev.parsed_ok and device is not None
    return ProtocolDiagnosticLog(
        ReceivedAt       = ev.received_at,
        Protocol         = ev.protocol,
        Status           = status,
        Outcome          = _clip(ev.outcome, 30),
        SourceIP         = _clip(ev.source_ip, 45),
        DeviceId         = _clip(ev.device_id, 50) if ev.parsed_ok else None,
        DeviceName       = _clip(getattr(device, "Name", None), 100) if registered else None,
        IMEI             = _clip(getattr(device, "IMEI", None), 20) if registered else None,
        SiteId           = _clip((getattr(device, "SiteId", None) if registered else None) or ev.site_id, 50)
                           if ev.parsed_ok else None,
        IsRegistered     = registered,
        Topic            = _clip(ev.topic, 255),
        QoS              = ev.qos,
        Payload          = payload.text,
        PayloadEncoding  = payload.encoding,
        PayloadBytes     = payload.size,
        PayloadTruncated = payload.truncated,
        ErrorReason      = _clip(ev.error_reason, 500),
        CreatedAt        = ev.received_at,
    )


def record(ev: DiagnosticEvent) -> bool:
    """Write one diagnostic row. Returns True if written. NEVER raises."""
    try:
        settings = get_settings()
        if not settings.DIAG_ENABLED or not _get_limiter().allow():
            return False
        from app.database.repository import DeviceRepository
        db = _session_factory()
        try:
            device = None
            if ev.parsed_ok and ev.device_id:
                device = DeviceRepository.get_by_device_id(db, ev.device_id)   # READ only
            db.add(build_row(ev, device, settings.DIAG_PAYLOAD_MAX_CHARS))
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
    except Exception as exc:   # diagnostics must never affect ingestion
        logger.warning("Protocol diagnostic record not written (%s): %s", ev.protocol, exc)
        return False
