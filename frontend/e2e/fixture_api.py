"""
TEST-ONLY fixture API for frontend end-to-end tests. NOT used in production and not
part of any image (frontend/.dockerignore excludes e2e/).

Runs the REAL Storm API routers (devices, telemetry, events, configuration, commands,
health) against a throw-away in-memory SQLite database seeded with fictional meters whose
timestamps are relative to now_ist(), so every status rule is exercised:

  RTU-1001 online  (5 min)    located      RTU-1004 offline (never seen)   no location
  RTU-1002 online  (23 h)     located      RTU-1005 inactive (1 h)         located
  RTU-1003 delayed (3 d)      no location  RTU-1006 delayed (25 h)         no location

Protocol Test Log: also serves the diagnostics router, seeds 120 fictional MQTT
diagnostic rows (pagination), and - when a second argument is given - runs the REAL
TCP listener code (app.tcp.server.handle_client) on that port against the same SQLite
database, so test packets flow through the real parser / archive / diagnostic capture.

Usage:  python fixture_api.py <port> [tcp_port]   (needs the backend requirements installed)
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("API_SECRET_KEY", "fixture-only")
os.environ.setdefault("SQL_SERVER", "127.0.0.1")
os.environ["ENABLE_MQTT_CONSUMER"] = "false"      # no broker in the fixture: report "disabled", not "down"
os.environ["ENABLE_TCP_SERVER"] = "false"
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import uvicorn                                                   # noqa: E402
from fastapi import FastAPI                                      # noqa: E402
from sqlalchemy import create_engine                             # noqa: E402
from sqlalchemy.orm import sessionmaker                          # noqa: E402
from sqlalchemy.pool import StaticPool                           # noqa: E402

from contextlib import contextmanager                            # noqa: E402

from sqlalchemy import BigInteger                                # noqa: E402
from sqlalchemy.ext.compiler import compiles                     # noqa: E402

from app.api import analytics, commands, configuration, devices, diagnostics, events, health, telemetry   # noqa: E402
from app.database.database import Base, get_db                   # noqa: E402
from app.database.models import (Device, DeviceCommand, DeviceConfiguration,     # noqa: E402
                                 DeviceEvent, MQTTMessage, ProtocolDiagnosticLog, RawMessage,
                                 TCPMessage, Telemetry)
from app.timezone import now_ist                                 # noqa: E402


@compiles(BigInteger, "sqlite")
def _bigint_sqlite(type_, compiler, **kw):   # SQLite auto-increments only INTEGER PRIMARY KEY
    return "INTEGER"


engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
Base.metadata.create_all(engine, tables=[Device.__table__, DeviceConfiguration.__table__, Telemetry.__table__,
                                         DeviceCommand.__table__, DeviceEvent.__table__, RawMessage.__table__,
                                         TCPMessage.__table__, MQTTMessage.__table__,
                                         ProtocolDiagnosticLog.__table__])
Session = sessionmaker(bind=engine)


def seed() -> None:
    now = now_ist().replace(microsecond=0)
    created = now - timedelta(days=30)

    def dev(did, site, seen, name=None, lat=None, lng=None, active=True, mode="MQTT"):
        return Device(DeviceId=did, IMEI="86" + did[-4:].rjust(13, "0"), SiteId=site, FirmwareVersion="2.4.1",
                      CommunicationMode=mode, IsActive=active, LastSeenAt=seen, LastIPAddress=None,
                      CreatedAt=created, UpdatedAt=created, Name=name, Latitude=lat, Longitude=lng)

    with Session() as s:
        s.add_all([
            dev("RTU-1001", "SITE-NORTH", now - timedelta(minutes=5), "Pump House 1", 17.385000, 78.486700),
            dev("RTU-1002", "SITE-NORTH", now - timedelta(hours=23), "Reservoir Inlet", 17.401000, 78.502000, mode="TCP"),
            dev("RTU-1003", "SITE-SOUTH", now - timedelta(days=3)),
            dev("RTU-1004", "SITE-SOUTH", None),
            dev("RTU-1005", "SITE-EAST", now - timedelta(hours=1), "Old Booster", 17.370000, 78.470000, active=False),
            dev("RTU-1006", None, now - timedelta(hours=25)),
        ])
        s.commit()

        tid = 1

        def tel(did, ts, flow, proto="MQTT", site=None, **kw):
            nonlocal tid
            row = Telemetry(Id=tid, DeviceId=did, SiteId=site, Timestamp=ts, ReceivedAt=ts, Protocol=proto,
                            Flow=flow, FlowUnit="m3/h", TotalToday=kw.get("total_today"),
                            TotalYesterday=kw.get("total_yesterday", 812.4), SensorType=kw.get("sensor", "EMF"),
                            SignalDbm=kw.get("signal", -73), Battery=kw.get("battery", 3.61), FirmwareVersion="2.4.1",
                            READ01=kw.get("read01"), READ02=kw.get("read02"), READ03=None, READ04=None, READ05=None,
                            Pressure=kw.get("pressure"), IsHistorical=False)
            tid += 1
            return row

        rows = []
        for h in range(48, -1, -1):                      # hourly for 48 h, newest = 5 min ago
            ts = now - timedelta(hours=h, minutes=5)
            rows.append(tel("RTU-1001", ts, 30 + (h % 12) * 1.5, site="SITE-NORTH",
                            total_today=round(35.0 * (ts.hour + 1), 2), pressure=2.0 + (h % 5) * 0.1,
                            read01="0x0012", read02="OK"))
        for h in range(40, 25, -2):
            rows.append(tel("RTU-1002", now - timedelta(hours=h), 12.0 + h * 0.2, proto="TCP", site="SITE-NORTH",
                            total_today=180.0, sensor="ULTRASONIC", signal=-95, battery=3.35))
        rows.append(tel("RTU-1002", now - timedelta(hours=23), 18.5, proto="TCP", site="SITE-NORTH",
                        total_today=220.0, sensor="ULTRASONIC", signal=-97, battery=3.3))
        rows.append(tel("RTU-1003", now - timedelta(days=3), 4.0, site="SITE-SOUTH", total_today=50.0, signal=-108))
        rows.append(tel("RTU-1005", now - timedelta(hours=1), 9.0, site="SITE-EAST", total_today=77.0))
        rows.append(tel("RTU-1006", now - timedelta(hours=25), 2.5, total_today=15.0, signal=-88, battery=None))
        s.add_all(rows)

        s.add(DeviceConfiguration(DeviceId="RTU-1001", CommunicationMode="MQTT", MqttBroker="mqtt.example.invalid",
                                  MqttPort=8883, MqttTlsEnabled=True, ReportingInterval=900, Apn="internet",
                                  SlaveId=1, BaudRate=9600, Parity="N", Range=100, CreatedAt=created, UpdatedAt=created))
        s.add_all([
            DeviceCommand(Id=1, DeviceId="RTU-1001", Protocol="MQTT", Command="GET_STATUS", Payload='{"cmd":"status"}',
                          CreatedAt=now - timedelta(days=2), SentAt=now - timedelta(days=2), Response="OK",
                          Status="ACKNOWLEDGED"),
            DeviceCommand(Id=2, DeviceId="RTU-1001", Protocol="MQTT", Command="SET_INTERVAL", Payload='{"interval":900}',
                          CreatedAt=now - timedelta(days=1), SentAt=None, Response=None, Status="PENDING"),
        ])
        s.add_all([
            DeviceEvent(Id=1, DeviceId="RTU-1001", EventType="DEVICE_ONLINE", Description="First message received",
                        Timestamp=now - timedelta(days=2), Protocol="MQTT", Severity="INFO", CreatedAt=now),
            DeviceEvent(Id=2, DeviceId="RTU-1003", EventType="LOW_SIGNAL", Description="Signal below -105 dBm",
                        Timestamp=now - timedelta(days=3), Protocol="MQTT", Severity="WARNING", CreatedAt=now),
        ])
        s.commit()

        for i in range(120):                              # MQTT diagnostic history for pagination
            ts = now - timedelta(hours=2, seconds=-i * 30)
            ok = i % 3 != 0
            s.add(ProtocolDiagnosticLog(
                ReceivedAt=ts, CreatedAt=ts, Protocol="MQTT", Status="VALID" if ok else "INVALID",
                Outcome="PROCESSED" if ok else "PARSE_ERROR", DeviceId="RTU-1001" if ok else None,
                DeviceName="Pump House 1" if ok else None, IMEI="860000000001001" if ok else None,
                SiteId="SITE-NORTH" if ok else None, IsRegistered=ok, Topic="storm/meters/RTU-1001/telemetry", QoS=1,
                Payload=f'{{"deviceId":"RTU-1001","seq":{i}}}' if ok else "{not json",
                PayloadEncoding="TEXT", PayloadBytes=30, PayloadTruncated=False,
                ErrorReason=None if ok else "INVALID_JSON: JSON parse error"))
        s.commit()


def _db():
    s = Session()
    try:
        yield s
    finally:
        s.close()


health.check_database_connection = lambda: True      # the SQLite fixture is always "reachable"

app = FastAPI(title="Storm RTU fixture API (TEST ONLY)")
for r in (analytics.router, health.router, devices.router, telemetry.router, commands.router, configuration.router, events.router,
          diagnostics.router):
    app.include_router(r)
app.dependency_overrides[get_db] = _db
seed()

TCP_PORT = int(sys.argv[2]) if len(sys.argv) > 2 else None
if TCP_PORT:
    import asyncio

    import app.tcp.server as tcp_mod
    from app.diagnostics import recorder

    @contextmanager
    def _fixture_session():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    tcp_mod.db_session = _fixture_session            # real listener code, fixture database
    recorder._session_factory = Session

    @app.on_event("startup")
    async def _start_tcp():
        app.state.tcp = await asyncio.start_server(tcp_mod.handle_client, "127.0.0.1", TCP_PORT)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 18000, log_level="warning")
