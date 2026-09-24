"""
Storm Energy RTU Platform — Unit tests for MQTT parser.
Tests Scanvix V1.3 payload parsing, optional fields, error paths.
"""
import json
import pytest
from datetime import datetime

import sys
sys.path.insert(0, "backend")

from app.protocol.mqtt_parser import parse_mqtt_payload
from app.protocol.validation import PayloadValidationError, ValidationErrorCode


VALID_PAYLOAD = {
    "deviceId":       "864012049873321",
    "siteid":         "BENCH",
    "ts":             "2026-09-01 14:30:00",
    "flow":           12.47,
    "flowUnit":       "m3/h",
    "totalToday":     318.6,
    "totalYesterday": 402.1,
    "sensorType":     "rs485",
    "signalDbm":      -71,
    "battery":        None,
    "fwVersion":      "1.0.0",
    "READ01":         None,
    "READ02":         None,
    "READ03":         None,
    "READ04":         None,
    "READ05":         None,
    "PRESSURE":       None,
}

TOPIC = "storm/meters/864012049873321/telemetry"


class TestMqttParserHappyPath:

    def test_parses_device_id(self):
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD))
        assert t.device_id == "864012049873321"

    def test_parses_timestamp(self):
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD))
        assert t.timestamp == datetime(2026, 9, 1, 14, 30, 0)

    def test_parses_flow(self):
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD))
        assert t.flow == pytest.approx(12.47)

    def test_parses_site_id(self):
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD))
        assert t.site_id == "BENCH"

    def test_optional_fields_are_none(self):
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD))
        assert t.battery  is None
        assert t.read01   is None
        assert t.pressure is None

    def test_protocol_set_to_mqtt(self):
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD))
        assert t.protocol == "MQTT"

    def test_accepts_bytes_payload(self):
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD).encode())
        assert t.device_id == "864012049873321"

    def test_accepts_iso_timestamp(self):
        p = dict(VALID_PAYLOAD, ts="2026-09-01T14:30:00")
        t = parse_mqtt_payload(TOPIC, json.dumps(p))
        assert t.timestamp == datetime(2026, 9, 1, 14, 30, 0)

    def test_accepts_unix_epoch(self):
        epoch = int(datetime(2026, 9, 1, 14, 30, 0).timestamp())
        p = dict(VALID_PAYLOAD, ts=epoch)
        t = parse_mqtt_payload(TOPIC, json.dumps(p))
        assert t.timestamp.year == 2026

    def test_pressure_trailing_space_key(self):
        """Spec V1.3 has 'PRESSURE ' with trailing space — must be handled."""
        p = dict(VALID_PAYLOAD)
        p.pop("PRESSURE", None)
        p["PRESSURE "] = "3.14"
        t = parse_mqtt_payload(TOPIC, json.dumps(p))
        assert t.pressure == pytest.approx(3.14)


class TestMqttParserErrors:

    def test_invalid_json_raises(self):
        with pytest.raises(PayloadValidationError) as exc_info:
            parse_mqtt_payload(TOPIC, b"{not valid json}")
        assert exc_info.value.error.code == ValidationErrorCode.INVALID_JSON

    def test_missing_device_id_raises(self):
        p = dict(VALID_PAYLOAD)
        del p["deviceId"]
        with pytest.raises(PayloadValidationError) as exc_info:
            parse_mqtt_payload(TOPIC, json.dumps(p))
        assert exc_info.value.error.code == ValidationErrorCode.MISSING_DEVICE_ID

    def test_missing_timestamp_raises(self):
        p = dict(VALID_PAYLOAD)
        del p["ts"]
        with pytest.raises(PayloadValidationError) as exc_info:
            parse_mqtt_payload(TOPIC, json.dumps(p))
        assert exc_info.value.error.code == ValidationErrorCode.MISSING_TIMESTAMP

    def test_invalid_timestamp_raises(self):
        p = dict(VALID_PAYLOAD, ts="not-a-date")
        with pytest.raises(PayloadValidationError) as exc_info:
            parse_mqtt_payload(TOPIC, json.dumps(p))
        assert exc_info.value.error.code == ValidationErrorCode.INVALID_TIMESTAMP

    def test_non_numeric_flow_becomes_none(self):
        p = dict(VALID_PAYLOAD, flow="bad")
        t = parse_mqtt_payload(TOPIC, json.dumps(p))
        assert t.flow is None   # gracefully degraded, not raised

    def test_empty_payload_raises(self):
        with pytest.raises(PayloadValidationError):
            parse_mqtt_payload(TOPIC, b"")

    def test_array_payload_raises(self):
        with pytest.raises(PayloadValidationError):
            parse_mqtt_payload(TOPIC, b"[1,2,3]")
