"""
Storm Energy RTU Platform - read-only inspection of Protocol Test Log records.

Everything here is DERIVED from what is already stored; nothing is written:
  * exact payload bytes      <- ProtocolDiagnosticLogs.Payload (TEXT = UTF-8, HEX = bytes)
  * safe escaped / hex views <- those bytes
  * parsed telemetry         <- the EXISTING protocol parsers (app.protocol.*) re-run on
                                the stored bytes; they are pure functions (no DB access)
  * decoded JSON + field check against the documented MQTT payload (docs/mqtt-protocol.md)

The ingestion pipeline is not called and not changed.
"""
from __future__ import annotations

import contextvars
import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional

# Documented Scanvix V1.3 telemetry payload keys (docs/mqtt-protocol.md), in document order.
# Required = what the existing parser rejects when absent (app.protocol.mqtt_parser).
DOCUMENTED_FIELDS = (
    "deviceId", "siteid", "ts", "flow", "flowUnit", "totalToday", "totalYesterday", "sensorType",
    "signalDbm", "battery", "fwVersion", "READ01", "READ02", "READ03", "READ04", "READ05", "PRESSURE",
)
REQUIRED_FIELDS = ("deviceId", "ts")
# Spellings the existing parser also accepts for a documented field (not new fields).
ACCEPTED_ALIASES = {"device_id": "deviceId", "siteId": "siteid", "site_id": "siteid",
                    "PRESSURE ": "PRESSURE", "pressure": "PRESSURE"}

# Canonical telemetry fields shown for every parsed packet (NormalizedTelemetry names).
TELEMETRY_FIELDS = ("device_id", "site_id", "timestamp", "flow", "flow_unit", "total_today",
                    "total_yesterday", "sensor_type", "signal_dbm", "battery", "fw_version",
                    "read01", "read02", "read03", "read04", "read05", "pressure")

# ─── keep re-parsing quiet (the parsers log warnings meant for live ingestion) ──────────
_quiet = contextvars.ContextVar("diag_reparse_quiet", default=False)


class _QuietFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return not _quiet.get()


for _name in ("app.protocol.tcp_parser", "app.protocol.mqtt_parser"):
    logging.getLogger(_name).addFilter(_QuietFilter())


@contextmanager
def _quiet_parsers():
    token = _quiet.set(True)
    try:
        yield
    finally:
        _quiet.reset(token)


# ─── bytes / views ──────────────────────────────────────────────────────────────────────

def stored_bytes(payload: str, encoding: str) -> bytes:
    """Exact bytes the server received (up to the stored maximum)."""
    if encoding == "HEX":
        return bytes.fromhex(payload.replace(" ", "")) if payload else b""
    return (payload or "").encode("utf-8")


def hex_view(data: bytes) -> str:
    return data.hex(" ").upper()


def escaped_view(data: bytes) -> str:
    """Printable ASCII kept; CR/LF/TAB shown as \\r \\n \\t; every other byte as \\xHH."""
    out = []
    for b in data:
        if b == 0x5C:
            out.append("\\\\")
        elif b == 0x0D:
            out.append("\\r")
        elif b == 0x0A:
            out.append("\\n")
        elif b == 0x09:
            out.append("\\t")
        elif 0x20 <= b <= 0x7E:
            out.append(chr(b))
        else:
            out.append(f"\\x{b:02x}")
    return "".join(out)


# ─── parsing ────────────────────────────────────────────────────────────────────────────

@dataclass
class Parsed:
    ok: bool
    fields: Optional[dict]              # canonical telemetry fields (None when not parsed)
    error: Optional[str]
    format: str                         # "JSON" | "ASCII" | "BINARY" | "EMPTY"


def payload_format(data: bytes, encoding: str) -> str:
    if not data:
        return "EMPTY"
    if encoding == "HEX":
        return "BINARY"
    s = data.strip()
    return "JSON" if s.startswith(b"{") or s.startswith(b"[") else "ASCII"


def _fields(t) -> dict:
    d = {name: getattr(t, name, None) for name in TELEMETRY_FIELDS}
    d["timestamp"] = t.timestamp.isoformat(sep=" ") if t.timestamp else None
    return d


def reparse(protocol: str, topic: Optional[str], source_ip: Optional[str], data: bytes,
            encoding: str, truncated: bool) -> Parsed:
    """Run the EXISTING parser for this protocol on the stored bytes (read-only)."""
    fmt = payload_format(data, encoding)
    if truncated:
        return Parsed(False, None, "payload was truncated in storage; not re-parsed", fmt)
    from app.protocol.validation import PayloadValidationError
    try:
        with _quiet_parsers():
            if protocol == "TCP":
                from app.protocol.tcp_parser import parse_tcp_packet
                t = parse_tcp_packet(data.strip(), source_ip or "unknown")
            else:
                from app.protocol.mqtt_parser import parse_mqtt_payload
                from app.protocol.mqtt_topics import parse_topic
                pt = parse_topic(topic or "")
                if pt is None or pt.message_type != "telemetry":
                    return Parsed(False, None, None, fmt)       # not a telemetry message
                t = parse_mqtt_payload(topic, data)
        return Parsed(True, _fields(t), None, fmt)
    except PayloadValidationError as ve:
        return Parsed(False, None, f"{ve.error.code.value}: {ve}", fmt)
    except Exception as exc:                                     # never break the viewer
        return Parsed(False, None, f"{type(exc).__name__}: {exc}", fmt)


def decode_json(data: bytes) -> tuple[Any, list[str]]:
    """Decoded JSON object (or None) and any keys that appear more than once."""
    dups: list[str] = []

    def hook(pairs):
        seen = set()
        for k, _ in pairs:
            if k in seen and k not in dups:
                dups.append(k)
            seen.add(k)
        return dict(pairs)                                       # last value wins, like json.loads

    try:
        return json.loads(data.decode("utf-8"), object_pairs_hook=hook), dups
    except Exception:
        return None, []


def field_check(obj: Any, duplicate_keys: list[str]) -> Optional[dict]:
    """Compare a decoded JSON payload with the documented field list (display only)."""
    if not isinstance(obj, dict):
        return None
    rows = []
    for name in DOCUMENTED_FIELDS:
        keys = [name] + [a for a, c in ACCEPTED_ALIASES.items() if c == name]
        key = next((k for k in keys if k in obj), None)
        rows.append({
            "field": name,
            "required": name in REQUIRED_FIELDS,
            "present": key is not None,
            "key": key,
            "is_null": key is not None and obj[key] is None,
            "value": None if key is None else obj[key],
        })
    known = set(DOCUMENTED_FIELDS) | set(ACCEPTED_ALIASES)
    return {
        "fields": rows,
        "undocumented_keys": [k for k in obj if k not in known],
        "duplicate_keys": duplicate_keys,
        "missing_required": [r["field"] for r in rows if r["required"] and (not r["present"] or r["is_null"])],
    }


# ─── pipeline wording ───────────────────────────────────────────────────────────────────

def database_status(outcome: Optional[str], telemetry_id: Optional[int]) -> str:
    return {
        "PROCESSED": f"STORED - telemetry row {telemetry_id}" if telemetry_id else "STORED",
        "DUPLICATE": "DUPLICATE - already stored, not stored again",
        "UNKNOWN_DEVICE": "NOT STORED - device not registered (no auto-registration)",
        "PARSE_ERROR": "NOT STORED - parse error",
        "UNEXPECTED_TOPIC": "NOT STORED - unexpected topic",
        "STATUS": "NOT TELEMETRY - status message",
        "NOT_HANDLED": "NOT TELEMETRY - no handler for this topic type",
        "SERVER_ERROR": "ERROR - see error message",
    }.get(outcome or "", outcome or "UNKNOWN")
