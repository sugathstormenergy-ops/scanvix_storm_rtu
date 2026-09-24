"""
Storm Energy RTU Platform — MQTT topic definitions.

Agreed topic hierarchy (from Scanvix V1.3 spec):
  storm/meters/<deviceId>/telemetry
  storm/meters/<deviceId>/status
  storm/meters/<deviceId>/attributes
  storm/meters/<deviceId>/cmd
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

TOPIC_PREFIX = "storm/meters"

# Subscription wildcard — receive all device topics
SUBSCRIBE_ALL = f"{TOPIC_PREFIX}/+/telemetry"
SUBSCRIBE_STATUS = f"{TOPIC_PREFIX}/+/status"
SUBSCRIBE_ATTRIBUTES = f"{TOPIC_PREFIX}/+/attributes"

_TOPIC_RE = re.compile(
    r"^storm/meters/(?P<device_id>[^/]+)/(?P<message_type>telemetry|status|attributes|cmd)$"
)


@dataclass
class ParsedTopic:
    device_id:    str
    message_type: str   # telemetry | status | attributes | cmd


def parse_topic(topic: str) -> Optional[ParsedTopic]:
    """Return ParsedTopic if the topic matches the Storm hierarchy, else None."""
    m = _TOPIC_RE.match(topic)
    if not m:
        return None
    return ParsedTopic(device_id=m.group("device_id"), message_type=m.group("message_type"))


def cmd_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/cmd"


def telemetry_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/telemetry"


def status_topic(device_id: str) -> str:
    return f"{TOPIC_PREFIX}/{device_id}/status"
