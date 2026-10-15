"""
Storm Energy RTU Platform — Health check endpoints.
GET /health               — overall platform health
GET /health/live          — process liveness only (no dependency checks)
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
    status:    str        # "ok" | "down" | "disabled" (component intentionally not run in this process)
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
    """
    Overall status:
      ok       — database reachable and every component enabled in this process is up
      degraded — database reachable, but an enabled MQTT/TCP component is down
      down     — database unreachable (never masked)
    Components disabled via ENABLE_MQTT_CONSUMER / ENABLE_TCP_SERVER are reported as
    "disabled" and do not affect the overall status (e.g. the Docker storm-api container,
    where the TCP listener runs in the separate storm-tcp container).
    """
    settings = get_settings()
    db_ok    = check_database_connection()

    if settings.ENABLE_MQTT_CONSUMER:
        mqtt_ok = _mqtt_consumer_ref.is_connected if _mqtt_consumer_ref else False
        mqtt    = ServiceStatus(status="ok" if mqtt_ok else "down",
                                details="Broker connected" if mqtt_ok else "Broker not connected")
    else:
        mqtt_ok = True
        mqtt    = ServiceStatus(status="disabled", details="MQTT consumer not enabled in this process")

    if settings.ENABLE_TCP_SERVER:
        tcp_ok = _tcp_server_ref is not None
        tcp    = ServiceStatus(status="ok" if tcp_ok else "down",
                               details=f"{_tcp_server_ref.connection_count if _tcp_server_ref else 0} active connections")
    else:
        tcp_ok = True
        tcp    = ServiceStatus(status="disabled", details="TCP listener runs in a separate process/container")

    overall = "ok" if (db_ok and mqtt_ok and tcp_ok) else (
        "degraded" if db_ok else "down"
    )

    return HealthResponse(
        status    = overall,
        timestamp = datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        version   = settings.APP_VERSION,
        database  = ServiceStatus(status="ok" if db_ok else "down",
                                  details="SQL Server reachable" if db_ok else "SQL Server unreachable"),
        mqtt      = mqtt,
        tcp       = tcp,
    )


@router.get("/live", response_model=ServiceStatus, summary="Process liveness (no dependency checks)")
def health_live():
    """Liveness probe for container healthchecks. Says only that the API process is
    serving requests; it deliberately does NOT claim the database is healthy."""
    return ServiceStatus(status="ok", details="API process is serving requests")


@router.get("/database", response_model=ServiceStatus, summary="Database connectivity")
def health_database():
    ok = check_database_connection()
    return ServiceStatus(status="ok" if ok else "down",
                         details="SQL Server reachable" if ok else "SQL Server unreachable")


@router.get("/mqtt", response_model=ServiceStatus, summary="MQTT broker connectivity")
def health_mqtt():
    if not get_settings().ENABLE_MQTT_CONSUMER:
        return ServiceStatus(status="disabled", details="MQTT consumer not enabled in this process")
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
    if not get_settings().ENABLE_TCP_SERVER:
        return ServiceStatus(status="disabled", details="TCP listener runs in a separate process/container")
    if _tcp_server_ref is None:
        return ServiceStatus(status="down", details="TCP server not started")
    return ServiceStatus(
        status  = "ok",
        details = f"{_tcp_server_ref.connection_count} active TCP connections",
    )
