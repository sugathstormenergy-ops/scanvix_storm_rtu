"""
Storm Energy RTU Platform — MQTT JSON Payload Parser.

Parses the Scanvix V1.3 MQTT telemetry payload:
{
  "deviceId": "864012049873321",
  "siteid":   "BENCH",
  "ts":       "2026-09-01 14:30:00",
  "flow":     12.47,
  "flowUnit": "m3/h",
  "totalToday": 318.6,
  "totalYesterday": 402.1,
  "sensorType": "rs485",
  "signalDbm": -71,
  "battery":  null,
  "fwVersion": "1.0.0",
  "READ01": null, ... "READ05": null,
  "PRESSURE": null
}

Timestamp formats accepted:
  "YYYY-MM-DD HH:MM:SS"   (V1.3 spec)
  ISO-8601 with T separator (forward-compatible)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.protocol.telemetry import NormalizedTelemetry
from app.protocol.validation import PayloadValidationError, ValidationErrorCode

logger = logging.getLogger(__name__)

_TIMESTAMP_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S",
)


def _parse_timestamp(raw: Any) -> datetime:
    if raw is None:
        raise PayloadValidationError(
            ValidationErrorCode.MISSING_TIMESTAMP, "Field 'ts' is null or absent", raw
        )
    if isinstance(raw, (int, float)):
        # Unix epoch in seconds or milliseconds
        ts = raw / 1000 if raw > 1e10 else raw
        return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
    raw_str = str(raw).strip()
    for fmt in _TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(raw_str, fmt)
        except ValueError:
            continue
    raise PayloadValidationError(
        ValidationErrorCode.INVALID_TIMESTAMP,
        f"Cannot parse timestamp '{raw_str}'",
        raw,
    )


def _safe_float(value: Any, field_name: str) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Field '%s' has non-numeric value '%s' — stored as NULL", field_name, value)
        return None


def _safe_int(value: Any, field_name: str) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Field '%s' has non-integer value '%s' — stored as NULL", field_name, value)
        return None


def parse_mqtt_payload(topic: str, payload: bytes | str) -> NormalizedTelemetry:
    """
    Parse a raw MQTT payload into a NormalizedTelemetry instance.
    Raises PayloadValidationError for unrecoverable failures.
    Non-critical missing fields are silently set to None.
    """
    # 1. Decode bytes
    if isinstance(payload, bytes):
        try:
            payload = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PayloadValidationError(
                ValidationErrorCode.INVALID_JSON, f"UTF-8 decode error: {exc}", payload
            )

    # 2. Parse JSON
    try:
        data: Dict[str, Any] = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PayloadValidationError(
            ValidationErrorCode.INVALID_JSON, f"JSON parse error: {exc}", payload
        )

    if not isinstance(data, dict):
        raise PayloadValidationError(
            ValidationErrorCode.INVALID_JSON, "Payload is not a JSON object", payload
        )

    # 3. Device ID — required
    device_id = data.get("deviceId") or data.get("device_id")
    if not device_id:
        raise PayloadValidationError(
            ValidationErrorCode.MISSING_DEVICE_ID, "Field 'deviceId' is absent or empty", payload
        )
    device_id = str(device_id).strip()

    # 4. Timestamp — required
    timestamp = _parse_timestamp(data.get("ts"))

    # 5. Optional measurement fields
    flow = _safe_float(data.get("flow"), "flow")
    if flow is not None and flow < 0:
        logger.warning("Negative flow value %.4f for device %s — accepted but flagged", flow, device_id)

    # Handle PRESSURE key variants (spec has duplicate "PRESSURE " with trailing space in V1.3)
    pressure_raw = data.get("PRESSURE") or data.get("PRESSURE ") or data.get("pressure")

    return NormalizedTelemetry(
        device_id       = device_id,
        protocol        = "MQTT",
        timestamp       = timestamp,
        site_id         = data.get("siteid") or data.get("siteId") or data.get("site_id"),
        flow            = flow,
        flow_unit       = data.get("flowUnit"),
        total_today     = _safe_float(data.get("totalToday"), "totalToday"),
        total_yesterday = _safe_float(data.get("totalYesterday"), "totalYesterday"),
        sensor_type     = data.get("sensorType"),
        signal_dbm      = _safe_int(data.get("signalDbm"), "signalDbm"),
        battery         = _safe_float(data.get("battery"), "battery"),
        fw_version      = data.get("fwVersion"),
        read01          = data.get("READ01"),
        read02          = data.get("READ02"),
        read03          = data.get("READ03"),
        read04          = data.get("READ04"),
        read05          = data.get("READ05"),
        pressure        = _safe_float(pressure_raw, "PRESSURE"),
    )
