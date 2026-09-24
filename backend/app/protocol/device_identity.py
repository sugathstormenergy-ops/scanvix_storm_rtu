"""
Storm Energy RTU Platform — Device identity validation and derivation
(Phase 4: per-device MQTT credentials + ACL security).

This module is the single source of truth for turning a raw, untrusted
device identifier (as supplied by an operator, a provisioning script, or
Ansible `-e`) into the values used to build an MQTT username, a topic
namespace, and — in the Ansible tasks that consume this design — a
filename and a shell command argument on scanvix109.

SECURITY: every one of those destinations (username string embedded in a
Mosquitto ACL, MQTT topic string, Windows filename, PowerShell command
argument) has a different, well-known injection risk if fed an unvalidated
string:
  - ACL/topic injection:      '#', '+', '/', or any MQTT wildcard/separator
                               character would let a "device" claim a topic
                               outside its own namespace, or inject extra
                               ACL lines if ever templated unsafely.
  - Path traversal:            '..', '/', '\\' in a value used to build a
                               per-device filename could escape the
                               intended secrets directory.
  - Shell/command injection:   quotes, backticks, '$', ';', '|', '&', etc.
                               in a value later interpolated into a
                               PowerShell command (mosquitto_passwd -b ...).
  - Unicode digit confusables: Python's default `\\d` in `re` matches any
                               Unicode decimal digit (e.g. Arabic-Indic
                               digits U+0660-0669), not just ASCII 0-9 --
                               using `\\d` here would let a string that
                               *looks* like 15 digits but isn't ASCII slip
                               through and behave unpredictably downstream.

The fix used throughout this module: a single explicit ASCII character
class `[0-9]` (never `\\d`), a fixed length (15, the Scanvix V1.3 IMEI
length), and `re.fullmatch` (not `search`/`match`, which do not anchor the
end of the string). A device_id that fails this check is rejected before
it is ever used to build a username, topic, filename, or command argument.

DOCUMENTED (Scanvix V1.3, per docs/mqtt-protocol.md): IMEI is a 15-digit
device identifier; topic hierarchy is storm/meters/<deviceId>/{telemetry,
status,attributes,cmd}.

PROJECT DESIGN (not vendor-specified): the "rtu_<IMEI>" username prefix,
the exact validation strictness (15 ASCII digits, nothing else accepted),
and the derived topic/filename helpers below are this project's own
security design, not something Scanvix's documentation mandates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ASCII-only, fixed-length. Deliberately NOT `\d` (see module docstring).
_IMEI_RE = re.compile(r"^[0-9]{15}$")

TOPIC_PREFIX = "storm/meters"
USERNAME_PREFIX = "rtu_"


class InvalidDeviceIdError(ValueError):
    """Raised when a device_id fails validation. Never silently coerced."""


def validate_device_id(device_id: object) -> str:
    """
    Validate that device_id is a 15-digit ASCII IMEI string.

    Accepts only `str` input (a non-str such as an int, None, list, etc. is
    rejected outright — silently calling str() on an arbitrary object is
    itself a source of surprising injected values, e.g. from YAML parsing
    an unquoted number with leading zeros stripped).

    Returns the validated device_id unchanged on success.
    Raises InvalidDeviceIdError on any other input, with a message that
    never echoes back more than a length-capped, repr()'d snippet of the
    offending value (avoids reflecting attacker-controlled content
    verbatim into logs in a way that could itself be misleading/spoofable).
    """
    if not isinstance(device_id, str):
        raise InvalidDeviceIdError(
            f"device_id must be a string, got {type(device_id).__name__}"
        )
    if not _IMEI_RE.fullmatch(device_id):
        snippet = repr(device_id[:32])
        raise InvalidDeviceIdError(
            f"device_id must be exactly 15 ASCII digits (Scanvix IMEI format); "
            f"rejected value (truncated): {snippet}"
        )
    return device_id


@dataclass(frozen=True)
class DeviceIdentity:
    device_id:  str
    username:   str
    topic_root: str


def derive_device_identity(device_id: str) -> DeviceIdentity:
    """
    Validate device_id and derive its MQTT username and topic root.

    Raises InvalidDeviceIdError if device_id is not a valid IMEI. Never
    returns a partially-derived result for invalid input.
    """
    validated = validate_device_id(device_id)
    return DeviceIdentity(
        device_id=validated,
        username=f"{USERNAME_PREFIX}{validated}",
        topic_root=f"{TOPIC_PREFIX}/{validated}",
    )


def device_telemetry_topic(device_id: str) -> str:
    return f"{derive_device_identity(device_id).topic_root}/telemetry"


def device_status_topic(device_id: str) -> str:
    return f"{derive_device_identity(device_id).topic_root}/status"


def device_attributes_topic(device_id: str) -> str:
    return f"{derive_device_identity(device_id).topic_root}/attributes"


def device_cmd_topic(device_id: str) -> str:
    return f"{derive_device_identity(device_id).topic_root}/cmd"


def check_no_username_collisions(devices: list) -> None:
    """
    Given a list of dicts/objects each exposing `.device_id` (or a
    `device_id` key), raise ValueError if two devices would derive the
    same username or the same raw device_id. Used by device-registry
    validation before any credential is provisioned -- a registry-level
    guard against the exact collision scenario the Phase 4 security
    review calls out.
    """
    seen_ids: set = set()
    seen_usernames: set = set()
    for entry in devices:
        device_id = entry["device_id"] if isinstance(entry, dict) else entry.device_id
        identity = derive_device_identity(device_id)
        if identity.device_id in seen_ids:
            raise ValueError(f"duplicate device_id in registry: {identity.device_id}")
        if identity.username in seen_usernames:
            raise ValueError(f"duplicate derived username in registry: {identity.username}")
        seen_ids.add(identity.device_id)
        seen_usernames.add(identity.username)
