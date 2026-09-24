"""
Storm Energy RTU Platform — Device configuration API.
GET /api/devices/{device_id}/configuration
PUT /api/devices/{device_id}/configuration
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database.database import get_db
from app.services.device_service import DeviceService

router = APIRouter(prefix="/api/devices", tags=["Configuration"])


class ConfigurationOut(BaseModel):
    device_id:          str
    communication_mode: str
    mqtt_broker:        Optional[str]
    mqtt_port:          Optional[int]
    mqtt_tls_enabled:   bool
    tcp_host:           Optional[str]
    tcp_port:           Optional[int]
    reporting_interval: Optional[int]
    apn:                Optional[str]
    slave_id:           Optional[int]
    baud_rate:          Optional[int]
    parity:             Optional[str]
    range_value:        Optional[int]
    updated_at:         Optional[datetime]


class ConfigurationUpdate(BaseModel):
    communication_mode: Optional[str]  = None
    mqtt_broker:        Optional[str]  = None
    mqtt_port:          Optional[int]  = None
    mqtt_tls_enabled:   Optional[bool] = None
    tcp_host:           Optional[str]  = None
    tcp_port:           Optional[int]  = None
    reporting_interval: Optional[int]  = None
    apn:                Optional[str]  = None
    slave_id:           Optional[int]  = None
    baud_rate:          Optional[int]  = None
    parity:             Optional[str]  = None
    range_value:        Optional[int]  = None


@router.get("/{device_id}/configuration", response_model=ConfigurationOut,
            summary="Get device configuration")
def get_configuration(device_id: str, db: Session = Depends(get_db)):
    cfg = DeviceService.get_configuration(db, device_id)
    if cfg is None:
        raise HTTPException(status_code=404,
                            detail=f"No configuration found for device '{device_id}'")
    return _to_out(cfg)


@router.put("/{device_id}/configuration", response_model=ConfigurationOut,
            summary="Update device configuration")
def update_configuration(device_id: str, body: ConfigurationUpdate, db: Session = Depends(get_db)):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    field_map = {
        "communication_mode": "CommunicationMode",
        "mqtt_broker":        "MqttBroker",
        "mqtt_port":          "MqttPort",
        "mqtt_tls_enabled":   "MqttTlsEnabled",
        "tcp_host":           "TcpHost",
        "tcp_port":           "TcpPort",
        "reporting_interval": "ReportingInterval",
        "apn":                "Apn",
        "slave_id":           "SlaveId",
        "baud_rate":          "BaudRate",
        "parity":             "Parity",
        "range_value":        "Range",
    }
    orm_updates = {field_map[k]: v for k, v in updates.items() if k in field_map}
    try:
        cfg = DeviceService.upsert_configuration(db, device_id, **orm_updates)
        db.commit()
        return _to_out(cfg)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


def _to_out(cfg) -> ConfigurationOut:
    return ConfigurationOut(
        device_id          = cfg.DeviceId,
        communication_mode = cfg.CommunicationMode,
        mqtt_broker        = cfg.MqttBroker,
        mqtt_port          = cfg.MqttPort,
        mqtt_tls_enabled   = cfg.MqttTlsEnabled,
        tcp_host           = cfg.TcpHost,
        tcp_port           = cfg.TcpPort,
        reporting_interval = cfg.ReportingInterval,
        apn                = cfg.Apn,
        slave_id           = cfg.SlaveId,
        baud_rate          = cfg.BaudRate,
        parity             = cfg.Parity,
        range_value        = cfg.Range,
        updated_at         = cfg.UpdatedAt,
    )
