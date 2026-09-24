"""
Storm Energy RTU Platform — Events API.
GET /api/events
GET /api/devices/{device_id}/events
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.services.event_service import EventService

router = APIRouter(tags=["Events"])


class EventOut(BaseModel):
    id:          int
    device_id:   str
    event_type:  str
    description: Optional[str]
    timestamp:   datetime
    protocol:    Optional[str]
    severity:    str


def _to_out(e) -> EventOut:
    return EventOut(
        id          = e.Id,
        device_id   = e.DeviceId,
        event_type  = e.EventType,
        description = e.Description,
        timestamp   = e.Timestamp,
        protocol    = e.Protocol,
        severity    = e.Severity,
    )


@router.get("/api/events", response_model=List[EventOut], summary="List all recent events")
def list_events(limit: int = 200, db: Session = Depends(get_db)):
    events = EventService.get_all(db, limit)
    return [_to_out(e) for e in events]


@router.get("/api/devices/{device_id}/events", response_model=List[EventOut],
            summary="List events for a device")
def device_events(device_id: str, limit: int = 100, db: Session = Depends(get_db)):
    events = EventService.get_for_device(db, device_id, limit)
    return [_to_out(e) for e in events]
