"""
Storm Energy RTU Platform — Telemetry data generator.
Produces realistic Scanvix telemetry payloads for both MQTT and TCP simulators.
This is a development tool only — it uses the real application protocol.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def make_telemetry(
    device_id: str,
    site_id:   str = "BENCH",
    timestamp: Optional[datetime] = None,
    flow_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Generate a single Scanvix V1.3 MQTT telemetry payload."""
    ts = timestamp or datetime.now(timezone.utc).replace(tzinfo=None)
    flow = flow_override if flow_override is not None else round(random.uniform(0, 50), 2)

    return {
        "deviceId":       device_id,
        "siteid":         site_id,
        "ts":             ts.strftime("%Y-%m-%d %H:%M:%S"),
        "flow":           flow,
        "flowUnit":       "m3/h",
        "totalToday":     round(random.uniform(100, 500), 1),
        "totalYesterday": round(random.uniform(100, 500), 1),
        "sensorType":     "rs485",
        "signalDbm":      random.randint(-100, -50),
        "battery":        None,                              # often null per spec
        "fwVersion":      "1.0.0",
        "READ01":         None,
        "READ02":         None,
        "READ03":         None,
        "READ04":         None,
        "READ05":         None,
        "PRESSURE":       None,
    }


def make_historical_batch(
    device_id: str,
    site_id:   str = "BENCH",
    count:     int = 10,
    start_hours_ago: int = 2,
) -> list[Dict[str, Any]]:
    """Generate a batch of historical telemetry (store-and-forward simulation)."""
    records = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(count):
        ts = now - timedelta(hours=start_hours_ago) + timedelta(minutes=i * 5)
        records.append(make_telemetry(device_id, site_id, timestamp=ts))
    return records


def make_invalid_payload() -> str:
    """Generate a payload that will fail parsing (for error-handling tests)."""
    return '{"broken": true, "ts": "not-a-date"}'


def make_duplicate(base: Dict[str, Any]) -> Dict[str, Any]:
    """Return an identical copy — simulates QoS 1 re-delivery."""
    return dict(base)
