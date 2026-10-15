"""
Read-only analytics API (/api/analytics/*): consumption in KL, daily totals, per-meter
24h / yesterday / last-month comparison, bucketed trend, paginated history and heatmap.
Real FastAPI routes against in-memory SQLite built from the ORM models; "now" is frozen.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("API_SECRET_KEY", "test-only")
os.environ.setdefault("SQL_SERVER", "127.0.0.1")

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
from fastapi import FastAPI                                   # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402
from sqlalchemy import create_engine, event                   # noqa: E402
from sqlalchemy.orm import sessionmaker                       # noqa: E402
from sqlalchemy.pool import StaticPool                        # noqa: E402

from app.api import analytics as analytics_api                # noqa: E402
from app.database.database import Base, get_db                # noqa: E402
from app.database.models import Device, Telemetry             # noqa: E402
from app.services import analytics_service as svc             # noqa: E402

NOW = datetime(2026, 9, 24, 15, 0, 0)          # Thursday, frozen server time (IST)
_tid = iter(range(1, 100_000))


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setattr(analytics_api, "now_ist", lambda: NOW)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Device.__table__, Telemetry.__table__])
    Session = sessionmaker(bind=engine)
    statements = []

    @event.listens_for(engine, "before_cursor_execute")
    def _log(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    app = FastAPI()
    app.include_router(analytics_api.router)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return Session, TestClient(app), statements


def dev(s, did, active=True, lat=None, lng=None, name=None):
    s.add(Device(DeviceId=did, IMEI="I" + did, IsActive=active, CommunicationMode="MQTT", Name=name,
                 Latitude=lat, Longitude=lng, CreatedAt=datetime(2026, 1, 1), UpdatedAt=datetime(2026, 1, 1)))


def tel(s, did, ts, total, flow=1.0, unit="m3/h"):
    s.add(Telemetry(Id=next(_tid), DeviceId=did, Timestamp=ts, ReceivedAt=ts, Protocol="MQTT",
                    Flow=flow, FlowUnit=unit, TotalToday=total, IsHistorical=False))


def test_units_are_converted_only_when_known():
    assert svc.kl_factor("m3/h") == 1.0
    assert svc.kl_factor("L/min") == 0.001
    assert svc.kl_factor("kL/h") == 1.0
    assert svc.kl_factor("gal/h") is None
    assert svc.kl_factor(None) is None
    assert svc.kl_factor("furlong") is None


def test_overview_empty_database_is_null_not_zero(env):
    _, client, _ = env
    j = client.get("/api/analytics/overview").json()
    assert j["total_kl"] is None and j["meters_counted"] == 0 and j["meters_excluded"] == 0


def test_overview_sums_last_24h_across_the_midnight_boundary(env):
    Session, client, statements = env
    with Session() as s:
        dev(s, "A"); dev(s, "B"); dev(s, "OFF", active=False)
        # window = 23-Sep 15:00 .. 24-Sep 15:00
        tel(s, "A", datetime(2026, 9, 23, 10, 0), 5.0)      # before window, same day as window start
        tel(s, "A", datetime(2026, 9, 23, 20, 0), 12.0)     # 12 - 5 baseline = 7 credited to the window
        tel(s, "A", datetime(2026, 9, 24, 14, 0), 9.0)      # today's counter restarted: +9
        tel(s, "B", datetime(2026, 9, 24, 8, 0), 3.0, unit="L/h")     # 3 L -> 0.003 KL
        tel(s, "OFF", datetime(2026, 9, 24, 8, 0), 999.0)   # inactive meters never count
        s.commit()
    j = client.get("/api/analytics/overview").json()
    assert j["total_kl"] == pytest.approx(7 + 9 + 0.003)
    assert j["meters_counted"] == 2 and j["meters_excluded"] == 0


def test_unconvertible_units_are_excluded_and_disclosed_never_summed(env):
    Session, client, _ = env
    with Session() as s:
        dev(s, "A"); dev(s, "X")
        tel(s, "A", datetime(2026, 9, 24, 10, 0), 4.0)
        tel(s, "X", datetime(2026, 9, 24, 10, 0), 500.0, unit="gal/h")
        s.commit()
    j = client.get("/api/analytics/overview").json()
    assert j["total_kl"] == pytest.approx(4.0)
    assert j["meters_counted"] == 1 and j["meters_excluded"] == 1
    # only unconvertible data -> null, not 0
    with Session() as s:
        s.query(Telemetry).filter(Telemetry.DeviceId == "A").delete(); s.commit()
    assert client.get("/api/analytics/overview").json()["total_kl"] is None


def test_daily_totals_one_point_per_day_with_nulls_for_missing_days(env):
    Session, client, _ = env
    with Session() as s:
        dev(s, "A"); dev(s, "B")
        tel(s, "A", datetime(2026, 9, 22, 6, 0), 2.0); tel(s, "A", datetime(2026, 9, 22, 18, 0), 10.0)
        tel(s, "B", datetime(2026, 9, 22, 18, 0), 5.0)
        tel(s, "A", datetime(2026, 9, 24, 9, 0), 1.5)
        s.commit()
    days = client.get("/api/analytics/daily?days=4").json()["days"]
    assert [d["date"] for d in days] == ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24"]
    assert days[0]["kl"] is None and days[2]["kl"] is None
    assert days[1]["kl"] == pytest.approx(15.0) and days[1]["meters"] == 2
    assert days[3]["kl"] == pytest.approx(1.5)


def test_device_consumption_compares_24h_yesterday_last_month(env):
    Session, client, _ = env
    with Session() as s:
        dev(s, "M1")
        tel(s, "M1", datetime(2026, 8, 5, 12, 0), 20.0, flow=2.0)     # last month
        tel(s, "M1", datetime(2026, 8, 6, 12, 0), 30.0, flow=4.0)
        tel(s, "M1", datetime(2026, 9, 23, 12, 0), 11.0, flow=3.0)    # yesterday
        tel(s, "M1", datetime(2026, 9, 24, 9, 0), 6.0, flow=5.0)      # today
        s.commit()
    j = client.get("/api/analytics/devices/M1/consumption").json()
    p = {x["key"]: x for x in j["periods"]}
    assert p["last_month"]["label"] == "Last month (Aug 2026)"
    assert p["last_month"]["consumption_kl"] == pytest.approx(50.0)
    assert p["last_month"]["flow_max"] == 4.0 and p["last_month"]["flow_min"] == 2.0 and p["last_month"]["flow_avg"] == 3.0
    assert p["yesterday"]["consumption_kl"] == pytest.approx(11.0)
    # last 24 h = 23-Sep 15:00 .. 24-Sep 15:00: only today's 6.0 is inside (yesterday's reading is 12:00)
    assert p["last_24h"]["consumption_kl"] == pytest.approx(6.0)
    assert p["last_24h"]["readings"] == 1
    assert j["flow_unit"] == "m3/h"


def test_device_with_no_data_returns_nulls_and_unknown_device_404(env):
    Session, client, _ = env
    with Session() as s:
        dev(s, "EMPTY"); s.commit()
    j = client.get("/api/analytics/devices/EMPTY/consumption").json()
    assert all(x["consumption_kl"] is None and x["flow_avg"] is None and x["readings"] == 0 for x in j["periods"])
    assert client.get("/api/analytics/devices/NOPE/consumption").status_code == 404
    assert client.get("/api/analytics/devices/NOPE/trend").status_code == 404
    assert client.get("/api/analytics/devices/NOPE/history").status_code == 404


def test_trend_is_bucketed_server_side(env):
    Session, client, _ = env
    with Session() as s:
        dev(s, "M1")
        for m in range(0, 60, 5):                       # 12 readings within one hour
            tel(s, "M1", datetime(2026, 9, 24, 10, m), 1.0, flow=float(m))
        tel(s, "M1", datetime(2026, 9, 24, 12, 30), 1.0, flow=100.0)
        s.commit()
    j = client.get("/api/analytics/devices/M1/trend?window=24h").json()
    assert j["bucket_minutes"] == 60 and len(j["points"]) == 2
    assert j["points"][0]["n"] == 12 and j["points"][0]["avg"] == pytest.approx(27.5)
    assert j["points"][0]["min"] == 0 and j["points"][0]["max"] == 55
    assert client.get("/api/analytics/devices/M1/trend?window=30d").json()["bucket_minutes"] == 1440
    assert client.get("/api/analytics/devices/M1/trend?window=99d").status_code == 422


def test_history_pagination_and_order(env):
    Session, client, _ = env
    with Session() as s:
        dev(s, "M1")
        for i in range(25):
            tel(s, "M1", datetime(2026, 9, 24, 0, 0) + timedelta(minutes=i), float(i))
        s.commit()
    j = client.get("/api/analytics/devices/M1/history?page=1&page_size=10").json()
    assert j["total"] == 25 and len(j["items"]) == 10 and j["items"][0]["total_today"] == 24.0
    j3 = client.get("/api/analytics/devices/M1/history?page=3&page_size=10").json()
    assert len(j3["items"]) == 5
    asc = client.get("/api/analytics/devices/M1/history?page_size=10&order=asc").json()
    assert asc["items"][0]["total_today"] == 0.0
    assert client.get("/api/analytics/devices/M1/history?page_size=1000").status_code == 422


def test_heatmap_uses_only_real_coordinates_and_real_consumption(env):
    Session, client, _ = env
    with Session() as s:
        dev(s, "LOC", lat=12.9, lng=77.6, name="Located")
        dev(s, "NOLOC")
        dev(s, "ZERO", lat=0.0, lng=0.0)
        dev(s, "QUIET", lat=13.0, lng=77.5)
        for d in ("LOC", "NOLOC", "ZERO"):
            tel(s, d, datetime(2026, 9, 23, 12, 0), 8.0)
        s.commit()
    j = client.get("/api/analytics/heatmap?period=yesterday").json()
    assert [p["device_id"] for p in j["points"]] == ["LOC"]
    assert j["points"][0]["consumption_kl"] == pytest.approx(8.0)
    assert j["located_meters"] == 2 and j["without_consumption"] == 1      # LOC + QUIET located; QUIET has none
    assert client.get("/api/analytics/heatmap?period=1y").status_code == 422


def test_analytics_endpoints_only_select(env):
    Session, client, statements = env
    with Session() as s:
        dev(s, "M1", lat=12.9, lng=77.6); tel(s, "M1", datetime(2026, 9, 24, 9, 0), 3.0); s.commit()
    statements.clear()
    for url in ("/api/analytics/overview", "/api/analytics/daily", "/api/analytics/devices/M1/consumption",
                "/api/analytics/devices/M1/trend", "/api/analytics/devices/M1/history", "/api/analytics/heatmap"):
        assert client.get(url).status_code == 200
    bad = [x for x in statements if x.lstrip().split(None, 1)[0].upper() not in ("SELECT", "WITH", "PRAGMA")]
    assert bad == []
    for method in (client.post, client.put, client.delete, client.patch):
        assert method("/api/analytics/overview").status_code == 405

def test_sql_server_dialect_never_renders_is_1_for_bit_columns(env):
    """Production regression: SQL Server rejects `IsActive IS 1`. Compile every analytics query with the
    mssql dialect and require `= 1` comparisons."""
    from sqlalchemy.dialects import mssql
    from sqlalchemy import select
    from app.database.models import Device as D
    import re
    compiled = []
    orig = svc.select

    def spy(*a, **k):
        st = orig(*a, **k)
        compiled.append(st)
        return st
    Session, client, _ = env
    svc.select = spy
    try:
        with Session() as s:
            svc.consumption(s, NOW - timedelta(hours=24), NOW, active_only=True)
            svc.daily_totals(s, NOW.date(), NOW.date())
    finally:
        svc.select = orig
    assert compiled
    for st in compiled:
        sql = str(st.compile(dialect=mssql.dialect()))
        assert not re.search(r"\bIS\s+(1|0)\b", sql, re.I), sql
    sql = str(select(D).where(D.IsActive == svc.true()).compile(dialect=mssql.dialect()))
    assert "[IsActive] = 1" in sql


def test_all_analytics_endpoints_return_200_on_empty_database(env):
    _, client, _ = env
    for url in ("/api/analytics/overview", "/api/analytics/daily", "/api/analytics/heatmap?period=yesterday",
                "/api/analytics/heatmap?period=7d", "/api/analytics/heatmap?period=30d"):
        assert client.get(url).status_code == 200, url
    j = client.get("/api/analytics/overview").json()
    assert j["total_kl"] is None and j["meters_counted"] == 0
    h = client.get("/api/analytics/heatmap").json()
    assert h["points"] == [] and h["located_meters"] == 0
    assert all(d["kl"] is None for d in client.get("/api/analytics/daily").json()["days"])

