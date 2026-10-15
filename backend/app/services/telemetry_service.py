"""
Storm Energy RTU Platform — Telemetry Service.

Shared by both MQTT and TCP pipelines.  Single place for:
  - deduplication
  - historical record detection
  - persistence
  - device last-seen update
  - event emission
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from app.timezone import now_ist

from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.repository import (
    DeviceRepository, EventRepository,
    RawMessageRepository, TelemetryRepository,
)
from app.protocol.telemetry import NormalizedTelemetry

logger = logging.getLogger(__name__)


class TelemetryService:

    def __init__(self, settings=None):
        self._settings = settings or get_settings()

    # ── Public entry point ───────────────────────────────────────────────────

    def ingest(self, db: Session, telemetry: NormalizedTelemetry) -> dict:
        """
        Persist a NormalizedTelemetry record.  Returns a result dict:
          { "status": "stored" | "duplicate" | "unknown_device",
            "telemetry_id": int | None,
            "is_historical": bool }
        The caller must commit the session.
        """
        settings = self._settings

        # 1. Verify device exists. Unknown devices are NOT auto-registered: an arbitrary
        #    sender must never create a Devices row. The message itself is already archived
        #    by the caller (RawMessages + TCPMessages/MQTTMessages) and shown in the
        #    Protocol Test Log as UNKNOWN_DEVICE; nothing is written to Devices/Telemetry.
        #    Register the device (POST /api/devices) to start storing its telemetry.
        device = DeviceRepository.get_by_device_id(db, telemetry.device_id)
        if device is None:
            logger.warning(
                "Telemetry from unregistered device %s via %s rejected (not auto-registered)",
                telemetry.device_id, telemetry.protocol,
            )
            return {"status": "unknown_device", "telemetry_id": None, "is_historical": False}

        # 2. Deduplication — QoS 1 may redeliver; check exact (device, timestamp, protocol)
        if TelemetryRepository.exists(db, telemetry.device_id, telemetry.timestamp, telemetry.protocol):
            logger.info(
                "Duplicate telemetry suppressed: device=%s ts=%s proto=%s",
                telemetry.device_id, telemetry.timestamp, telemetry.protocol,
            )
            EventRepository.create(
                db,
                DeviceId=telemetry.device_id,
                EventType="DUPLICATE_TELEMETRY",
                Description=f"Duplicate {telemetry.protocol} record for {telemetry.timestamp}",
                Severity="INFO",
                Protocol=telemetry.protocol,
            )
            return {"status": "duplicate", "telemetry_id": None, "is_historical": False}

        # 3. Historical detection — if RTU timestamp is older than threshold
        age = (now_ist() - telemetry.timestamp).total_seconds()
        is_historical = age > settings.HISTORICAL_THRESHOLD_SECONDS
        telemetry.is_historical = is_historical
        if is_historical:
            logger.info(
                "Historical telemetry received: device=%s ts=%s (age=%.0fs)",
                telemetry.device_id, telemetry.timestamp, age,
            )
            EventRepository.create(
                db,
                DeviceId=telemetry.device_id,
                EventType="HISTORICAL_TELEMETRY",
                Description=f"Store-and-forward record for {telemetry.timestamp} (age {age:.0f}s)",
                Severity="INFO",
                Protocol=telemetry.protocol,
            )

        # 4. Persist telemetry
        record = TelemetryRepository.create(
            db,
            DeviceId        = telemetry.device_id,
            SiteId          = telemetry.site_id or (device.SiteId if device else None),
            Timestamp       = telemetry.timestamp,
            ReceivedAt      = telemetry.received_at,
            Protocol        = telemetry.protocol,
            Flow            = telemetry.flow,
            FlowUnit        = telemetry.flow_unit,
            TotalToday      = telemetry.total_today,
            TotalYesterday  = telemetry.total_yesterday,
            SensorType      = telemetry.sensor_type,
            SignalDbm       = telemetry.signal_dbm,
            Battery         = telemetry.battery,
            FirmwareVersion = telemetry.fw_version,
            READ01          = telemetry.read01,
            READ02          = telemetry.read02,
            READ03          = telemetry.read03,
            READ04          = telemetry.read04,
            READ05          = telemetry.read05,
            Pressure        = telemetry.pressure,
            IsHistorical    = is_historical,
            RawMessageId    = telemetry.raw_message_id,
        )

        # 5. Update device last-seen and firmware
        DeviceRepository.update_last_seen(db, telemetry.device_id, telemetry.source_ip)
        if telemetry.fw_version and device and device.FirmwareVersion != telemetry.fw_version:
            DeviceRepository.update_firmware(db, telemetry.device_id, telemetry.fw_version)
            EventRepository.create(
                db,
                DeviceId    = telemetry.device_id,
                EventType   = "FIRMWARE_CHANGED",
                Description = f"Firmware changed to {telemetry.fw_version}",
                Severity    = "INFO",
                Protocol    = telemetry.protocol,
            )

        return {
            "status":       "stored",
            "telemetry_id": record.Id,
            "is_historical": is_historical,
        }
