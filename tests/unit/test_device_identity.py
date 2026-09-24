"""
Storm Energy RTU Platform — Tests for device identity validation
(Phase 4: per-device MQTT credentials + ACL security).

Covers the Phase 4 security-review checklist directly against
app.protocol.device_identity:
  - IMEI validation (length, digits-only, ASCII-only)
  - topic injection via device_id (#, +, /)
  - malformed / empty device IDs
  - wildcard characters in device IDs
  - path traversal patterns (../, ..\\, absolute paths)
  - shell-metacharacter payloads (quotes, backticks, $, ;, |, &, newlines)
  - non-string input types
  - username-collision detection across a device list
  - correct derivation for a valid IMEI (matches the Phase 4 spec example)
"""
import sys

sys.path.insert(0, "backend")

import pytest

from app.protocol.device_identity import (
    InvalidDeviceIdError,
    check_no_username_collisions,
    derive_device_identity,
    device_attributes_topic,
    device_cmd_topic,
    device_status_topic,
    device_telemetry_topic,
    validate_device_id,
)

VALID_IMEI = "864012049873321"  # the exact example from the Phase 4 spec


class TestValidDeviceId:

    def test_valid_imei_accepted(self):
        assert validate_device_id(VALID_IMEI) == VALID_IMEI

    def test_derived_identity_matches_phase4_spec_example(self):
        identity = derive_device_identity(VALID_IMEI)
        assert identity.username == "rtu_864012049873321"
        assert identity.topic_root == "storm/meters/864012049873321"

    def test_derived_topics(self):
        assert device_telemetry_topic(VALID_IMEI) == "storm/meters/864012049873321/telemetry"
        assert device_status_topic(VALID_IMEI) == "storm/meters/864012049873321/status"
        assert device_attributes_topic(VALID_IMEI) == "storm/meters/864012049873321/attributes"
        assert device_cmd_topic(VALID_IMEI) == "storm/meters/864012049873321/cmd"


class TestMalformedDeviceId:

    @pytest.mark.parametrize("bad_id", [
        "",                      # empty
        "12345",                 # too short
        "1234567890123456",      # too long (16 digits)
        "86401204987332x",       # trailing non-digit
        "x86401204987332",       # leading non-digit
        "864 012049873321",      # embedded space
        "864012049873321\n",     # trailing newline
        " 864012049873321",      # leading whitespace
        "864012049873321 ",      # trailing whitespace
    ])
    def test_malformed_lengths_and_characters_rejected(self, bad_id):
        with pytest.raises(InvalidDeviceIdError):
            validate_device_id(bad_id)

    def test_none_rejected(self):
        with pytest.raises(InvalidDeviceIdError):
            validate_device_id(None)

    def test_non_string_types_rejected(self):
        for bad in [864012049873321, 123, [], {}, 12.5, True]:
            with pytest.raises(InvalidDeviceIdError):
                validate_device_id(bad)

    def test_unicode_digit_confusable_rejected(self):
        # Arabic-Indic digits look like ASCII digits but are NOT '[0-9]'.
        # Python's default `\d` in `re` matches these -- this module must
        # not, since a value that "looks" like 15 digits but isn't ASCII
        # must never reach a username/topic/filename/shell command.
        arabic_indic_15 = "٨٦٤٠١٢٠٤٩٨٧٣٣٢١"
        assert len(arabic_indic_15) == 15
        with pytest.raises(InvalidDeviceIdError):
            validate_device_id(arabic_indic_15)


class TestInjectionAttempts:
    """device_id values crafted to break out of the topic namespace, the
    filesystem path, or a shell command if validation were weaker."""

    @pytest.mark.parametrize("payload", [
        "864012049873321/#",             # MQTT wildcard: full-tree subscribe
        "864012049873321/+",             # MQTT single-level wildcard
        "#",                              # bare wildcard as device_id
        "+",                              # bare wildcard as device_id
        "../../etc/passwd",               # path traversal (Unix-style)
        "..\\..\\Windows\\System32",      # path traversal (Windows-style)
        "864012049873321/../other",       # traversal appended to a valid-looking prefix
        "864012049873321; rm -rf /",      # shell command injection
        "864012049873321`whoami`",        # backtick command substitution
        "864012049873321$(whoami)",       # $() command substitution
        "864012049873321' OR '1'='1",     # SQL-injection-shaped payload
        "864012049873321\"; DROP TABLE devices; --",
        "864012049873321|cat /etc/shadow",
        "864012049873321&& calc.exe",
        "864012049873321\nrtu_evil",      # newline injection (log/file injection)
        "storm/meters/864012049873322",   # attempt to smuggle another device's topic root directly
        "rtu_864012049873321",            # attempt to pass an already-prefixed username as device_id
    ])
    def test_injection_payloads_rejected(self, payload):
        with pytest.raises(InvalidDeviceIdError):
            validate_device_id(payload)
        with pytest.raises(InvalidDeviceIdError):
            derive_device_identity(payload)


class TestUsernameCollisions:

    def test_no_collision_for_distinct_devices(self):
        devices = [
            {"device_id": "864012049873321"},
            {"device_id": "864012049873322"},
        ]
        check_no_username_collisions(devices)  # must not raise

    def test_duplicate_device_id_detected(self):
        devices = [
            {"device_id": "864012049873321"},
            {"device_id": "864012049873321"},
        ]
        with pytest.raises(ValueError, match="duplicate device_id"):
            check_no_username_collisions(devices)

    def test_invalid_device_id_in_registry_rejected_not_silently_skipped(self):
        devices = [
            {"device_id": "864012049873321"},
            {"device_id": "not-an-imei"},
        ]
        with pytest.raises(InvalidDeviceIdError):
            check_no_username_collisions(devices)
