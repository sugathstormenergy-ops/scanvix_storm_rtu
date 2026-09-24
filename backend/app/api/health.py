"""
Storm Energy RTU Platform — Health check endpoints.
GET /health               — overall platform health
GET /health/database      — SQL Server connectivity
GET /health/mqtt          — MQTT broker connectivity
GET /health/tcp           — TCP server status
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.config import get_settings
from app.database.database import check_database_connection

router = APIRouter(prefix="/health", tags=["Health"])

# These are set by main.py after services start
_mqtt_consumer_ref = None
_tcp_server_ref    = None


def set_service_refs(mqtt_consumer, tcp_server) -> None:
    global _mqtt_consumer_ref, _tcp_server_ref
    _mqtt_consumer_ref = mqtt_consumer
    _tcp_server_ref    = tcp_server


class ServiceStatus(BaseModel):
    status:    str        # "ok" | "degraded" | "down"
    details:   str = ""


class HealthResponse(BaseModel):
    status:    str
    timestamp: str
    version:   str
    database:  ServiceStatus
    mqtt:      ServiceStatus
    tcp:       ServiceStatus


@router.get("", response_model=HealthResponse, summary="Overall platform health")
def health_check():
    settings = get_settings()
    db_ok    = check_database_connection()
    mqtt_ok  = _mqtt_consumer_ref.is_connected if _mqtt_consumer_ref else False
    tcp_ok   = _tcp_server_ref is not None

    overall = "ok" if (db_ok and mqtt_ok and tcp_ok) else (
        "degraded" if db_ok else "down"
    )

    return HealthResponse(
        status    = overall,
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        version   = settings.APP_VERSION,
        database  = ServiceStatus(status="ok" if db_ok else "down",
                                  details="SQL Server reachable" if db_ok else "SQL Server unreachable"),
        mqtt      = ServiceStatus(status="ok" if mqtt_ok else "down",
                                  details="Broker connected" if mqtt_ok else "Broker not connected"),
        tcp       = ServiceStatus(status="ok" if tcp_ok else "down",
                                  details=f"{_tcp_server_ref.connection_count if _tcp_server_ref else 0} active connections"),
    )


@router.get("/database", response_model=ServiceStatus, summary="Database connectivity")
def health_database():
    ok = check_database_connection()
    return ServiceStatus(status="ok" if ok else "down",
                         details="SQL Server reachable" if ok else "SQL Server unreachable")


@router.get("/mqtt", response_model=ServiceStatus, summary="MQTT broker connectivity")
def health_mqtt():
    if _mqtt_consumer_ref is None:
        return ServiceStatus(status="down", details="MQTT consumer not started")
    connected = _mqtt_consumer_ref.is_connected
    stats     = _mqtt_consumer_ref.stats
    return ServiceStatus(
        status  = "ok" if connected else "down",
        details = f"messages={stats['messages_processed']} errors={stats['errors']}",
    )


@router.get("/tcp", response_model=ServiceStatus, summary="TCP server status")
def health_tcp():
    if _tcp_server_ref is None:
        return ServiceStatus(status="down", details="TCP server not started")
    return ServiceStatus(
        status  = "ok",
        details = f"{_tcp_server_ref.connection_count} active TCP connections",
    )
