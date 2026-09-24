"""
Storm Energy RTU Platform — Unit tests for TCP parser.
"""
import json
import pytest
import sys
sys.path.insert(0, "backend")

from app.protocol.tcp_parser import JsonOverTcpParser, parse_tcp_packet
from app.protocol.validation import PayloadValidationError, ValidationErrorCode

VALID_JSON = {
    "deviceId": "864012049873321",
    "siteid":   "BENCH",
    "ts":       "2026-09-01 10:00:00",
    "flow":     5.0,
    "flowUnit": "m3/h",
}
SOURCE_IP = "10.0.0.1"


class TestJsonOverTcpParser:

    def setup_method(self):
        self.parser = JsonOverTcpParser()

    def test_recognises_json(self):
        raw = json.dumps(VALID_JSON).encode()
        assert self.parser.can_parse(raw)

    def test_rejects_non_json(self):
        assert not self.parser.can_parse(b"864012049873321|BENCH|2026-09-01 10:00:00")

    def test_parses_valid_json(self):
        raw = json.dumps(VALID_JSON).encode()
        t   = self.parser.parse(raw, SOURCE_IP)
        assert t.device_id  == "864012049873321"
        assert t.protocol   == "TCP"
        assert t.source_ip  == SOURCE_IP
        assert t.flow       == pytest.approx(5.0)

    def test_invalid_json_raises(self):
        with pytest.raises(PayloadValidationError) as exc:
            self.parser.parse(b"{bad}", SOURCE_IP)
        assert exc.value.error.code == ValidationErrorCode.INVALID_JSON


class TestParseTcpPacket:

    def test_routes_json_to_json_parser(self):
        raw = json.dumps(VALID_JSON).encode()
        t   = parse_tcp_packet(raw, SOURCE_IP)
        assert t.device_id == "864012049873321"
        assert t.protocol  == "TCP"

    def test_unrecognised_packet_raises(self):
        with pytest.raises(PayloadValidationError) as exc:
            parse_tcp_packet(b"\x00\x01\x02", SOURCE_IP)
        assert exc.value.error.code == ValidationErrorCode.MALFORMED_PACKET
