"""
Storm Energy RTU Platform — Tests for NormalizedTelemetry and topic parsing.
"""
import sys
sys.path.insert(0, "backend")

from app.protocol.mqtt_topics import parse_topic, cmd_topic, telemetry_topic
from app.protocol.telemetry import NormalizedTelemetry
from datetime import datetime, timezone
from app.timezone import now_ist


class TestTopicParsing:

    def test_parses_telemetry_topic(self):
        t = parse_topic("storm/meters/864012049873321/telemetry")
        assert t is not None
        assert t.device_id    == "864012049873321"
        assert t.message_type == "telemetry"

    def test_parses_status_topic(self):
        t = parse_topic("storm/meters/864012049873321/status")
        assert t is not None
        assert t.message_type == "status"

    def test_rejects_unknown_topic(self):
        assert parse_topic("other/meters/123/data") is None

    def test_rejects_extra_segments(self):
        assert parse_topic("storm/meters/123/telemetry/extra") is None

    def test_cmd_topic_format(self):
        assert cmd_topic("864012049873321") == "storm/meters/864012049873321/cmd"

    def test_telemetry_topic_format(self):
        assert telemetry_topic("864012049873321") == "storm/meters/864012049873321/telemetry"


class TestNormalizedTelemetry:

    def test_defaults_optional_fields_to_none(self):
        t = NormalizedTelemetry(
            device_id="123", protocol="MQTT", timestamp=datetime.now(timezone.utc).replace(tzinfo=None)
        )
        assert t.flow       is None
        assert t.battery    is None
        assert t.pressure   is None
        assert t.read01     is None
        assert not t.is_historical

    def test_received_at_defaults_to_now(self):
        # received_at is a server-generated timestamp; policy is IST (see app/timezone.py).
        before = now_ist()
        t = NormalizedTelemetry(device_id="x", protocol="MQTT", timestamp=datetime.now(timezone.utc).replace(tzinfo=None))
        after = now_ist()
        assert before <= t.received_at <= after
