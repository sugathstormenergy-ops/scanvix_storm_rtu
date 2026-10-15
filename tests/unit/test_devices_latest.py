"""
GET /api/devices/latest - read-only, every device + its latest telemetry, ONE SQL statement.
Runs the real FastAPI route against an in-memory SQLite database built from the ORM models.
"""
from __future__ import annotations

import os
from datetime import datetime

import pytest

os.environ.setdefault("API_SECRET_KEY", "test-only")
os.environ.setdefault("SQL_SERVER", "127.0.0.1")

sqlalchemy = pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
from fastapi import FastAPI                                   # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402
from sqlalchemy import create_engine, event                   # noqa: E402
from sqlalchemy.orm import sessionmaker                       # noqa: E402
from sqlalchemy.pool import StaticPool                        # noqa: E402

from app.api import devices as devices_api                    # noqa: E402
from app.database.database import Base, get_db                # noqa: E402
from app.database.models import Device, Telemetry             # noqa: E402
from app.database.repository import DeviceRepository          # noqa: E402


@pytest.fixture()
def env():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Device.__table__, Telemetry.__table__])
    Session = sessionmaker(bind=engine)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _count(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    app = FastAPI()
    app.include_router(devices_api.router)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return Session, TestClient(app), statements


def _dev(s, did, active=True, seen=None, name=None, lat=None, lng=None):
    s.add(Device(DeviceId=did, IMEI="IMEI" + did, IsActive=active, LastSeenAt=seen,
                 CommunicationMode="MQTT", CreatedAt=datetime(2026, 9, 1), UpdatedAt=datetime(2026, 9, 1),
                 Name=name, Latitude=lat, Longitude=lng))


_tid = iter(range(1, 10_000))


def _tel(s, did, ts, flow, tid=None, protocol="MQTT"):
    s.add(Telemetry(Id=tid or next(_tid), DeviceId=did, Timestamp=ts, ReceivedAt=ts, Protocol=protocol,
                    Flow=flow, TotalToday=flow * 10, IsHistorical=False))


def test_every_device_with_latest_or_null_in_one_statement(env):
    Session, client, statements = env
    with Session() as s:
        _dev(s, "A", seen=datetime(2026, 9, 25, 10, 0), name="Meter A", lat=17.385, lng=78.4867)
        _dev(s, "B", seen=datetime(2026, 9, 20, 9, 0))
        _dev(s, "C", seen=None)                          # never communicated -> latest_telemetry null
        _dev(s, "D", active=False, seen=datetime(2026, 9, 1))  # inactive devices are included too
        s.commit()
        _tel(s, "A", datetime(2026, 9, 25, 9, 0), 1.0)
        _tel(s, "A", datetime(2026, 9, 25, 10, 0), 2.0)  # newest for A
        _tel(s, "A", datetime(2026, 9, 24, 23, 0), 0.5)
        _tel(s, "B", datetime(2026, 9, 20, 9, 0), 7.0)
        _tel(s, "D", datetime(2026, 9, 1, 0, 0), 3.0)
        s.commit()
    statements.clear()
    r = client.get("/api/devices/latest")
    assert r.status_code == 200
    select_stmts = [q for q in statements if q.lstrip().upper().startswith("SELECT")]
    assert len(select_stmts) == 1, select_stmts          # NOT N+1
    body = r.json()
    assert "server_time" in body
    by_id = {d["device_id"]: d for d in body["devices"]}
    assert set(by_id) == {"A", "B", "C", "D"}
    assert by_id["A"]["latest_telemetry"]["flow"] == 2.0
    assert by_id["A"]["name"] == "Meter A" and by_id["A"]["latitude"] == pytest.approx(17.385)
    assert by_id["B"]["latest_telemetry"]["flow"] == 7.0
    assert by_id["C"]["latest_telemetry"] is None
    assert by_id["C"]["latitude"] is None and by_id["C"]["longitude"] is None and by_id["C"]["name"] is None
    assert by_id["D"]["is_active"] is False and by_id["D"]["latest_telemetry"]["flow"] == 3.0


def test_statement_count_does_not_grow_with_devices(env):
    Session, client, statements = env
    with Session() as s:
        for i in range(40):
            _dev(s, f"M{i:03d}", seen=datetime(2026, 9, 25))
        s.commit()
        for i in range(40):
            _tel(s, f"M{i:03d}", datetime(2026, 9, 25, 1, 0), float(i))
        s.commit()
    statements.clear()
    assert client.get("/api/devices/latest").status_code == 200
    assert len([q for q in statements if q.lstrip().upper().startswith("SELECT")]) == 1


def test_tie_on_timestamp_is_broken_by_highest_id(env):
    Session, client, _ = env
    with Session() as s:
        _dev(s, "T", seen=datetime(2026, 9, 25))
        s.commit()
        # same timestamp via both channels (schema: UNIQUE DeviceId+Timestamp+Protocol)
        _tel(s, "T", datetime(2026, 9, 25, 8, 0), 1.0, tid=5001, protocol="MQTT")
        _tel(s, "T", datetime(2026, 9, 25, 8, 0), 9.0, tid=5002, protocol="TCP")
        s.commit()
    d = client.get("/api/devices/latest").json()["devices"][0]
    assert d["latest_telemetry"]["id"] == 5002 and d["latest_telemetry"]["flow"] == 9.0


def test_latest_route_is_not_captured_by_device_id_route(env):
    _, client, _ = env
    r = client.get("/api/devices/latest")
    assert r.status_code == 200 and "devices" in r.json()      # not a 404 "Device 'latest' not found"


def test_empty_registry(env):
    _, client, _ = env
    body = client.get("/api/devices/latest").json()
    assert body["devices"] == []


def test_endpoint_is_read_only(env):
    _, client, statements = env
    statements.clear()
    client.get("/api/devices/latest")
    assert not [q for q in statements if q.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE", "MERGE", "ALTER", "CREATE", "DROP"}]


def test_sql_server_statement_is_single_valid_top1_correlated_join():
    from sqlalchemy.dialects import mssql
    sql = str(DeviceRepository.list_with_latest_telemetry_stmt().compile(dialect=mssql.dialect()))
    up = " ".join(sql.upper().split())
    assert "LATERAL" not in up                          # not valid T-SQL
    assert "LEFT OUTER JOIN [TELEMETRY] ON [TELEMETRY].[ID] = (SELECT TOP" in up
    assert "WHERE T_LATEST.[DEVICEID] = [DEVICES].[DEVICEID] ORDER BY T_LATEST.[TIMESTAMP] DESC, T_LATEST.[ID] DESC" in up
    assert up.count("SELECT") == 2                       # outer select + one correlated TOP 1
