"""
Storm Energy RTU Platform — Application entry point.

Starts three independently manageable services:
  storm-rtu-api   : FastAPI REST API (uvicorn)
  storm-rtu-mqtt  : MQTT consumer (paho, threaded)
  storm-rtu-tcp   : Raw TCP listener (asyncio)

All three share the same process when run via uvicorn.
For production isolation they can be launched as separate systemd services
using the --service flag; Ansible handles the service wiring.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

import structlog
import uvicorn

from app.timezone import ISTFormatter
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.commands import router as commands_router, set_command_service
from app.api.configuration import router as configuration_router
from app.api.devices import router as devices_router
from app.api.diagnostics import router as diagnostics_router
from app.api.analytics import router as analytics_router
from app.api.events import router as events_router
from app.api.health import router as health_router, set_service_refs
from app.api.telemetry import router as telemetry_router
from app.commands.service import CommandService
from app.config import get_settings
from app.database.database import check_database_connection, engine
from app.database.models import Base
from app.devices.registry import device_registry
from app.mqtt.consumer import MQTTConsumer
from app.tcp.server import TCPServer

# ─────────────────────────────────────────────────────────────────────────────
# Logging — structured, never log credentials
# ─────────────────────────────────────────────────────────────────────────────

def configure_logging(level: str = "INFO") -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.dev.ConsoleRenderer() if os.getenv("APP_ENV", "production") != "production"
            else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    ist_handler = logging.StreamHandler(sys.stdout)
    ist_handler.setFormatter(
        ISTFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    )
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        handlers=[ist_handler],
        force=True,
    )
    # Suppress noisy library loggers
    logging.getLogger("paho.mqtt").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.DEBUG if level == "DEBUG" else logging.WARNING
    )


logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI application
# ─────────────────────────────────────────────────────────────────────────────

settings = get_settings()
configure_logging(settings.LOG_LEVEL)

app = FastAPI(
    title       = settings.APP_NAME,
    version     = settings.APP_VERSION,
    description = (
        "Storm Energy RTU Communication Platform — "
        "MQTT/TCP telemetry ingestion, device management, and REST API."
    ),
    docs_url    = "/docs",
    redoc_url   = "/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],   # tighten in production via reverse proxy
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# Register routers
app.include_router(health_router)
app.include_router(devices_router)
app.include_router(telemetry_router)
app.include_router(commands_router)
app.include_router(configuration_router)
app.include_router(events_router)
app.include_router(diagnostics_router)
app.include_router(analytics_router)

# ─────────────────────────────────────────────────────────────────────────────
# Service singletons
# ─────────────────────────────────────────────────────────────────────────────

_mqtt_consumer: MQTTConsumer | None = None
_tcp_server:    TCPServer    | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Startup / shutdown
# ─────────────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def on_startup():
    global _mqtt_consumer, _tcp_server

    logger.info("Storm Energy RTU Platform starting (env=%s v=%s)",
                settings.APP_ENV, settings.APP_VERSION)

    # 1. Database connectivity check — fail fast if DB is unreachable
    if not check_database_connection():
        logger.critical("Cannot reach SQL Server at startup — check SQL_SERVER / credentials")
        # Do not crash the process; health check will report "down"

    # 2. Load device registry from DB
    try:
        from app.database.database import db_session
        with db_session() as db:
            device_registry.load_from_db(db)
    except Exception as exc:
        logger.error("Failed to load device registry: %s", exc)

    # 3. MQTT consumer (ENABLE_MQTT_CONSUMER, default on)
    if settings.ENABLE_MQTT_CONSUMER:
        try:
            _mqtt_consumer = MQTTConsumer()
            _mqtt_consumer.start()
        except Exception as exc:
            logger.error("MQTT consumer failed to start: %s", exc)
            _mqtt_consumer = None
    else:
        logger.info("MQTT consumer disabled in this process (ENABLE_MQTT_CONSUMER=false)")

    # 4. TCP server (ENABLE_TCP_SERVER, default on). In the Docker deployment the
    #    TCP listener runs in its own container: python -m app.tcp.server
    if settings.ENABLE_TCP_SERVER:
        try:
            _tcp_server = TCPServer()
            await _tcp_server.start()
            # Run TCP server in background
            asyncio.create_task(_tcp_server.serve_forever())
        except Exception as exc:
            logger.error("TCP server failed to start: %s", exc)
            _tcp_server = None
    else:
        logger.info("TCP listener disabled in this process (ENABLE_TCP_SERVER=false)")

    # 5. Command service
    mqtt_client = _mqtt_consumer._client if _mqtt_consumer else None
    cmd_service  = CommandService(mqtt_client=mqtt_client)
    set_command_service(cmd_service)

    # 6. Wire health check service references
    set_service_refs(_mqtt_consumer, _tcp_server)

    # 7. Protocol Test Log retention (30 days): background purge of
    #    dbo.ProtocolDiagnosticLogs ONLY. Runs here (storm-api), never in storm-tcp.
    if settings.DIAG_PURGE_ENABLED:
        from app.diagnostics.retention import retention_loop
        asyncio.create_task(retention_loop())
        logger.info("Protocol diagnostics retention: %d days, checked every %ds",
                    settings.DIAG_RETENTION_DAYS, settings.DIAG_PURGE_INTERVAL_SECONDS)

    logger.info(
        "Platform started — API=%s:%d MQTT=%s TCP=%s",
        settings.API_HOST, settings.API_PORT,
        f"{settings.MQTT_HOST}:{settings.MQTT_PORT}" if settings.ENABLE_MQTT_CONSUMER else "disabled",
        f"{settings.TCP_HOST}:{settings.TCP_PORT}" if settings.ENABLE_TCP_SERVER else "disabled",
    )


@app.on_event("shutdown")
async def on_shutdown():
    logger.info("Storm Energy RTU Platform shutting down …")
    if _mqtt_consumer:
        _mqtt_consumer.stop()
    if _tcp_server:
        await _tcp_server.stop()
    engine.dispose()
    logger.info("Shutdown complete")


# ─────────────────────────────────────────────────────────────────────────────
# CLI entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host    = settings.API_HOST,
        port    = settings.API_PORT,
        log_level = settings.LOG_LEVEL.lower(),
        reload  = settings.APP_ENV == "development",
    )
