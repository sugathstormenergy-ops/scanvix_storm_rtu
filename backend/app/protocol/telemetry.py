"""
Storm Energy RTU Platform — Normalized Telemetry dataclass.
Both MQTT and TCP parsers produce this structure before handing off
to the shared TelemetryService.  This is the single integration point.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from app.timezone import now_ist
from typing import Optional


@dataclass
class NormalizedTelemetry:
    """
    Protocol-agnostic telemetry record produced by MQTT and TCP parsers.
    All optional sensor fields default to None and are stored as NULL.
    """
    # Identity — always required
    device_id:   str
    protocol:    str           # "MQTT" | "TCP"

    # Measurement timestamp from the RTU (not the server receive time)
    timestamp:   datetime

    # Core flow measurements
    flow:            Optional[float] = None
    flow_unit:       Optional[str]   = None
    total_today:     Optional[float] = None
    total_yesterday: Optional[float] = None

    # Sensor / modem metadata
    sensor_type:      Optional[str]   = None
    signal_dbm:       Optional[int]   = None
    battery:          Optional[float] = None
    fw_version:       Optional[str]   = None

    # Optional extended registers (RS485 / Modbus additional reads)
    read01: Optional[str]   = None
    read02: Optional[str]   = None
    read03: Optional[str]   = None
    read04: Optional[str]   = None
    read05: Optional[str]   = None

    # Analog inputs / pressure
    pressure: Optional[float] = None

    # Site association (may come from payload or device registry)
    site_id: Optional[str] = None

    # Server-side metadata set after parsing
    raw_message_id:  Optional[int]      = None
    received_at:     datetime            = field(default_factory=lambda: now_ist())
    source_ip:       Optional[str]       = None

    # Set by TelemetryService after comparing timestamp to received_at
    is_historical:   bool = False
