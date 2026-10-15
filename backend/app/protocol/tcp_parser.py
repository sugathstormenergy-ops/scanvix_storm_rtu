"""
Storm Energy RTU Platform — TCP ASCII Packet Parser.

NOTE: The Scanvix production frame ("#SP,...") is implemented by ScanvixSpFrameParser, confirmed by
Scanvix from a real captured packet. The placeholder pipe format below remains for internal testing only.

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
import re
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


class ScanvixSpFrameParser(TcpParser):
    """
    Scanvix production TCP frame, confirmed by Scanvix from a real packet captured on the Storm TCP
    endpoint. The captured wire format is authoritative (it differs from the written protocol document).

    Wire layout (bytes, comma separated; NOT ordinary CSV - the telemetry block is binary):

        #SP , <device id> , NUL<IMEI> , HH:MM:SS , DD/MM/YYYY , <sensor byte> , <signal> , <firmware>NUL ,
        <f1> , <f2> , ... , <fN> ,          N binary fields of exactly 4 bytes, each followed by a comma
        00000 , 00000 , 00000 , 00000 , 00000 , 00000 , 00000 ,      7 ASCII fields of 5 digits, each + comma
        .                                                           terminator

    Binary fields are fixed width (4 bytes), so they are located by position and never split on commas
    (a binary value may legitimately contain 0x2C). The frame is parsed from raw bytes; nothing is
    normalised before the caller archives the original bytes.

    Binary field order (Scanvix): Instant Flow, Positive Totaliser, AI3, AI4, AI5, Today Total,
    Previous Day Total, 4-20mA 1, 4-20mA 2. Layouts with 9 fields (151 bytes in total, as specified) and
    8 fields (146 bytes: the size of the packet actually captured, the 9th field absent) are accepted;
    anything else is rejected.

    Only the confirmed structure is recognised. Anything starting "#SP," that deviates from it is
    rejected with a specific MALFORMED_PACKET reason (never passed on to another parser, never VALID).
    """

    PREFIX = b"#SP"
    BINARY_FIELDS = ("instant_flow", "positive_totaliser", "ai3", "ai4", "ai5",
                     "today_total", "previous_day_total", "ma_4_20_1", "ma_4_20_2")
    ACCEPTED_FIELD_COUNTS = (9, 8)
    SENSOR_TYPES = {1: "rs485"}                     # 1 = RS485 (the only value Scanvix has defined)
    _TAIL = re.compile(rb"(?:[0-9]{5},){7}\.")      # 7 x 5 ASCII digits, terminator
    _TAIL_LEN = 7 * 6 + 1
    _DEVICE = re.compile(rb"[A-Za-z0-9_-]{1,32}")
    _IMEI = re.compile(rb"[0-9]{15}")
    _TIME = re.compile(rb"([0-9]{2}):([0-9]{2}):([0-9]{2})")
    _DATE = re.compile(rb"([0-9]{2})/([0-9]{2})/([0-9]{4})")
    _FW = re.compile(rb"[A-Za-z0-9._-]{1,16}")

    def can_parse(self, raw: bytes) -> bool:
        return raw.startswith(self.PREFIX + b",")

    @staticmethod
    def decode_binary_field(name: str, field: bytes) -> float:
        """
        THE single place where the 4-byte telemetry fields are decoded.

        The byte order and the REAL4 / LONG type of each field are NOT yet confirmed (neither the repository
        nor the one captured packet, whose fields are all 00 00 00 00, establishes them), so only the
        confirmed value - all four bytes zero, which is 0 in every encoding - is decoded. Any other value is
        rejected with the raw bytes in the message instead of guessing a number into production telemetry.
        Add the real decoding here once Scanvix confirms the encoding.
        """
        if field == b"\x00\x00\x00\x00":
            return 0.0
        raise PayloadValidationError(
            ValidationErrorCode.MALFORMED_PACKET,
            f"Scanvix frame: binary field '{name}' is {field.hex(' ')}; non-zero binary encoding "
            f"(byte order / REAL4 vs LONG) is not confirmed yet, value not decoded",
        )

    @staticmethod
    def _bad(reason: str, raw: bytes) -> PayloadValidationError:
        return PayloadValidationError(ValidationErrorCode.MALFORMED_PACKET, f"Scanvix #SP frame rejected: {reason}", raw)

    def parse(self, raw: bytes, source_ip: str) -> NormalizedTelemetry:
        frame = raw.rstrip(b"\r\n ")
        parts = frame.split(b",", 8)
        if len(parts) != 9 or parts[0] != self.PREFIX:
            raise self._bad("header incomplete (expected prefix, device, IMEI, time, date, sensor, signal, firmware)", raw)
        _, dev, imei_raw, tm, dt, sensor, signal, fw_raw, rest = parts

        if not self._DEVICE.fullmatch(dev.strip(b"\x00")):
            raise self._bad("device id field is not a plain identifier", raw)
        imei_b = imei_raw.strip(b"\x00")           # the wire carries a leading NUL before the IMEI
        if not self._IMEI.fullmatch(imei_b):
            raise self._bad("IMEI is not exactly 15 digits", raw)
        mt, md = self._TIME.fullmatch(tm), self._DATE.fullmatch(dt)
        if not mt or not md:
            raise self._bad("time must be HH:MM:SS and date DD/MM/YYYY", raw)
        try:
            timestamp = datetime(int(md[3]), int(md[2]), int(md[1]), int(mt[1]), int(mt[2]), int(mt[3]))
        except ValueError:
            raise self._bad("time/date is not a valid calendar value", raw)
        # sensor type: the binary byte 0x01 (an ASCII '1' is tolerated as the same value)
        code = sensor[0] if len(sensor) == 1 and sensor[0] < 32 else (int(sensor) if sensor.isdigit() and len(sensor) == 1 else None)
        if code not in self.SENSOR_TYPES:
            raise self._bad(f"unknown sensor type byte {sensor.hex()}", raw)
        if not (1 <= len(signal) <= 3 and signal.isdigit()):
            raise self._bad("signal field is not a number", raw)
        fw_b = fw_raw.strip(b"\x00")
        if not self._FW.fullmatch(fw_b):
            raise self._bad("firmware field is not a plain version string", raw)

        if len(rest) < self._TAIL_LEN or not self._TAIL.fullmatch(rest[-self._TAIL_LEN:]):
            raise self._bad("trailing block must be 7 five-digit ASCII fields followed by '.'", raw)
        body = rest[: -self._TAIL_LEN]
        n, rem = divmod(len(body), 5)
        if rem or n not in self.ACCEPTED_FIELD_COUNTS or any(body[i * 5 + 4: i * 5 + 5] != b"," for i in range(n)):
            raise self._bad(f"binary block must be {' or '.join(map(str, self.ACCEPTED_FIELD_COUNTS))} "
                            f"comma-terminated 4-byte fields (got {len(body)} bytes)", raw)
        values = {name: self.decode_binary_field(name, body[i * 5: i * 5 + 4])
                  for i, name in enumerate(self.BINARY_FIELDS[:n])}
        trailing = [b.decode("ascii") for b in rest[-self._TAIL_LEN:-1].split(b",") if b]

        # Mapped to existing model fields only. Positive totaliser, AI3-5 and the two 4-20mA inputs have no
        # model field (two inputs vs a single PRESSURE column) and are validated but not persisted; the
        # frame carries no flow unit, so none is invented. READ01-READ05 take the first five trailing fields
        # (7 are sent; the mapping of the last two is unknown, so they are not persisted).
        return NormalizedTelemetry(
            device_id       = imei_b.decode("ascii"),
            protocol        = "TCP",
            timestamp       = timestamp,
            flow            = values["instant_flow"],
            total_today     = values["today_total"],
            total_yesterday = values["previous_day_total"],
            sensor_type     = self.SENSOR_TYPES[code],
            signal_dbm      = int(signal),
            fw_version      = fw_b.decode("ascii"),
            read01=trailing[0], read02=trailing[1], read03=trailing[2], read04=trailing[3], read05=trailing[4],
            source_ip       = source_ip,
        )


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
    ScanvixSpFrameParser(),
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
