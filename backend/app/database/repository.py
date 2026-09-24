"""
Storm Energy RTU Platform — Database Repository Layer.
All DB writes go through this module. Parameterised queries only.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from app.timezone import now_ist
from typing import List, Optional

from sqlalchemy import and_, select, update
from sqlalchemy.orm import Session

from app.database.models import (
    Device, DeviceCommand, DeviceConfiguration,
    DeviceEvent, MQTTMessage, RawMessage, TCPMessage, Telemetry,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Device repository
# ─────────────────────────────────────────────────────────────────────────────

class DeviceRepository:

    @staticmethod
    def get_by_device_id(db: Session, device_id: str) -> Optional[Device]:
        return db.scalar(select(Device).where(Device.DeviceId == device_id))

    @staticmethod
    def get_by_imei(db: Session, imei: str) -> Optional[Device]:
        return db.scalar(select(Device).where(Device.IMEI == imei))

    @staticmethod
    def get_all_active(db: Session) -> List[Device]:
        return list(db.scalars(select(Device).where(Device.IsActive == True)))

    @staticmethod
    def create(db: Session, **kwargs) -> Device:
        device = Device(**kwargs)
        db.add(device)
        db.flush()
        return device

    @staticmethod
    def update_last_seen(db: Session, device_id: str, ip: Optional[str] = None) -> None:
        db.execute(
            update(Device)
            .where(Device.DeviceId == device_id)
            .values(LastSeenAt=now_ist(), LastIPAddress=ip, UpdatedAt=now_ist())
        )

    @staticmethod
    def update_firmware(db: Session, device_id: str, fw_version: str) -> None:
        db.execute(
            update(Device)
            .where(Device.DeviceId == device_id)
            .values(FirmwareVersion=fw_version, UpdatedAt=now_ist())
        )


# ─────────────────────────────────────────────────────────────────────────────
# Telemetry repository
# ─────────────────────────────────────────────────────────────────────────────

class TelemetryRepository:

    @staticmethod
    def exists(db: Session, device_id: str, timestamp: datetime, protocol: str) -> bool:
        """Idempotency check — return True if this exact record already exists."""
        result = db.scalar(
            select(Telemetry.Id)
            .where(
                and_(
                    Telemetry.DeviceId == device_id,
                    Telemetry.Timestamp == timestamp,
                    Telemetry.Protocol == protocol,
                )
            )
        )
        return result is not None

    @staticmethod
    def create(db: Session, **kwargs) -> Telemetry:
        record = Telemetry(**kwargs)
        db.add(record)
        db.flush()
        return record

    @staticmethod
    def get_for_device(
        db: Session,
        device_id: str,
        from_dt: Optional[datetime] = None,
        to_dt: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[Telemetry]:
        stmt = select(Telemetry).where(Telemetry.DeviceId == device_id)
        if from_dt:
            stmt = stmt.where(Telemetry.Timestamp >= from_dt)
        if to_dt:
            stmt = stmt.where(Telemetry.Timestamp <= to_dt)
        stmt = stmt.order_by(Telemetry.Timestamp.desc()).limit(limit)
        return list(db.scalars(stmt))

    @staticmethod
    def get_latest(db: Session, device_id: str) -> Optional[Telemetry]:
        return db.scalar(
            select(Telemetry)
            .where(Telemetry.DeviceId == device_id)
            .order_by(Telemetry.Timestamp.desc())
            .limit(1)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Raw message repository
# ─────────────────────────────────────────────────────────────────────────────

class RawMessageRepository:

    @staticmethod
    def create(db: Session, **kwargs) -> RawMessage:
        msg = RawMessage(**kwargs)
        db.add(msg)
        db.flush()
        return msg


class MQTTMessageRepository:

    @staticmethod
    def create(db: Session, **kwargs) -> MQTTMessage:
        msg = MQTTMessage(**kwargs)
        db.add(msg)
        db.flush()
        return msg

    @staticmethod
    def update_status(db: Session, msg_id: int, status: str) -> None:
        db.execute(update(MQTTMessage).where(MQTTMessage.Id == msg_id).values(Status=status))


class TCPMessageRepository:

    @staticmethod
    def create(db: Session, **kwargs) -> TCPMessage:
        msg = TCPMessage(**kwargs)
        db.add(msg)
        db.flush()
        return msg

    @staticmethod
    def update_status(db: Session, msg_id: int, status: str, ack: Optional[str] = None) -> None:
        values = {"Status": status}
        if ack is not None:
            values["Acknowledgement"] = ack
        db.execute(update(TCPMessage).where(TCPMessage.Id == msg_id).values(**values))


# ─────────────────────────────────────────────────────────────────────────────
# Command repository
# ─────────────────────────────────────────────────────────────────────────────

class CommandRepository:

    @staticmethod
    def create(db: Session, **kwargs) -> DeviceCommand:
        cmd = DeviceCommand(**kwargs)
        db.add(cmd)
        db.flush()
        return cmd

    @staticmethod
    def get_pending(db: Session, device_id: str) -> List[DeviceCommand]:
        return list(
            db.scalars(
                select(DeviceCommand)
                .where(and_(DeviceCommand.DeviceId == device_id, DeviceCommand.Status == "PENDING"))
                .order_by(DeviceCommand.CreatedAt)
            )
        )

    @staticmethod
    def get_for_device(db: Session, device_id: str, limit: int = 100) -> List[DeviceCommand]:
        return list(
            db.scalars(
                select(DeviceCommand)
                .where(DeviceCommand.DeviceId == device_id)
                .order_by(DeviceCommand.CreatedAt.desc())
                .limit(limit)
            )
        )

    @staticmethod
    def mark_sent(db: Session, cmd_id: int) -> None:
        db.execute(
            update(DeviceCommand)
            .where(DeviceCommand.Id == cmd_id)
            .values(Status="SENT", SentAt=now_ist())
        )

    @staticmethod
    def mark_acked(db: Session, cmd_id: int, response: str) -> None:
        db.execute(
            update(DeviceCommand)
            .where(DeviceCommand.Id == cmd_id)
            .values(Status="ACKED", Response=response)
        )


# ─────────────────────────────────────────────────────────────────────────────
# Event repository
# ─────────────────────────────────────────────────────────────────────────────

class EventRepository:

    @staticmethod
    def create(db: Session, **kwargs) -> DeviceEvent:
        evt = DeviceEvent(**kwargs)
        db.add(evt)
        db.flush()
        return evt

    @staticmethod
    def get_for_device(db: Session, device_id: str, limit: int = 200) -> List[DeviceEvent]:
        return list(
            db.scalars(
                select(DeviceEvent)
                .where(DeviceEvent.DeviceId == device_id)
                .order_by(DeviceEvent.Timestamp.desc())
                .limit(limit)
            )
        )

    @staticmethod
    def get_all(db: Session, limit: int = 500) -> List[DeviceEvent]:
        return list(
            db.scalars(
                select(DeviceEvent).order_by(DeviceEvent.Timestamp.desc()).limit(limit)
            )
        )
