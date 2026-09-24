"""
Storm Energy RTU Platform — Telemetry query API.
GET /api/telemetry
GET /api/telemetry/{device_id}
Supports filtering by site, date range, and protocol.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.database.repository import TelemetryRepository

router = APIRouter(prefix="/api/telemetry", tags=["Telemetry"])


class TelemetryOut(BaseModel):
    id:              int
    device_id:       str
    site_id:         Optional[str]
    timestamp:       datetime
    received_at:     datetime
    protocol:        str
    flow:            Optional[float]
    flow_unit:       Optional[str]
    total_today:     Optional[float]
    total_yesterday: Optional[float]
    sensor_type:     Optional[str]
    signal_dbm:      Optional[int]
    battery:         Optional[float]
    firmware_version:Optional[str]
    read01:          Optional[str]
    read02:          Optional[str]
    read03:          Optional[str]
    read04:          Optional[str]
    read05:          Optional[str]
    pressure:        Optional[float]
    is_historical:   bool

    model_config = {"from_attributes": True}


def _to_out(t) -> TelemetryOut:
    return TelemetryOut(
        id              = t.Id,
        device_id       = t.DeviceId,
        site_id         = t.SiteId,
        timestamp       = t.Timestamp,
        received_at     = t.ReceivedAt,
        protocol        = t.Protocol,
        flow            = t.Flow,
        flow_unit       = t.FlowUnit,
        total_today     = t.TotalToday,
        total_yesterday = t.TotalYesterday,
        sensor_type     = t.SensorType,
        signal_dbm      = t.SignalDbm,
        battery         = t.Battery,
        firmware_version= t.FirmwareVersion,
        read01          = t.READ01,
        read02          = t.READ02,
        read03          = t.READ03,
        read04          = t.READ04,
        read05          = t.READ05,
        pressure        = t.Pressure,
        is_historical   = t.IsHistorical,
    )


@router.get("", response_model=List[TelemetryOut], summary="Query telemetry across all devices")
def list_telemetry(
    device_id: Optional[str]   = Query(None),
    site_id:   Optional[str]   = Query(None),
    from_dt:   Optional[datetime] = Query(None, alias="from"),
    to_dt:     Optional[datetime] = Query(None, alias="to"),
    protocol:  Optional[str]   = Query(None, description="MQTT | TCP"),
    limit:     int             = Query(500, le=5000),
    db: Session = Depends(get_db),
):
    if device_id:
        records = TelemetryRepository.get_for_device(db, device_id, from_dt, to_dt, limit)
    else:
        # cross-device query
        from sqlalchemy import select, and_
        from app.database.models import Telemetry
        stmt = select(Telemetry)
        filters = []
        if site_id:   filters.append(Telemetry.SiteId == site_id)
        if from_dt:   filters.append(Telemetry.Timestamp >= from_dt)
        if to_dt:     filters.append(Telemetry.Timestamp <= to_dt)
        if protocol:  filters.append(Telemetry.Protocol == protocol.upper())
        if filters:
            stmt = stmt.where(and_(*filters))
        stmt = stmt.order_by(Telemetry.Timestamp.desc()).limit(limit)
        records = list(db.scalars(stmt))

    return [_to_out(r) for r in records]


@router.get("/{device_id}", response_model=List[TelemetryOut], summary="Query telemetry for one device")
def device_telemetry(
    device_id: str,
    from_dt:   Optional[datetime] = Query(None, alias="from"),
    to_dt:     Optional[datetime] = Query(None, alias="to"),
    limit:     int               = Query(200, le=5000),
    db: Session = Depends(get_db),
):
    records = TelemetryRepository.get_for_device(db, device_id, from_dt, to_dt, limit)
    return [_to_out(r) for r in records]
