"""
Storm Energy RTU Platform - read-only consumption analytics (SQL aggregation).

CONSUMPTION DEFINITION
    Telemetry.TotalToday is a per-day register that restarts each day. Consumption of a
    device over a window is therefore the sum, over the calendar days touching the window,
    of the highest TotalToday reported on that day inside the window. The first (partial)
    day subtracts the highest value reported earlier the same day, so the window is not
    credited with consumption that happened before it started.

UNITS
    The total's unit is derived from FlowUnit ('m3/h' -> 'm3', 'L/min' -> 'L'). Only units
    with a known conversion to kilolitres (KL) are converted (m3 x1, KL x1, L /1000, ML x1000).
    A device whose unit is missing or unknown is NEVER summed with others; it is reported in
    `excluded` so the caller can say so.

Every function here only SELECTs. Timestamps are the API's naive IST values.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Tuple

from sqlalchemy import Date, String, and_, cast, func, select, true, type_coerce
from sqlalchemy.orm import Session

from app.database.models import Device, Telemetry

_UNIT_RE = re.compile(r"^\s*(.+?)\s*/\s*(h|hr|hrs|hour|min|mins|minute|s|sec|second|d|day)\s*$", re.I)

# lower-cased total unit -> multiplier to kilolitres
_TO_KL = {"m3": 1.0, "m³": 1.0, "kl": 1.0, "l": 0.001, "lit": 0.001, "litre": 0.001, "liter": 0.001,
          "ml": 1000.0, "mld": 1000.0}


def total_unit(flow_unit: Optional[str]) -> Optional[str]:
    if not flow_unit:
        return None
    m = _UNIT_RE.match(str(flow_unit))
    return m.group(1) if m else None


def kl_factor(flow_unit: Optional[str]) -> Optional[float]:
    """Multiplier turning a TotalToday value into KL, or None when it cannot be done safely."""
    u = total_unit(flow_unit)
    return _TO_KL.get(u.lower()) if u else None


@dataclass
class DeviceConsumption:
    device_id: str
    raw: float = 0.0                 # in the device's own total unit
    unit: Optional[str] = None
    kl: Optional[float] = None       # None = not convertible
    days: int = 0


@dataclass
class ConsumptionResult:
    devices: Dict[str, DeviceConsumption] = field(default_factory=dict)

    @property
    def included(self) -> List[DeviceConsumption]:
        return [d for d in self.devices.values() if d.kl is not None]

    @property
    def excluded(self) -> List[DeviceConsumption]:
        return [d for d in self.devices.values() if d.kl is None]

    def total_kl(self) -> Optional[float]:
        inc = self.included
        return sum(d.kl for d in inc) if inc else None


def _day_expr(db: Session):
    """Calendar-day expression. SQL Server: CAST(Timestamp AS DATE). SQLite (tests) has no real
    DATE type - CAST(.. AS DATE) would yield a number - so date() text is used there."""
    if db.get_bind().dialect.name == "sqlite":
        return type_coerce(func.date(Telemetry.Timestamp), String)
    return cast(Telemetry.Timestamp, Date)


def consumption(db: Session, start: datetime, end: datetime,
                device_ids: Optional[Iterable[str]] = None, active_only: bool = False) -> ConsumptionResult:
    """Per-device consumption in [start, end] (see module docstring)."""
    day = _day_expr(db)
    conds = [Telemetry.Timestamp >= start, Telemetry.Timestamp <= end, Telemetry.TotalToday.is_not(None)]
    if device_ids is not None:
        ids = list(device_ids)
        if not ids:
            return ConsumptionResult()
        conds.append(Telemetry.DeviceId.in_(ids))
    stmt = (select(Telemetry.DeviceId, day.label("d"), Telemetry.FlowUnit, func.max(Telemetry.TotalToday))
            .where(and_(*conds)).group_by(Telemetry.DeviceId, day, Telemetry.FlowUnit))
    if active_only:
        stmt = stmt.join(Device, Device.DeviceId == Telemetry.DeviceId).where(Device.IsActive == true())
    rows = db.execute(stmt).all()

    # highest earlier reading on the window's first day, per device (baseline to subtract)
    day0 = start.replace(hour=0, minute=0, second=0, microsecond=0)
    baseline: Dict[Tuple[str, Optional[str]], float] = {}
    if start > day0:
        bconds = [Telemetry.Timestamp >= day0, Telemetry.Timestamp < start, Telemetry.TotalToday.is_not(None)]
        if device_ids is not None:
            bconds.append(Telemetry.DeviceId.in_(list(device_ids)))
        for did, unit, mx in db.execute(
                select(Telemetry.DeviceId, Telemetry.FlowUnit, func.max(Telemetry.TotalToday))
                .where(and_(*bconds)).group_by(Telemetry.DeviceId, Telemetry.FlowUnit)):
            baseline[(did, unit)] = float(mx)

    res = ConsumptionResult()
    unconvertible = set()
    for did, d, unit, mx in rows:
        if mx is None:
            continue
        d = d if isinstance(d, date) else datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
        value = float(mx)
        if d == start.date():
            value -= baseline.get((did, unit), 0.0)
        value = max(value, 0.0)
        dc = res.devices.setdefault(did, DeviceConsumption(device_id=did))
        dc.raw += value
        dc.unit = total_unit(unit)
        dc.days += 1
        f = kl_factor(unit)
        if f is None:
            unconvertible.add(did)
        else:
            dc.kl = (dc.kl or 0.0) + value * f
    # a device that ever reported an unconvertible unit is excluded entirely (never partially summed)
    for did in unconvertible:
        res.devices[did].kl = None
    return res


def daily_totals(db: Session, first_day: date, last_day: date, active_only: bool = True) -> List[dict]:
    """Per calendar day: KL summed over devices (max TotalToday per device per day)."""
    start = datetime.combine(first_day, datetime.min.time())
    end = datetime.combine(last_day, datetime.max.time()).replace(microsecond=0)
    day = _day_expr(db)
    stmt = (select(Telemetry.DeviceId, day.label("d"), Telemetry.FlowUnit, func.max(Telemetry.TotalToday))
            .where(and_(Telemetry.Timestamp >= start, Telemetry.Timestamp <= end, Telemetry.TotalToday.is_not(None)))
            .group_by(Telemetry.DeviceId, day, Telemetry.FlowUnit))
    if active_only:
        stmt = stmt.join(Device, Device.DeviceId == Telemetry.DeviceId).where(Device.IsActive == true())
    bucket: Dict[date, dict] = {}
    excluded_devices: Dict[date, set] = {}
    for did, d, unit, mx in db.execute(stmt):
        if mx is None:
            continue
        d = d if isinstance(d, date) else datetime.strptime(str(d)[:10], "%Y-%m-%d").date()
        f = kl_factor(unit)
        b = bucket.setdefault(d, {"kl": 0.0, "meters": 0, "converted": 0})
        b["meters"] += 1
        if f is None:
            excluded_devices.setdefault(d, set()).add(did)
        else:
            b["kl"] += float(mx) * f
            b["converted"] += 1
    out = []
    cur = first_day
    while cur <= last_day:
        b = bucket.get(cur)
        out.append({
            "date": cur.isoformat(),
            "kl": round(b["kl"], 3) if b and b["converted"] else None,
            "meters": b["converted"] if b else 0,
            "excluded_meters": len(excluded_devices.get(cur, ())),
        })
        cur += timedelta(days=1)
    return out


def flow_stats(db: Session, device_id: str, start: datetime, end: datetime) -> dict:
    row = db.execute(
        select(func.avg(Telemetry.Flow), func.max(Telemetry.Flow), func.min(Telemetry.Flow), func.count(Telemetry.Id))
        .where(and_(Telemetry.DeviceId == device_id, Telemetry.Timestamp >= start,
                    Telemetry.Timestamp <= end, Telemetry.Flow.is_not(None)))
    ).one()
    avg, mx, mn, n = row
    return {"avg": float(avg) if avg is not None else None, "max": float(mx) if mx is not None else None,
            "min": float(mn) if mn is not None else None, "readings": int(n or 0)}


def bucketed_flow(db: Session, device_id: str, start: datetime, end: datetime, bucket: timedelta) -> List[dict]:
    """Flow aggregated into fixed-size buckets (server side, so the browser never gets raw points)."""
    rows = db.execute(
        select(Telemetry.Timestamp, Telemetry.Flow)
        .where(and_(Telemetry.DeviceId == device_id, Telemetry.Timestamp >= start,
                    Telemetry.Timestamp <= end, Telemetry.Flow.is_not(None)))
        .order_by(Telemetry.Timestamp)
    ).all()
    step = int(bucket.total_seconds())
    base = start.replace(minute=0, second=0, microsecond=0) if step < 86400 else start.replace(hour=0, minute=0, second=0, microsecond=0)
    acc: Dict[int, List[float]] = {}
    for ts, flow in rows:
        k = int((ts - base).total_seconds() // step)
        acc.setdefault(k, []).append(float(flow))
    return [{"t": (base + timedelta(seconds=k * step)).isoformat(timespec="seconds"),
             "avg": sum(v) / len(v), "min": min(v), "max": max(v), "n": len(v)}
            for k, v in sorted(acc.items())]
