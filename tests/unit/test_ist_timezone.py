"""
Storm Energy RTU Platform — Tests for the IST timezone policy (app/timezone.py).

Covers:
  1. now_ist() actually reflects Asia/Kolkata wall-clock time, not naive
     server-local time and not UTC merely labelled "IST".
  2. ISTFormatter renders %(asctime)s converted to Asia/Kolkata, regardless
     of the server OS timezone, using the real UTC-epoch record.created
     value (not a text-appended label).
  3. Device/RTU-supplied telemetry timestamps (`ts`) are NOT touched by the
     IST policy — they are parsed and preserved exactly as sent, per the
     Scanvix V1.3 spec (mirrors the existing mqtt_parser assertions but
     states the guarantee explicitly for this task).
"""
import logging
import sys
from datetime import datetime, timezone

sys.path.insert(0, "backend")

from app.timezone import IST, ISTFormatter, now_ist
from app.protocol.mqtt_parser import parse_mqtt_payload
import json

TOPIC = "storm/meters/864012049873321/telemetry"
VALID_PAYLOAD = {"deviceId": "864012049873321", "ts": "2026-09-01T14:30:00", "flow": 12.34}


class TestNowIst:

    def test_now_ist_matches_zoneinfo_conversion(self):
        # now_ist() must be a naive datetime whose wall-clock numbers equal
        # a genuine tz-aware Asia/Kolkata conversion, not naive local time.
        reference = datetime.now(IST).replace(tzinfo=None)
        value = now_ist()
        delta = abs((value - reference).total_seconds())
        assert delta < 2, "now_ist() drifted from a direct Asia/Kolkata conversion"

    def test_now_ist_is_ahead_of_utc_by_five_thirty(self):
        utc_naive = datetime.now(timezone.utc).replace(tzinfo=None)
        ist_naive = now_ist()
        offset_minutes = (ist_naive - utc_naive).total_seconds() / 60
        # Expect ~330 minutes (5:30) ahead of naive-UTC, allowing test runtime slack.
        assert 325 <= offset_minutes <= 335


class TestIstFormatter:

    def test_format_time_converts_utc_epoch_to_ist(self):
        formatter = ISTFormatter("%(asctime)s | %(levelname)s | %(message)s")
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="hello", args=(), exc_info=None,
        )
        # A known UTC epoch: 2026-01-01T00:00:00Z -> IST is 2026-01-01T05:30:00
        record.created = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        rendered = formatter.formatTime(record)
        assert rendered == "2026-01-01 05:30:00" or rendered.startswith("2026-01-01 05:30:00")

    def test_default_format_appends_ist_label_to_converted_value(self):
        formatter = ISTFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=1,
            msg="hello", args=(), exc_info=None,
        )
        record.created = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        rendered = formatter.formatTime(record)
        assert rendered == "2026-01-01 05:30:00 IST"


class TestDeviceTimestampUntouched:

    def test_rtu_ts_string_preserved_exactly_no_ist_conversion(self):
        # Guards against ever "fixing" the RTU ts field by conversion: the
        # value must come back byte-for-byte as the wall-clock numbers sent,
        # never shifted by +5:30 or otherwise reinterpreted.
        t = parse_mqtt_payload(TOPIC, json.dumps(VALID_PAYLOAD))
        assert t.timestamp == datetime(2026, 9, 1, 14, 30, 0)
