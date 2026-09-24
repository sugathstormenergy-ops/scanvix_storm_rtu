"""
Storm Energy RTU Platform — Device management service.
Business logic for device registration, lookup, and configuration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from app.timezone import now_ist
from typing import List, Optional

from sqlalchemy.orm import Session

from app.database.models import Device, DeviceConfiguration
from app.database.repository import DeviceRepository, EventRepository

logger = logging.getLogger(__name__)


class DeviceService:

    # ── Registration ─────────────────────────────────────────────────────────

    @staticmethod
    def register(
        db: Session,
        *,
        device_id: str,
        imei: str,
        site_id: Optional[str] = None,
        firmware_version: Optional[str] = None,
        communication_mode: str = "MQTT",
    ) -> Device:
        existing = DeviceRepository.get_by_device_id(db, device_id)
        if existing:
            raise ValueError(f"Device '{device_id}' is already registered")

        device = DeviceRepository.create(
            db,
            DeviceId=device_id,
            IMEI=imei,
            SiteId=site_id,
            FirmwareVersion=firmware_version,
            CommunicationMode=communication_mode,
            IsActive=True,
        )
        EventRepository.create(
            db,
            DeviceId    = device_id,
            EventType   = "CONNECTED",
            Description = f"Device registered (mode={communication_mode})",
            Severity    = "INFO",
        )
        logger.info("Device registered: %s (IMEI=%s)", device_id, imei)
        return device

    # ── Lookup ───────────────────────────────────────────────────────────────

    @staticmethod
    def get(db: Session, device_id: str) -> Optional[Device]:
        return DeviceRepository.get_by_device_id(db, device_id)

    @staticmethod
    def get_all(db: Session) -> List[Device]:
        return DeviceRepository.get_all_active(db)

    # ── Update ───────────────────────────────────────────────────────────────

    @staticmethod
    def update(db: Session, device_id: str, **kwargs) -> Device:
        device = DeviceRepository.get_by_device_id(db, device_id)
        if not device:
            raise ValueError(f"Device '{device_id}' not found")
        for key, value in kwargs.items():
            if hasattr(device, key):
                setattr(device, key, value)
        device.UpdatedAt = now_ist()
        db.flush()
        return device

    # ── Configuration ────────────────────────────────────────────────────────

    @staticmethod
    def get_configuration(db: Session, device_id: str) -> Optional[DeviceConfiguration]:
        device = DeviceRepository.get_by_device_id(db, device_id)
        if device:
            return device.configuration
        return None

    @staticmethod
    def upsert_configuration(db: Session, device_id: str, **kwargs) -> DeviceConfiguration:
        device = DeviceRepository.get_by_device_id(db, device_id)
        if not device:
            raise ValueError(f"Device '{device_id}' not found")
        cfg = device.configuration
        if cfg is None:
            cfg = DeviceConfiguration(DeviceId=device_id, **kwargs)
            db.add(cfg)
        else:
            for key, value in kwargs.items():
                if hasattr(cfg, key):
                    setattr(cfg, key, value)
            cfg.UpdatedAt = now_ist()
        db.flush()
        EventRepository.create(
            db,
            DeviceId    = device_id,
            EventType   = "CONFIG_CHANGED",
            Description = f"Configuration updated: {list(kwargs.keys())}",
            Severity    = "INFO",
        )
        return cfg
