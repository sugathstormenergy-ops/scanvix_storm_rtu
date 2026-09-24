"""
Storm Energy RTU Platform — Event service.
Centralised creation of DeviceEvents with structured logging.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from app.timezone import now_ist
from typing import List, Optional

from sqlalchemy.orm import Session

from app.database.models import DeviceEvent
from app.database.repository import EventRepository

logger = logging.getLogger(__name__)


class EventService:

    @staticmethod
    def record(
        db: Session,
        *,
        device_id: str,
        event_type: str,
        description: Optional[str] = None,
        protocol: Optional[str] = None,
        severity: str = "INFO",
    ) -> DeviceEvent:
        event = EventRepository.create(
            db,
            DeviceId    = device_id,
            EventType   = event_type,
            Description = description,
            Protocol    = protocol,
            Severity    = severity,
            Timestamp   = now_ist(),
        )
        logger.info(
            "Event recorded: device=%s type=%s severity=%s proto=%s — %s",
            device_id, event_type, severity, protocol, description,
        )
        return event

    @staticmethod
    def get_for_device(db: Session, device_id: str, limit: int = 200) -> List[DeviceEvent]:
        return EventRepository.get_for_device(db, device_id, limit)

    @staticmethod
    def get_all(db: Session, limit: int = 500) -> List[DeviceEvent]:
        return EventRepository.get_all(db, limit)
