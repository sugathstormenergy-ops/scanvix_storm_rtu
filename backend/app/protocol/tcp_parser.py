"""
Storm Energy RTU Platform — TCP ASCII Packet Parser.

NOTE: The exact TCP packet format for Scanvix RTUs is defined as ASCII
but the field layout has NOT yet been finalised with Scanvix.

Current status: TBD — to be agreed with Scanvix.

This module provides:
  1. A pluggable parser interface so the real format can be dropped in
     without touching any other layer.
  2. A best-effort JSON fallback — some RTU firmware sends JSON over TCP.
  3. The AckStrategy abstraction — ACK byte sequence is TBD.

Do NOT assume the placeholder format is production-approved.
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.protocol.telemetry import NormalizedTelemetry
from app.protocol.validation import PayloadValidationError, ValidationErrorCode
from app.protocol.mqtt_parser import parse_mqtt_payload   # JSON-over-TCP reuses this

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# ACK strategy — TBD with Scanvix
# ─────────────────────────────────────────────────────────────────────────────

class AckStrategy(ABC):
    """
    Abstract acknowledgement strategy.
    Concrete implementations are swapped in via configuration without
    changing the TCP server or any other layer.
    """
    @abstractmethod
    def build_ack(self, device_id: str, timestamp: datetime, success: bool) -> bytes:
        """Return the bytes to send back to the RTU as acknowledgement."""
        ...

    @abstractmethod
    def describe(self) -> str:
        """Human-readable description for logging and documentation."""
        ...


class NullAckStrategy(AckStrategy):
    """
    Send no acknowledgement byte.
    Used when ACK protocol is TBD or explicitly disabled.
    """
    def build_ack(self, device_id: str, timestamp: datetime, success: bool) -> bytes:
        return b""

    def describe(self) -> str:
        return "NullAck (no acknowledgement — TBD with Scanvix)"


class SimpleOkAckStrategy(AckStrategy):
    """
    Send 'OK\r\n' on success, 'ERR\r\n' on failure.
    PLACEHOLDER — not yet agreed with Scanvix. Do not deploy to production
    without explicit confirmation of this ACK format.
    """
    def build_ack(self, device_id: str, timestamp: datetime, success: bool) -> bytes:
        return b"OK\r\n" if success else b"ERR\r\n"

    def describe(self) -> str:
        return "SimpleOkAck (TBD — placeholder format, not yet confirmed with Scanvix)"


# Default strategy — no ACK until format is agreed
_DEFAULT_ACK_STRATEGY: AckStrategy = NullAckStrategy()


def get_ack_strategy() -> AckStrategy:
    return _DEFAULT_ACK_STRATEGY


# ─────────────────────────────────────────────────────────────────────────────
# TCP packet parsers
# ─────────────────────────────────────────────────────────────────────────────

class TcpParser(ABC):
    """Base class for all TCP packet parsers."""

    @abstractmethod
    def can_parse(self, raw: bytes) -> bool:
        """Return True if this parser recognises the packet format."""
        ...

    @abstractmethod
    def parse(self, raw: bytes, source_ip: str) -> NormalizedTelemetry:
        """Parse raw bytes into NormalizedTelemetry. Raise PayloadValidationError on failure."""
        ...


class JsonOverTcpParser(TcpParser):
    """
    Handles RTU firmware that sends the same JSON payload over a raw TCP
    socket as it would send over MQTT.  Forward-compatible if Scanvix
    confirms this as the TCP format.
    """

    def can_parse(self, raw: bytes) -> bool:
        stripped = raw.strip()
        return stripped.startswith(b"{") and stripped.endswith(b"}")

    def parse(self, raw: bytes, source_ip: str) -> NormalizedTelemetry:
        telemetry = parse_mqtt_payload("tcp/raw", raw)
        telemetry.protocol  = "TCP"
        telemetry.source_ip = source_ip
        return telemetry


class PlaceholderAsciiParser(TcpParser):
    """
    Placeholder for the final Scanvix ASCII TCP frame format.

    *** TBD — frame structure not yet agreed with Scanvix ***

    When the real frame specification is received from Scanvix, implement
    the complete parser here and remove this placeholder.  No other file
    needs to change.

    Assumed placeholder delimited format (for internal testing only):
      IMEI|SITEID|YYYY-MM-DD HH:MM:SS|FLOW|FLOWUNIT|TOTALTODAY|TOTALYESTERDAY|
      SENSORTYPE|SIGNALDBM|BATTERY|FWVERSION\\r\\n
    """

    def can_parse(self, raw: bytes) -> bool:
        # Rough heuristic: contains pipe separators, starts with a digit (IMEI)
        decoded = raw.decode("ascii", errors="ignore").strip()
        return "|" in decoded and decoded[:1].isdigit()

    def parse(self, raw: bytes, source_ip: str) -> NormalizedTelemetry:
        try:
            text   = raw.decode("ascii", errors="replace").strip().rstrip("\r\n")
            fields = text.split("|")
        except Exception as exc:
            raise PayloadValidationError(
                ValidationErrorCode.MALFORMED_PACKET,
                f"ASCII frame decode failed: {exc}",
                raw,
            )

        if len(fields) < 3:
            raise PayloadValidationError(
                ValidationErrorCode.MALFORMED_PACKET,
                f"Insufficient fields in ASCII frame (got {len(fields)}, need ≥3)",
                raw,
            )

        device_id = fields[0].strip()
        if not device_id:
            raise PayloadValidationError(
                ValidationErrorCode.MISSING_DEVICE_ID,
                "First field (IMEI/DeviceId) is empty",
                raw,
            )

        from app.protocol.mqtt_parser import _parse_timestamp, _safe_float, _safe_int
        timestamp = _parse_timestamp(fields[2].strip() if len(fields) > 2 else None)

        def f(idx: int):
            return fields[idx].strip() if idx < len(fields) else None

        logger.warning(
            "PlaceholderAsciiParser used for device %s — TCP frame format is TBD with Scanvix",
            device_id,
        )

        return NormalizedTelemetry(
            device_id       = device_id,
            protocol        = "TCP",
            timestamp       = timestamp,
            site_id         = f(1),
            flow            = _safe_float(f(3), "flow"),
            flow_unit       = f(4),
            total_today     = _safe_float(f(5), "totalToday"),
            total_yesterday = _safe_float(f(6), "totalYesterday"),
            sensor_type     = f(7),
            signal_dbm      = _safe_int(f(8), "signalDbm"),
            battery         = _safe_float(f(9), "battery"),
            fw_version      = f(10),
            source_ip       = source_ip,
        )


# Ordered list of parsers — first match wins
_PARSERS: list[TcpParser] = [
    JsonOverTcpParser(),
    PlaceholderAsciiParser(),
]


def parse_tcp_packet(raw: bytes, source_ip: str) -> NormalizedTelemetry:
    """
    Attempt each registered parser in order.
    Raises PayloadValidationError if no parser can handle the packet.
    """
    for parser in _PARSERS:
        if parser.can_parse(raw):
            return parser.parse(raw, source_ip)

    raise PayloadValidationError(
        ValidationErrorCode.MALFORMED_PACKET,
        f"No TCP parser could handle packet from {source_ip} ({len(raw)} bytes)",
        raw,
    )
