"""
Storm Energy RTU Platform — Device management API.
GET  /api/devices
GET  /api/devices/{device_id}
POST /api/devices
PUT  /api/devices/{device_id}
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.services.device_service import DeviceService

router = APIRouter(prefix="/api/devices", tags=["Devices"])


# ── Pydantic schemas ─────────────────────────────────────────────────────────

class DeviceCreate(BaseModel):
    device_id:          str    = Field(..., description="RTU device identifier (IMEI recommended)")
    imei:               str    = Field(..., description="RTU IMEI")
    site_id:            Optional[str] = None
    firmware_version:   Optional[str] = None
    communication_mode: str    = Field("MQTT", description="MQTT | TCP | BOTH")


class DeviceUpdate(BaseModel):
    site_id:            Optional[str] = None
    firmware_version:   Optional[str] = None
    communication_mode: Optional[str] = None
    is_active:          Optional[bool]= None


class DeviceOut(BaseModel):
    device_id:          str
    imei:               str
    site_id:            Optional[str]
    firmware_version:   Optional[str]
    communication_mode: str
    is_active:          bool
    last_seen_at:       Optional[datetime]
    last_ip_address:    Optional[str]
    created_at:         datetime

    model_config = {"from_attributes": True}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=List[DeviceOut], summary="List all active devices")
def list_devices(db: Session = Depends(get_db)):
    devices = DeviceService.get_all(db)
    return [_to_out(d) for d in devices]


@router.get("/{device_id}", response_model=DeviceOut, summary="Get device by ID")
def get_device(device_id: str, db: Session = Depends(get_db)):
    device = DeviceService.get(db, device_id)
    if not device:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail=f"Device '{device_id}' not found")
    return _to_out(device)


@router.post("", response_model=DeviceOut, status_code=status.HTTP_201_CREATED,
             summary="Register a new device")
def register_device(body: DeviceCreate, db: Session = Depends(get_db)):
    try:
        device = DeviceService.register(
            db,
            device_id          = body.device_id,
            imei               = body.imei,
            site_id            = body.site_id,
            firmware_version   = body.firmware_version,
            communication_mode = body.communication_mode,
        )
        db.commit()
        return _to_out(device)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.put("/{device_id}", response_model=DeviceOut, summary="Update device metadata")
def update_device(device_id: str, body: DeviceUpdate, db: Session = Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    # Map snake_case to ORM column names
    field_map = {
        "site_id":            "SiteId",
        "firmware_version":   "FirmwareVersion",
        "communication_mode": "CommunicationMode",
        "is_active":          "IsActive",
    }
    orm_updates = {field_map[k]: v for k, v in updates.items() if k in field_map}
    try:
        device = DeviceService.update(db, device_id, **orm_updates)
        db.commit()
        return _to_out(device)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _to_out(d) -> DeviceOut:
    return DeviceOut(
        device_id          = d.DeviceId,
        imei               = d.IMEI,
        site_id            = d.SiteId,
        firmware_version   = d.FirmwareVersion,
        communication_mode = d.CommunicationMode,
        is_active          = d.IsActive,
        last_seen_at       = d.LastSeenAt,
        last_ip_address    = d.LastIPAddress,
        created_at         = d.CreatedAt,
    )
