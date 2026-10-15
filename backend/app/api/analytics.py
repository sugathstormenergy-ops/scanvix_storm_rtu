"""
Storm Energy RTU Platform - read-only analytics API (consumption in KL, trends, history, heatmap).

    GET /api/analytics/overview                         Total Today (KL): all active meters, last 24 h
    GET /api/analytics/daily?days=7                     KL per calendar day (all active meters)
    GET /api/analytics/devices/{id}/consumption         last 24 h / yesterday / last month + flow stats
    GET /api/analytics/devices/{id}/trend?window=24h    bucketed flow series (24h | 7d | 30d)
    GET /api/analytics/devices/{id}/history             paginated telemetry rows
    GET /api/analytics/heatmap?period=yesterday         KL per located meter (yesterday | 7d | 30d)

SELECT-only. Times are the API's naive IST values (see app.timezone). Units: see
app.services.analytics_service - only unit-safe conversions to KL are made; meters whose unit
cannot be converted are reported as excluded instead of being summed.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select, true
from sqlalchemy.orm import Session

from app.api.telemetry import TelemetryOut, _to_out
from app.database.database import get_db
from app.database.models import Device, Telemetry
from app.services import analytics_service as svc
from app.timezone import now_ist

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


# -- models -------------------------------------------------------------------
class OverviewOut(BaseModel):
    server_time: datetime
    window_from: datetime
    window_to: datetime
    total_kl: Optional[float]           # null = nothing convertible to report
    meters_counted: int
    meters_excluded: int                # reported a total in a unit that cannot be converted to KL


class DailyPoint(BaseModel):
    date: str
    kl: Optional[float]
    meters: int
    excluded_meters: int


class DailyOut(BaseModel):
    server_time: datetime
    days: List[DailyPoint]


class PeriodOut(BaseModel):
    key: str
    label: str
    window_from: datetime
    window_to: datetime
    days: float
    consumption_kl: Optional[float]     # null = no readings, or unit cannot be converted
    consumption_raw: Optional[float]
    total_unit: Optional[str]
    avg_per_day_kl: Optional[float]
    flow_avg: Optional[float]
    flow_max: Optional[float]
    flow_min: Optional[float]
    readings: int
    unit_convertible: bool


class DeviceConsumptionOut(BaseModel):
    device_id: str
    server_time: datetime
    flow_unit: Optional[str]
    periods: List[PeriodOut]


class TrendPoint(BaseModel):
    t: str
    avg: float
    min: float
    max: float
    n: int


class TrendOut(BaseModel):
    device_id: str
    window: str
    bucket_minutes: int
    flow_unit: Optional[str]
    points: List[TrendPoint]


class HistoryPage(BaseModel):
    device_id: str
    total: int
    page: int
    page_size: int
    items: List[TelemetryOut]


class HeatPoint(BaseModel):
    device_id: str
    name: Optional[str]
    latitude: float
    longitude: float
    consumption_kl: float


class HeatmapOut(BaseModel):
    period: str
    window_from: datetime
    window_to: datetime
    points: List[HeatPoint]
    located_meters: int
    without_consumption: int


# -- helpers ------------------------------------------------------------------
def _device_or_404(db: Session, device_id: str) -> Device:
    d = db.scalar(select(Device).where(Device.DeviceId == device_id))
    if d is None:
        raise HTTPException(status_code=404, detail=f"Device '{device_id}' is not registered")
    return d


def _midnight(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)


def _valid_location(lat, lng) -> bool:
    try:
        la, lo = float(lat), float(lng)
    except (TypeError, ValueError):
        return False
    return -90 <= la <= 90 and -180 <= lo <= 180 and not (la == 0 and lo == 0)


# -- endpoints ----------------------------------------------------------------
@router.get("/overview", response_model=OverviewOut, summary="Total Today (KL): sum of consumption of all active meters, last 24 h")
def overview(db: Session = Depends(get_db)):
    now = now_ist()
    start = now - timedelta(hours=24)
    res = svc.consumption(db, start, now, active_only=True)
    total = res.total_kl()
    return OverviewOut(server_time=now, window_from=start, window_to=now,
                       total_kl=round(total, 3) if total is not None else None,
                       meters_counted=len(res.included), meters_excluded=len(res.excluded))


@router.get("/daily", response_model=DailyOut, summary="Consumption per calendar day (KL), all active meters")
def daily(days: int = Query(7, ge=1, le=62), db: Session = Depends(get_db)):
    now = now_ist()
    first = (now - timedelta(days=days - 1)).date()
    return DailyOut(server_time=now, days=[DailyPoint(**p) for p in svc.daily_totals(db, first, now.date())])


@router.get("/devices/{device_id}/consumption", response_model=DeviceConsumptionOut,
            summary="Last 24 hours vs yesterday vs last month for one meter")
def device_consumption(device_id: str, db: Session = Depends(get_db)):
    _device_or_404(db, device_id)
    now = now_ist()
    today0 = _midnight(now)
    this_month0 = today0.replace(day=1)
    last_month_end = this_month0 - timedelta(seconds=1)
    last_month0 = _midnight(last_month_end).replace(day=1)
    windows = [
        ("last_24h", "Last 24 hours", now - timedelta(hours=24), now),
        ("yesterday", "Yesterday", today0 - timedelta(days=1), today0 - timedelta(seconds=1)),
        ("last_month", f"Last month ({last_month0:%b %Y})", last_month0, last_month_end),
    ]
    latest_unit = db.scalar(select(Telemetry.FlowUnit).where(Telemetry.DeviceId == device_id, Telemetry.FlowUnit.is_not(None))
                            .order_by(Telemetry.Timestamp.desc()).limit(1))
    periods: List[PeriodOut] = []
    for key, label, a, b in windows:
        res = svc.consumption(db, a, b, device_ids=[device_id])
        dc = res.devices.get(device_id)
        fs = svc.flow_stats(db, device_id, a, b)
        days = round((b - a).total_seconds() / 86400, 3)
        kl = dc.kl if dc else None
        periods.append(PeriodOut(
            key=key, label=label, window_from=a, window_to=b, days=days,
            consumption_kl=round(kl, 3) if kl is not None else None,
            consumption_raw=round(dc.raw, 3) if dc else None,
            total_unit=dc.unit if dc else None,
            avg_per_day_kl=round(kl / max(days, 1e-9), 3) if kl is not None else None,
            flow_avg=fs["avg"], flow_max=fs["max"], flow_min=fs["min"], readings=fs["readings"],
            unit_convertible=(dc is None) or (dc.kl is not None),
        ))
    return DeviceConsumptionOut(device_id=device_id, server_time=now, flow_unit=latest_unit, periods=periods)


_TREND = {"24h": (timedelta(hours=24), timedelta(hours=1)),
          "7d": (timedelta(days=7), timedelta(hours=6)),
          "30d": (timedelta(days=30), timedelta(days=1))}


@router.get("/devices/{device_id}/trend", response_model=TrendOut, summary="Bucketed flow series for one meter")
def device_trend(device_id: str, window: Literal["24h", "7d", "30d"] = Query("24h"), db: Session = Depends(get_db)):
    _device_or_404(db, device_id)
    span, bucket = _TREND[window]
    now = now_ist()
    unit = db.scalar(select(Telemetry.FlowUnit).where(Telemetry.DeviceId == device_id, Telemetry.FlowUnit.is_not(None))
                     .order_by(Telemetry.Timestamp.desc()).limit(1))
    pts = svc.bucketed_flow(db, device_id, now - span, now, bucket)
    return TrendOut(device_id=device_id, window=window, bucket_minutes=int(bucket.total_seconds() // 60),
                    flow_unit=unit, points=[TrendPoint(**p) for p in pts])


@router.get("/devices/{device_id}/history", response_model=HistoryPage, summary="Paginated telemetry rows for one meter")
def device_history(
    device_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=10, le=200),
    from_dt: Optional[datetime] = Query(None, alias="from"),
    to_dt: Optional[datetime] = Query(None, alias="to"),
    order: Literal["desc", "asc"] = Query("desc"),
    db: Session = Depends(get_db),
):
    _device_or_404(db, device_id)
    conds = [Telemetry.DeviceId == device_id]
    if from_dt:
        conds.append(Telemetry.Timestamp >= from_dt)
    if to_dt:
        conds.append(Telemetry.Timestamp <= to_dt)
    total = db.scalar(select(func.count(Telemetry.Id)).where(and_(*conds))) or 0
    col = Telemetry.Timestamp.desc() if order == "desc" else Telemetry.Timestamp.asc()
    rows = db.scalars(select(Telemetry).where(and_(*conds)).order_by(col, Telemetry.Id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return HistoryPage(device_id=device_id, total=int(total), page=page, page_size=page_size, items=[_to_out(r) for r in rows])


@router.get("/heatmap", response_model=HeatmapOut, summary="Consumption (KL) per meter with valid coordinates")
def heatmap(period: Literal["yesterday", "7d", "30d"] = Query("yesterday"), db: Session = Depends(get_db)):
    now = now_ist()
    today0 = _midnight(now)
    if period == "yesterday":
        a, b = today0 - timedelta(days=1), today0 - timedelta(seconds=1)
    else:
        a, b = now - timedelta(days=7 if period == "7d" else 30), now
    located = [d for d in db.scalars(select(Device).where(Device.IsActive == true()))
               if _valid_location(d.Latitude, d.Longitude)]
    res = svc.consumption(db, a, b, device_ids=[d.DeviceId for d in located])
    pts, none = [], 0
    for d in located:
        dc = res.devices.get(d.DeviceId)
        if dc is None or dc.kl is None or dc.kl <= 0:
            none += 1
            continue
        pts.append(HeatPoint(device_id=d.DeviceId, name=d.Name, latitude=float(d.Latitude),
                             longitude=float(d.Longitude), consumption_kl=round(dc.kl, 3)))
    return HeatmapOut(period=period, window_from=a, window_to=b, points=pts,
                      located_meters=len(located), without_consumption=none)
