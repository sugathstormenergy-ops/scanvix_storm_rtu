"""
Storm Energy RTU Platform — IST timezone policy (single source of truth).

Server-generated timestamps (CreatedAt/UpdatedAt/ReceivedAt/LastSeenAt/event
timestamps/log timestamps) use IST (Asia/Kolkata, UTC+05:30) going forward.

This module does NOT touch RTU-supplied telemetry timestamps (`ts` in the
MQTT/TCP payload) -- those are parsed and preserved exactly as sent by
app.protocol.mqtt_parser._parse_timestamp / app.protocol.tcp_parser, per the
Scanvix V1.3 spec, and are out of scope here.

Existing DB columns (SQL Server DATETIME2) are naive (no UTC offset stored).
To avoid any schema change, now_ist() returns a naive datetime whose wall-clock
numbers represent IST -- computed via a genuinely timezone-aware conversion
(datetime.now(IST)), not naive server-local time and not UTC.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist() -> datetime:
    """Current time as a naive datetime whose numbers represent IST wall-clock time."""
    return datetime.now(IST).replace(tzinfo=None)


class ISTFormatter(logging.Formatter):
    """
    logging.Formatter that renders %(asctime)s in IST regardless of the
    server's OS-level timezone, by converting record.created (a UTC epoch
    float) via ZoneInfo -- not the stdlib default (time.localtime) and not a
    naive text-appended "IST" label on an unconverted value.
    """
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created, tz=IST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S") + " IST"
