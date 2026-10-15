"""
Storm Energy RTU Platform - Protocol Test Log API (READ-ONLY).

GET /api/diagnostics/server-time
GET /api/diagnostics/tcp            ?page=1&page_size=50&status=&device_id=&imei=&source_ip=
GET /api/diagnostics/mqtt           ?page=1&page_size=50&status=&device_id=&topic=
GET /api/diagnostics/{tcp|mqtt}/{id}   one record with the complete stored payload

Testing / Protocol Monitor (combined TCP + MQTT, same table, same read-only rule):
GET /api/diagnostics/summary        ?window=today|1h|24h|7d|all   counts + service states
GET /api/diagnostics/sources        ?window=...                  every device/source seen
GET /api/diagnostics/packets        ?protocol=ALL|TCP|MQTT&status=&device_id=&site_id=&source_ip=
                                     &topic=&window=...|custom&from=&to=&page=&page_size=
GET /api/diagnostics/packets/{id}   parsed telemetry, raw text, escaped, hex, pipeline status

Only SELECTs against dbo.ProtocolDiagnosticLogs. There is deliberately no endpoint that
creates, changes or deletes diagnostic records (retention runs as a background task).
All timestamps are the SERVER receipt time (naive IST, like every other table) and are
also returned pre-formatted as "DD-Mon-YYYY HH:MM:SS IST" so no client ever has to
interpret or convert them.
"""
from __future__ import annotations

import socket
import threading
import time
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.database import get_db
from app.database.models import ProtocolDiagnosticLog
from app.diagnostics import inspect
from app.timezone import now_ist

router = APIRouter(prefix="/api/diagnostics", tags=["Diagnostics"])

PAGE_SIZES = (50, 100, 250)
PREVIEW_CHARS = 160
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def format_ist(dt: Optional[datetime]) -> Optional[str]:
    """Naive IST datetime -> 'DD-Mon-YYYY HH:MM:SS IST' (no timezone conversion)."""
    if dt is None:
        return None
    return f"{dt.day:02d}-{_MONTHS[dt.month - 1]}-{dt.year:04d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} IST"


class Protocol(str, Enum):
    tcp = "tcp"
    mqtt = "mqtt"


class StatusFilter(str, Enum):
    VALID = "VALID"
    INVALID = "INVALID"
    UNKNOWN_DEVICE = "UNKNOWN_DEVICE"


class ServerTimeOut(BaseModel):
    server_time: datetime
    server_time_display: str
    timezone: str
    retention_days: int


class DiagnosticItem(BaseModel):
    id: int
    received_at: datetime
    received_at_display: str
    protocol: str
    status: str
    outcome: Optional[str]
    source_ip: Optional[str]
    device_id: Optional[str]
    device_name: Optional[str]
    imei: Optional[str]
    site_id: Optional[str]
    is_registered: bool
    topic: Optional[str]
    qos: Optional[int]
    payload_preview: str
    payload_encoding: str
    payload_bytes: int
    payload_truncated: bool
    error_reason: Optional[str]


class DiagnosticDetail(DiagnosticItem):
    payload: str          # complete stored payload (text, or spaced hex for binary)


class DiagnosticPage(BaseModel):
    protocol: str
    page: int
    page_size: int
    total: int
    total_pages: int
    latest_received_at: Optional[datetime]
    latest_received_at_display: Optional[str]
    server_time: datetime
    server_time_display: str
    retention_days: int
    items: List[DiagnosticItem]


def _preview(payload: str) -> str:
    one = payload.replace("\r", "\\r").replace("\n", "\\n").replace("\t", "\\t")
    return one if len(one) <= PREVIEW_CHARS else one[: PREVIEW_CHARS - 1] + "…"


def _item(r: ProtocolDiagnosticLog, cls=DiagnosticItem, **extra):
    return cls(
        id=r.Id, received_at=r.ReceivedAt, received_at_display=format_ist(r.ReceivedAt),
        protocol=r.Protocol, status=r.Status, outcome=r.Outcome, source_ip=r.SourceIP,
        device_id=r.DeviceId, device_name=r.DeviceName, imei=r.IMEI, site_id=r.SiteId,
        is_registered=bool(r.IsRegistered), topic=r.Topic, qos=r.QoS,
        payload_preview=_preview(r.Payload or ""), payload_encoding=r.PayloadEncoding,
        payload_bytes=r.PayloadBytes, payload_truncated=bool(r.PayloadTruncated),
        error_reason=r.ErrorReason, **extra,
    )


def _contains(column, value: str):
    """Case-insensitive substring filter with LIKE wildcards escaped (parameterised)."""
    esc = value.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace("[", "\\[")
    return column.like(f"%{esc}%", escape="\\")


@router.get("/server-time", response_model=ServerTimeOut, summary="Authoritative server time (IST)")
def server_time():
    now = now_ist().replace(microsecond=0)
    return ServerTimeOut(server_time=now, server_time_display=format_ist(now),
                         timezone="Asia/Kolkata (IST, UTC+05:30)",
                         retention_days=get_settings().DIAG_RETENTION_DAYS)


# ═════════════════════════════════════════════════════════════════════════════
# Testing / Protocol Monitor (combined TCP + MQTT). Same table, same read-only rule.
# Everything below is derived from ProtocolDiagnosticLogs (the source of truth) plus
# read-only lookups; parsed fields come from re-running the EXISTING parsers.
# Declared before "/{protocol}" so these paths are not captured by that route.
# ═════════════════════════════════════════════════════════════════════════════

WINDOWS = {"1h": timedelta(hours=1), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
PROTOCOL_LABEL = {"TCP": "TCP / ASCII", "MQTT": "MQTT / JSON"}


class ProtocolFilter(str, Enum):
    ALL = "ALL"
    TCP = "TCP"
    MQTT = "MQTT"


def _window_bounds(window: str, date_from: Optional[datetime], date_to: Optional[datetime], now: datetime):
    """Server-clock window -> (from, to). 'today' = since 00:00 server (IST) time."""
    if window == "custom":
        if date_from and date_to and date_from > date_to:
            raise HTTPException(status_code=422, detail="'from' must not be after 'to'")
        return date_from, date_to
    if window == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0), None
    if window == "all":
        return None, None
    if window in WINDOWS:
        return now - WINDOWS[window], None
    raise HTTPException(status_code=422, detail="window must be one of today, 1h, 24h, 7d, all, custom")


def _window_conds(T, lo, hi):
    conds = []
    if lo is not None:
        conds.append(T.ReceivedAt >= lo)
    if hi is not None:
        conds.append(T.ReceivedAt <= hi)
    return conds


def _parsed_for(r):
    data = inspect.stored_bytes(r.Payload or "", r.PayloadEncoding)
    if r.Status == "INVALID":
        return None, data
    p = inspect.reparse(r.Protocol, r.Topic, r.SourceIP, data, r.PayloadEncoding, bool(r.PayloadTruncated))
    return (p.fields if p.ok else None), data


class ServiceState(BaseModel):
    status: str            # ok | down | disabled | unknown
    details: str = ""


class TestingSummary(BaseModel):
    server_time: datetime
    server_time_display: str
    window: str
    window_from: Optional[datetime]
    window_from_display: Optional[str]
    total: int
    valid: int
    unknown_device: int
    invalid: int
    by_protocol: dict
    last_packet_at: Optional[datetime]
    last_packet_at_display: Optional[str]
    last_packet_protocol: Optional[str]
    services: dict
    retention_days: int


class SourceRow(BaseModel):
    key: str
    protocol: str
    protocol_label: str
    device_id: Optional[str]
    device_name: Optional[str]
    imei: Optional[str]
    site_id: Optional[str]
    source_ip: Optional[str]
    topic: Optional[str]
    is_registered: bool
    device_is_active: Optional[bool]
    device_last_seen_at: Optional[datetime]
    last_seen_at: datetime
    last_seen_at_display: str
    last_status: str
    last_result: Optional[str]
    packet_count: int
    last_flow: Optional[float]
    last_flow_unit: Optional[str]
    last_total_today: Optional[float]
    last_signal_dbm: Optional[int]
    last_packet_id: int


class SourcesOut(BaseModel):
    server_time: datetime
    server_time_display: str
    window: str
    items: List[SourceRow]
    truncated: bool


class PacketItem(BaseModel):
    id: int
    received_at: datetime
    received_at_display: str
    protocol: str
    protocol_label: str
    status: str
    outcome: Optional[str]
    device_id: Optional[str]
    device_name: Optional[str]
    imei: Optional[str]
    site_id: Optional[str]
    source_ip: Optional[str]
    topic: Optional[str]
    qos: Optional[int]
    size: int
    flow: Optional[float]
    flow_unit: Optional[str]
    total_today: Optional[float]
    error_reason: Optional[str]
    payload_encoding: str
    payload_preview: str


class PacketPage(BaseModel):
    page: int
    page_size: int
    total: int
    total_pages: int
    window: str
    latest_received_at: Optional[datetime]
    latest_received_at_display: Optional[str]
    server_time: datetime
    server_time_display: str
    items: List[PacketItem]


class PacketDetail(PacketItem):
    server_time: datetime
    server_time_display: str
    is_registered: bool
    transport_received: str
    parse_status: str
    database_status: str
    acknowledgement: str
    raw_message_id: Optional[int]
    telemetry_id: Optional[int]
    payload_format: str
    payload_complete: bool
    payload_text: Optional[str]       # exact text as received (None for binary)
    payload_escaped: str              # \xHH for control / non-ASCII bytes
    payload_hex: str                  # every stored byte
    telemetry: Optional[dict]         # canonical fields from the existing parser (None = not parsed)
    decoded_json: Optional[object]
    field_check: Optional[dict]
    reparse_error: Optional[str]


def _packet_item(r, fields, cls=PacketItem, **extra):
    f = fields or {}
    return cls(
        id=r.Id, received_at=r.ReceivedAt, received_at_display=format_ist(r.ReceivedAt),
        protocol=r.Protocol, protocol_label=PROTOCOL_LABEL.get(r.Protocol, r.Protocol), status=r.Status,
        outcome=r.Outcome, device_id=r.DeviceId, device_name=r.DeviceName, imei=r.IMEI,
        site_id=r.SiteId or f.get("site_id"), source_ip=r.SourceIP, topic=r.Topic, qos=r.QoS,
        size=r.PayloadBytes, flow=f.get("flow"), flow_unit=f.get("flow_unit"), total_today=f.get("total_today"),
        error_reason=r.ErrorReason, payload_encoding=r.PayloadEncoding, payload_preview=_preview(r.Payload or ""),
        **extra,
    )


# TCP listener liveness. The listener runs in the storm-tcp container, so storm-api checks
# it with a plain TCP connect (no data sent), at most once per minute.
_tcp_probe_cache: dict = {"at": 0.0, "value": None}
_tcp_probe_lock = threading.Lock()


def _tcp_listener_state() -> ServiceState:
    s = get_settings()
    host = s.DIAG_TCP_PROBE_HOST
    if not host:
        return ServiceState(status="unknown", details="probe disabled (DIAG_TCP_PROBE_HOST empty)")
    with _tcp_probe_lock:
        if _tcp_probe_cache["value"] is not None and time.monotonic() - _tcp_probe_cache["at"] < 60:
            return _tcp_probe_cache["value"]
        try:
            with socket.create_connection((host, s.TCP_PORT), timeout=1.5):
                pass
            v = ServiceState(status="ok", details=f"listening on {host}:{s.TCP_PORT}")
        except OSError as exc:
            v = ServiceState(status="down", details=f"{host}:{s.TCP_PORT} not reachable ({exc.__class__.__name__})")
        _tcp_probe_cache.update(at=time.monotonic(), value=v)
        return v


def _services() -> dict:
    from app.api.health import health_check
    h = health_check()
    return {
        "api": ServiceState(status="ok", details=f"version {h.version}").model_dump(),
        "database": ServiceState(status=h.database.status, details=h.database.details).model_dump(),
        "mqtt_broker": ServiceState(status=h.mqtt.status, details=h.mqtt.details).model_dump(),
        "tcp_listener": _tcp_listener_state().model_dump(),
    }


@router.get("/summary", response_model=TestingSummary, summary="Testing status bar: counts and service states")
def testing_summary(window: str = Query("today"), db: Session = Depends(get_db)):
    now = now_ist().replace(microsecond=0)
    lo, hi = _window_bounds(window, None, None, now)
    T = ProtocolDiagnosticLog
    rows = db.execute(select(T.Protocol, T.Status, func.count()).where(*_window_conds(T, lo, hi))
                      .group_by(T.Protocol, T.Status)).all()
    by = {p: {"total": 0, "VALID": 0, "UNKNOWN_DEVICE": 0, "INVALID": 0} for p in ("TCP", "MQTT")}
    for proto, status, n in rows:
        b = by.setdefault(proto, {"total": 0, "VALID": 0, "UNKNOWN_DEVICE": 0, "INVALID": 0})
        b[status] = b.get(status, 0) + n
        b["total"] += n
    last = db.execute(select(T.ReceivedAt, T.Protocol).order_by(T.ReceivedAt.desc(), T.Id.desc()).limit(1)).first()
    return TestingSummary(
        server_time=now, server_time_display=format_ist(now), window=window,
        window_from=lo, window_from_display=format_ist(lo),
        total=sum(b["total"] for b in by.values()), valid=sum(b["VALID"] for b in by.values()),
        unknown_device=sum(b["UNKNOWN_DEVICE"] for b in by.values()), invalid=sum(b["INVALID"] for b in by.values()),
        by_protocol=by, last_packet_at=last[0] if last else None,
        last_packet_at_display=format_ist(last[0]) if last else None, last_packet_protocol=last[1] if last else None,
        services=_services(), retention_days=get_settings().DIAG_RETENTION_DAYS,
    )


@router.get("/sources", response_model=SourcesOut, summary="Every device / source seen in the window (latest packet each)")
def testing_sources(window: str = Query("24h"), limit: int = Query(500, ge=1, le=1000), db: Session = Depends(get_db)):
    from app.database.models import Device
    now = now_ist().replace(microsecond=0)
    lo, hi = _window_bounds(window, None, None, now)
    T = ProtocolDiagnosticLog
    key = func.coalesce(T.DeviceId, T.SourceIP, T.Topic)        # no bound literal: identical text in GROUP BY
    agg = (select(T.Protocol.label("proto"), key.label("k"), func.count().label("n"), func.max(T.Id).label("last_id"))
           .where(*_window_conds(T, lo, hi)).group_by(T.Protocol, key).subquery())
    rows = db.execute(select(T, agg.c.n).join(agg, T.Id == agg.c.last_id)
                      .order_by(T.ReceivedAt.desc(), T.Id.desc()).limit(limit + 1)).all()
    truncated = len(rows) > limit
    rows = rows[:limit]
    ids = {r.DeviceId for r, _ in rows if r.DeviceId}
    devices = {d.DeviceId: d for d in db.scalars(select(Device).where(Device.DeviceId.in_(ids)))} if ids else {}
    items = []
    for r, n in rows:
        fields, _ = _parsed_for(r)
        f = fields or {}
        d = devices.get(r.DeviceId) if r.DeviceId else None
        items.append(SourceRow(
            key=f"{r.Protocol}:{r.DeviceId or r.SourceIP or r.Topic or '?'}", protocol=r.Protocol,
            protocol_label=PROTOCOL_LABEL.get(r.Protocol, r.Protocol), device_id=r.DeviceId,
            device_name=d.Name if d else r.DeviceName, imei=d.IMEI if d else r.IMEI,
            site_id=(d.SiteId if d and d.SiteId else None) or r.SiteId or f.get("site_id"),
            source_ip=r.SourceIP, topic=r.Topic, is_registered=d is not None,
            device_is_active=d.IsActive if d else None, device_last_seen_at=d.LastSeenAt if d else None,
            last_seen_at=r.ReceivedAt, last_seen_at_display=format_ist(r.ReceivedAt), last_status=r.Status,
            last_result=r.Outcome, packet_count=n, last_flow=f.get("flow"), last_flow_unit=f.get("flow_unit"),
            last_total_today=f.get("total_today"), last_signal_dbm=f.get("signal_dbm"), last_packet_id=r.Id,
        ))
    return SourcesOut(server_time=now, server_time_display=format_ist(now), window=window, items=items, truncated=truncated)


@router.get("/packets", response_model=PacketPage, summary="Live packet stream, TCP and MQTT (newest first)")
def testing_packets(
    protocol: ProtocolFilter = Query(ProtocolFilter.ALL),
    status: Optional[StatusFilter] = Query(None),
    device_id: Optional[str] = Query(None, max_length=50),
    site_id: Optional[str] = Query(None, max_length=50),
    source_ip: Optional[str] = Query(None, max_length=45),
    topic: Optional[str] = Query(None, max_length=255),
    window: str = Query("24h"),
    date_from: Optional[datetime] = Query(None, alias="from"),
    date_to: Optional[datetime] = Query(None, alias="to"),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50),
    db: Session = Depends(get_db),
):
    if page_size not in PAGE_SIZES:
        raise HTTPException(status_code=422, detail=f"page_size must be one of {list(PAGE_SIZES)}")
    now = now_ist().replace(microsecond=0)
    lo, hi = _window_bounds(window, date_from, date_to, now)
    T = ProtocolDiagnosticLog
    conds = _window_conds(T, lo, hi)
    if protocol != ProtocolFilter.ALL:
        conds.append(T.Protocol == protocol.value)
    if status:
        conds.append(T.Status == status.value)
    if device_id and device_id.strip():
        conds.append(_contains(T.DeviceId, device_id) | _contains(T.DeviceName, device_id) | _contains(T.IMEI, device_id))
    if site_id and site_id.strip():
        conds.append(_contains(T.SiteId, site_id))
    if source_ip and source_ip.strip():
        conds.append(_contains(T.SourceIP, source_ip))
    if topic and topic.strip():
        conds.append(_contains(T.Topic, topic))
    total = db.scalar(select(func.count()).select_from(T).where(*conds)) or 0
    latest = db.scalar(select(func.max(T.ReceivedAt)))
    rows = db.scalars(select(T).where(*conds).order_by(T.ReceivedAt.desc(), T.Id.desc())
                      .offset((page - 1) * page_size).limit(page_size)).all()
    return PacketPage(
        page=page, page_size=page_size, total=total, total_pages=max(1, -(-total // page_size)), window=window,
        latest_received_at=latest, latest_received_at_display=format_ist(latest),
        server_time=now, server_time_display=format_ist(now),
        items=[_packet_item(r, _parsed_for(r)[0]) for r in rows],
    )


@router.get("/packets/{record_id}", response_model=PacketDetail, summary="One packet: parsed, raw, escaped, hex")
def testing_packet(record_id: int, db: Session = Depends(get_db)):
    from app.database.models import RawMessage, TCPMessage, Telemetry
    from app.protocol.tcp_parser import get_ack_strategy
    r = db.get(ProtocolDiagnosticLog, record_id)
    if r is None:
        raise HTTPException(status_code=404, detail="Diagnostic record not found")
    data = inspect.stored_bytes(r.Payload or "", r.PayloadEncoding)
    parsed = inspect.reparse(r.Protocol, r.Topic, r.SourceIP, data, r.PayloadEncoding, bool(r.PayloadTruncated))
    decoded, dups = inspect.decode_json(data) if parsed.format == "JSON" else (None, [])

    # The capture code writes the SAME server receipt timestamp to RawMessages and to this
    # table, so the archive row is found exactly (read-only).
    q = select(RawMessage).where(RawMessage.Protocol == r.Protocol, RawMessage.ReceivedAt == r.ReceivedAt)
    q = q.where(RawMessage.SourceIP == r.SourceIP) if r.Protocol == "TCP" else q.where(RawMessage.Topic == r.Topic)
    raw = db.scalars(q.order_by(RawMessage.Id).limit(1)).first()
    telemetry_id = ack = None
    if raw is not None:
        telemetry_id = db.scalar(select(Telemetry.Id).where(Telemetry.RawMessageId == raw.Id).limit(1))
        if r.Protocol == "TCP":
            ack = db.scalar(select(TCPMessage.Acknowledgement).where(TCPMessage.RawMessageId == raw.Id).limit(1))
    if r.Protocol == "TCP":
        acknowledgement = ack or f"none sent - {get_ack_strategy().describe()}"
        transport = "YES - received by the TCP listener"
    else:
        acknowledgement = f"MQTT QoS {r.QoS} - acknowledged by the broker" if r.QoS is not None else "MQTT - by the broker"
        transport = "YES - delivered by the MQTT broker"
    if r.Status == "INVALID":
        parse_status = "REJECTED"
    elif r.Outcome in ("STATUS", "NOT_HANDLED"):
        parse_status = "ACCEPTED (not telemetry)"
    else:
        parse_status = "ACCEPTED"
    now = now_ist().replace(microsecond=0)
    return _packet_item(
        r, parsed.fields, PacketDetail,
        server_time=now, server_time_display=format_ist(now), is_registered=bool(r.IsRegistered),
        transport_received=transport, parse_status=parse_status,
        database_status=inspect.database_status(r.Outcome, telemetry_id), acknowledgement=acknowledgement,
        raw_message_id=raw.Id if raw is not None else None, telemetry_id=telemetry_id,
        payload_format=parsed.format, payload_complete=not bool(r.PayloadTruncated),
        payload_text=(r.Payload or "") if r.PayloadEncoding == "TEXT" else None,
        payload_escaped=inspect.escaped_view(data), payload_hex=inspect.hex_view(data),
        telemetry=parsed.fields, decoded_json=decoded, field_check=inspect.field_check(decoded, dups),
        reparse_error=parsed.error,
    )


@router.get("/{protocol}", response_model=DiagnosticPage, summary="Protocol Test Log page (newest first)")
def list_diagnostics(
    protocol: Protocol,
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50),
    status: Optional[StatusFilter] = Query(None),
    device_id: Optional[str] = Query(None, max_length=50),
    imei: Optional[str] = Query(None, max_length=20),
    source_ip: Optional[str] = Query(None, max_length=45),
    topic: Optional[str] = Query(None, max_length=255),
    db: Session = Depends(get_db),
):
    if page_size not in PAGE_SIZES:
        raise HTTPException(status_code=422, detail=f"page_size must be one of {list(PAGE_SIZES)}")
    proto = protocol.value.upper()
    T = ProtocolDiagnosticLog
    conds = [T.Protocol == proto]
    if status:
        conds.append(T.Status == status.value)
    if device_id and device_id.strip():
        # "Device" filter matches the device ID or its registered name
        conds.append(_contains(T.DeviceId, device_id) | _contains(T.DeviceName, device_id))
    if imei and imei.strip():
        conds.append(_contains(T.IMEI, imei))
    if source_ip and source_ip.strip():
        conds.append(_contains(T.SourceIP, source_ip))
    if topic and topic.strip():
        conds.append(_contains(T.Topic, topic))

    total = db.scalar(select(func.count()).select_from(T).where(*conds)) or 0
    latest = db.scalar(select(func.max(T.ReceivedAt)).where(T.Protocol == proto))
    rows = db.scalars(
        select(T).where(*conds).order_by(T.ReceivedAt.desc(), T.Id.desc())
        .offset((page - 1) * page_size).limit(page_size)
    ).all()
    now = now_ist().replace(microsecond=0)
    return DiagnosticPage(
        protocol=proto, page=page, page_size=page_size, total=total,
        total_pages=max(1, -(-total // page_size)),
        latest_received_at=latest, latest_received_at_display=format_ist(latest),
        server_time=now, server_time_display=format_ist(now),
        retention_days=get_settings().DIAG_RETENTION_DAYS,
        items=[_item(r) for r in rows],
    )


@router.get("/{protocol}/{record_id}", response_model=DiagnosticDetail, summary="One record with full payload")
def get_diagnostic(protocol: Protocol, record_id: int, db: Session = Depends(get_db)):
    r = db.get(ProtocolDiagnosticLog, record_id)
    if r is None or r.Protocol != protocol.value.upper():
        raise HTTPException(status_code=404, detail="Diagnostic record not found")
    return _item(r, DiagnosticDetail, payload=r.Payload or "")
