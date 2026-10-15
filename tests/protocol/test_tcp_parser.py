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


# ─── Scanvix production "#SP" frame (confirmed by Scanvix from a real captured packet) ────────────────

from app.protocol.tcp_parser import ScanvixSpFrameParser   # noqa: E402

Z4 = b"\x00\x00\x00\x00"
SP_HEAD = b"#SP,STORM-ENER,\x00866224083271188,12:52:33,05/10/2026,\x01,28,V001\x00,"
SP_TAIL = b"00000,00000,00000,00000,00000,00000,00000,."


def sp_frame(fields=8, head=SP_HEAD, tail=SP_TAIL, blob=None):
    body = blob if blob is not None else b",".join([Z4] * fields) + b","
    return head + body + tail


# The packet as captured: 146 bytes (eight 4-byte fields). The nine-field form (151 bytes) is the layout in the
# Scanvix field list; both are accepted.
CAPTURED_146 = sp_frame(8)
SPEC_151 = sp_frame(9)


class TestScanvixSpFrame:
    def test_fixture_sizes(self):
        assert len(CAPTURED_146) == 146 and len(SPEC_151) == 151

    @pytest.mark.parametrize("raw", [CAPTURED_146, SPEC_151], ids=["captured-146", "nine-field-151"])
    def test_confirmed_frame_is_accepted_and_decoded(self, raw):
        t = parse_tcp_packet(raw.strip(), "172.18.0.1")
        assert t.device_id == "866224083271188"                  # leading NUL stripped, lookup key
        assert "\x00" not in t.device_id
        assert (t.timestamp.year, t.timestamp.month, t.timestamp.day) == (2026, 10, 5)   # DD/MM/YYYY
        assert (t.timestamp.hour, t.timestamp.minute, t.timestamp.second) == (12, 52, 33)
        assert t.sensor_type == "rs485" and t.signal_dbm == 28 and t.fw_version == "V001"
        assert t.protocol == "TCP" and t.source_ip == "172.18.0.1"
        assert (t.flow, t.total_today, t.total_yesterday) == (0.0, 0.0, 0.0)
        assert [t.read01, t.read02, t.read03, t.read04, t.read05] == ["00000"] * 5   # kept exactly as received

    def test_parser_claims_only_the_sp_prefix(self):
        p = ScanvixSpFrameParser()
        assert p.can_parse(CAPTURED_146)
        for other in (b"#SPX,a", b"SP,a", b"GET / HTTP/1.1", b'{"deviceId":"1"}', b"\x16\x03\x01\x00"):
            assert not p.can_parse(other)

    def test_regression_exact_packet_no_longer_malformed(self):
        try:
            parse_tcp_packet(CAPTURED_146, "127.0.0.1")
        except PayloadValidationError as e:                    # pragma: no cover - the old behaviour
            pytest.fail(f"still rejected: {e}")

    def test_original_bytes_are_untouched_by_parsing(self):
        raw = bytearray(CAPTURED_146)
        parse_tcp_packet(bytes(raw), "x")
        assert bytes(raw) == CAPTURED_146 and raw.count(0) == CAPTURED_146.count(b"\x00") == 1 + 1 + 8 * 4

    def test_sensor_ascii_one_is_the_same_value(self):
        t = parse_tcp_packet(CAPTURED_146.replace(b"\x01,28", b"1,28"), "x")
        assert t.sensor_type == "rs485"

    @pytest.mark.parametrize("mutate", [
        lambda r: r[:-1],                                              # no terminator
        lambda r: r[:-1] + b"!",                                       # wrong terminator
        lambda r: r.replace(b"00000,.", b"000000,."),                  # 6-digit trailing field
        lambda r: r.replace(b"00000,.", b"0000a,."),                   # non-digit trailing field
        lambda r: r.replace(b"\x00866224083271188", b"\x0086622408327118"),    # 14-digit IMEI
        lambda r: r.replace(b"\x00866224083271188", b"\x00866224083271188X"),
        lambda r: r.replace(b"12:52:33", b"12-52-33"),
        lambda r: r.replace(b"05/10/2026", b"2026-10-05"),
        lambda r: r.replace(b"05/10/2026", b"31/02/2026"),             # impossible date
        lambda r: r.replace(b"\x01,28", b"\x07,28"),                   # unknown sensor type
        lambda r: r.replace(b",28,", b",,"),                           # signal missing
        lambda r: r.replace(b"V001\x00", b""),                         # firmware missing
        lambda r: r.replace(b"STORM-ENER", b""),                       # device id missing
        lambda r: sp_frame(7),                                         # too few binary fields
        lambda r: sp_frame(10),                                        # too many
        lambda r: sp_frame(blob=Z4 * 8 + b","),                        # binary fields without separators
        lambda r: b"#SP,STORM-ENER,\x00866224083271188,12:52:33,05/10/2026,\x01,28,V001\x00,.",   # nothing between
        lambda r: b"#SP,junk,junk,junk",
        lambda r: b"#SP," + b"\xff" * 140,
    ])
    def test_malformed_sp_frames_are_rejected_with_a_reason(self, mutate):
        with pytest.raises(PayloadValidationError) as ei:
            parse_tcp_packet(mutate(CAPTURED_146), SOURCE_IP)
        assert ei.value.error.code == ValidationErrorCode.MALFORMED_PACKET
        assert "Scanvix #SP frame rejected" in str(ei.value)

    def test_non_zero_binary_value_is_not_guessed(self):
        # byte order / REAL4-vs-LONG is unconfirmed: refuse rather than store a wrong number
        raw = sp_frame(blob=b"\x00\x00\x80\x3f," + b",".join([Z4] * 7) + b",")
        with pytest.raises(PayloadValidationError) as ei:
            parse_tcp_packet(raw, SOURCE_IP)
        assert "00 00 80 3f" in str(ei.value) and "instant_flow" in str(ei.value)

    def test_binary_value_containing_a_comma_is_not_split(self):
        raw = sp_frame(blob=b"\x00\x2c\x00\x00," + b",".join([Z4] * 7) + b",")
        with pytest.raises(PayloadValidationError) as ei:
            parse_tcp_packet(raw, SOURCE_IP)
        assert "instant_flow" in str(ei.value)      # decoded as one 4-byte field, not as a malformed split

    def test_validation_is_not_weakened_for_other_traffic(self):
        for junk in (b"a,b,c,d", b"GET / HTTP/1.1\r\n\r\n", b"\x16\x03\x01\x00\xa5", b"866224083271188,12:52:33"):
            with pytest.raises(PayloadValidationError) as ei:
                parse_tcp_packet(junk, SOURCE_IP)
            assert "No TCP parser could handle packet" in str(ei.value)

