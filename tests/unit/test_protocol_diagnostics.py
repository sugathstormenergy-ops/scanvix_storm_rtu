"""
Protocol Test Log (diagnostics) - classification, capture through the REAL TCP server and
MQTT consumer code, no auto-registration, payload safety, read-only paginated API,
server timestamps and 30-day retention. Uses an in-memory SQLite database built from the
ORM models; nothing touches SQL Server.
"""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

os.environ.setdefault("API_SECRET_KEY", "test-only")
os.environ.setdefault("SQL_SERVER", "127.0.0.1")

pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
from fastapi import FastAPI                                        # noqa: E402
from fastapi.testclient import TestClient                          # noqa: E402
from sqlalchemy import create_engine, func, select                 # noqa: E402
from sqlalchemy.dialects import mssql                              # noqa: E402
from sqlalchemy import BigInteger                                  # noqa: E402
from sqlalchemy.ext.compiler import compiles                       # noqa: E402
from sqlalchemy.orm import sessionmaker                            # noqa: E402
from sqlalchemy.pool import StaticPool                             # noqa: E402

from app.api import diagnostics as diag_api                        # noqa: E402
from app.database.database import Base, get_db                     # noqa: E402
from app.database.models import (                                  # noqa: E402
    Device, DeviceEvent, MQTTMessage, ProtocolDiagnosticLog, RawMessage, TCPMessage, Telemetry,
)
from app.diagnostics import recorder                               # noqa: E402
from app.diagnostics.payload import render_payload                 # noqa: E402
from app.diagnostics.recorder import DiagnosticEvent, build_row    # noqa: E402
from app.diagnostics.retention import purge_expired, purge_statement  # noqa: E402
from app.services.telemetry_service import TelemetryService        # noqa: E402
from app.timezone import now_ist                                   # noqa: E402

@compiles(BigInteger, "sqlite")
def _bigint_as_sqlite_rowid(type_, compiler, **kw):
    # SQLite only auto-increments "INTEGER PRIMARY KEY"; the SQL Server DDL is unaffected.
    return "INTEGER"


TABLES = [Device.__table__, Telemetry.__table__, RawMessage.__table__, TCPMessage.__table__,
          MQTTMessage.__table__, DeviceEvent.__table__, ProtocolDiagnosticLog.__table__]


@pytest.fixture()
def db_env(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=TABLES)
    Session = sessionmaker(bind=engine)

    @contextmanager
    def test_db_session():
        s = Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    import app.mqtt.consumer as consumer_mod
    import app.tcp.server as tcp_mod
    monkeypatch.setattr(tcp_mod, "db_session", test_db_session)
    monkeypatch.setattr(consumer_mod, "db_session", test_db_session)
    monkeypatch.setattr(recorder, "_session_factory", Session)
    monkeypatch.setattr(recorder, "_limiter", recorder._MinuteLimiter(10_000))
    return Session


def _register(Session, device_id="RTU-1", imei="860000000000001", site="SITE-A", name="Pump 1"):
    with Session() as s:
        s.add(Device(DeviceId=device_id, IMEI=imei, SiteId=site, CommunicationMode="BOTH", IsActive=True,
                     CreatedAt=now_ist(), UpdatedAt=now_ist(), Name=name))
        s.commit()


def _count(Session, model):
    with Session() as s:
        return s.scalar(select(func.count()).select_from(model))


def _diag_rows(Session, protocol):
    with Session() as s:
        return list(s.scalars(select(ProtocolDiagnosticLog).where(ProtocolDiagnosticLog.Protocol == protocol)
                              .order_by(ProtocolDiagnosticLog.Id)))


def _json_packet(device_id, **extra):
    body = {"deviceId": device_id, "siteid": "SITE-X", "ts": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
            "flow": 12.5, "flowUnit": "m3/h", "totalToday": 10.0}
    body.update(extra)
    return json.dumps(body).encode()


# ─── payload rendering ────────────────────────────────────────────────────────

class TestPayload:
    def test_text_kept_verbatim_including_markup(self):
        r = render_payload(b'<script>alert(1)</script>|x')
        assert (r.encoding, r.text, r.size, r.truncated) == ("TEXT", "<script>alert(1)</script>|x", 27, False)

    def test_crlf_tab_allowed_as_text(self):
        assert render_payload(b"a|b\r\n\t").encoding == "TEXT"

    def test_binary_and_control_chars_become_hex(self):
        r = render_payload(b"\x00\x01\xffAB")
        assert r.encoding == "HEX" and r.text == "00 01 FF 41 42" and r.size == 5
        assert render_payload(b"ok\x1b[31m").encoding == "HEX"          # ANSI escape is not shown raw

    def test_truncation_is_bounded(self):
        t = render_payload(b"A" * 10_000, 4000)
        assert len(t.text) == 4000 and t.truncated and t.size == 10_000
        h = render_payload(bytes(range(256)) * 40, 4000)
        assert len(h.text) <= 4000 and h.truncated and h.encoding == "HEX"


# ─── classification ───────────────────────────────────────────────────────────

class TestClassification:
    def _ev(self, **kw):
        base = dict(protocol="TCP", received_at=datetime(2026, 9, 25, 17, 35, 37), raw=b"x", parsed_ok=True,
                    device_id="RTU-1", site_id="PARSED-SITE", source_ip="10.0.0.9")
        base.update(kw)
        return DiagnosticEvent(**base)

    def test_invalid_hides_identity(self):
        row = build_row(self._ev(parsed_ok=False, device_id="RTU-1"), None, 4000)
        assert (row.Status, row.DeviceId, row.IMEI, row.SiteId, row.IsRegistered) == ("INVALID", None, None, None, False)

    def test_unknown_device(self):
        row = build_row(self._ev(), None, 4000)
        assert (row.Status, row.DeviceId, row.IMEI, row.SiteId, row.IsRegistered) == \
            ("UNKNOWN_DEVICE", "RTU-1", None, "PARSED-SITE", False)

    def test_valid_uses_registry_identity(self):
        dev = SimpleNamespace(IMEI="860000000000001", SiteId="REG-SITE", Name="Pump 1")
        row = build_row(self._ev(), dev, 4000)
        assert (row.Status, row.IMEI, row.SiteId, row.DeviceName, row.IsRegistered) == \
            ("VALID", "860000000000001", "REG-SITE", "Pump 1", True)

    def test_timestamp_is_the_server_receipt_time(self):
        ts = datetime(2026, 9, 25, 17, 35, 37)
        row = build_row(self._ev(received_at=ts), None, 4000)
        assert row.ReceivedAt == ts and row.CreatedAt == ts

    def test_record_never_raises(self, monkeypatch):
        def broken():
            raise RuntimeError("db down")
        monkeypatch.setattr(recorder, "_session_factory", broken)
        monkeypatch.setattr(recorder, "_limiter", recorder._MinuteLimiter(10))
        assert recorder.record(self._ev()) is False

    def test_rate_limit(self):
        lim = recorder._MinuteLimiter(3)
        assert [lim.allow() for _ in range(5)] == [True, True, True, False, False]


# ─── no auto-registration ─────────────────────────────────────────────────────

class TestNoAutoRegistration:
    def test_unknown_device_creates_nothing(self, db_env):
        Session = db_env
        from app.protocol.mqtt_parser import parse_mqtt_payload
        tel = parse_mqtt_payload("storm/meters/NEW-1/telemetry", _json_packet("NEW-1"))
        with Session() as s:
            result = TelemetryService().ingest(s, tel)
            s.commit()
        assert result["status"] == "unknown_device"
        assert _count(Session, Device) == 0
        assert _count(Session, Telemetry) == 0
        assert _count(Session, DeviceEvent) == 0

    def test_registered_device_still_stored(self, db_env):
        Session = db_env
        _register(Session)
        from app.protocol.mqtt_parser import parse_mqtt_payload
        tel = parse_mqtt_payload("storm/meters/RTU-1/telemetry", _json_packet("RTU-1"))
        with Session() as s:
            result = TelemetryService().ingest(s, tel)
            s.commit()
        assert result["status"] == "stored"
        assert _count(Session, Telemetry) == 1 and _count(Session, Device) == 1


# ─── capture through the real TCP server ──────────────────────────────────────

def _run_tcp(packets):
    from app.tcp import server as tcp_mod

    async def main():
        srv = await asyncio.start_server(tcp_mod.handle_client, "127.0.0.1", 0)
        port = srv.sockets[0].getsockname()[1]
        for p in packets:
            r, w = await asyncio.open_connection("127.0.0.1", port)
            w.write(p)
            await w.drain()
            await asyncio.sleep(0.15)
            w.close()
            await w.wait_closed()
            await asyncio.sleep(0.1)
        srv.close()
        await srv.wait_closed()

    asyncio.run(main())


class TestTcpCapture:
    def test_valid_unknown_invalid_binary(self, db_env):
        Session = db_env
        _register(Session)
        _run_tcp([
            _json_packet("RTU-1"),                          # registered -> VALID, stored
            _json_packet("STRANGER-9"),                     # well-formed, unregistered -> UNKNOWN_DEVICE
            b"GET / HTTP/1.1\r\nHost: x\r\n\r\n",           # probe -> INVALID
            b"\x16\x03\x01\x00\xa5\x01\x00",                # TLS hello bytes -> INVALID, HEX
        ])
        rows = _diag_rows(Session, "TCP")
        assert [r.Status for r in rows] == ["VALID", "UNKNOWN_DEVICE", "INVALID", "INVALID"]
        assert rows[0].IMEI == "860000000000001" and rows[0].Outcome == "PROCESSED" and rows[0].SourceIP == "127.0.0.1"
        assert rows[1].DeviceId == "STRANGER-9" and rows[1].Outcome == "UNKNOWN_DEVICE" and rows[1].IMEI is None
        assert rows[2].DeviceId is None and rows[2].Outcome == "PARSE_ERROR" and "MALFORMED_PACKET" in rows[2].ErrorReason
        assert rows[3].PayloadEncoding == "HEX"
        # the existing archive still records every packet, business tables only the registered one
        assert _count(Session, TCPMessage) == 4 and _count(Session, RawMessage) == 4
        assert _count(Session, Device) == 1 and _count(Session, Telemetry) == 1
        with Session() as s:
            assert s.scalar(select(TCPMessage.Status).where(TCPMessage.DeviceId == "STRANGER-9")) == "UNKNOWN_DEVICE"

    def test_server_receipt_time_used(self, db_env):
        Session = db_env
        before = now_ist().replace(microsecond=0)
        _run_tcp([b"garbage"])
        after = now_ist()
        row = _diag_rows(Session, "TCP")[0]
        assert before <= row.ReceivedAt <= after


# ─── capture through the real MQTT consumer ───────────────────────────────────

class TestMqttCapture:
    def _deliver(self, topic, payload, qos=1):
        from app.mqtt.consumer import MQTTConsumer
        c = MQTTConsumer()
        c._handle_message(None, None, SimpleNamespace(topic=topic, payload=payload, qos=qos))

    def test_valid_unknown_invalid(self, db_env):
        Session = db_env
        _register(Session)
        self._deliver("storm/meters/RTU-1/telemetry", _json_packet("RTU-1"))
        self._deliver("storm/meters/NEW-7/telemetry", _json_packet("NEW-7"))
        self._deliver("storm/meters/RTU-1/telemetry", b"{not json")
        self._deliver("storm/meters/RTU-1/status", b'{"online": true}')
        rows = _diag_rows(Session, "MQTT")
        assert [(r.Status, r.Outcome) for r in rows] == [
            ("VALID", "PROCESSED"), ("UNKNOWN_DEVICE", "UNKNOWN_DEVICE"), ("INVALID", "PARSE_ERROR"), ("VALID", "STATUS")]
        assert rows[0].Topic == "storm/meters/RTU-1/telemetry" and rows[0].QoS == 1 and rows[0].SourceIP is None
        assert "INVALID_JSON" in rows[2].ErrorReason
        assert _count(Session, Device) == 1 and _count(Session, Telemetry) == 1

    def test_unexpected_topic_logged_invalid(self, db_env):
        Session = db_env
        self._deliver("some/other/topic", b"hello")
        row = _diag_rows(Session, "MQTT")[0]
        assert (row.Status, row.Outcome, row.Topic) == ("INVALID", "UNEXPECTED_TOPIC", "some/other/topic")


# ─── read-only API ────────────────────────────────────────────────────────────

@pytest.fixture()
def api(db_env):
    Session = db_env
    app = FastAPI()
    app.include_router(diag_api.router)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return Session, TestClient(app)


def _seed(Session, n, protocol="TCP", start=datetime(2026, 9, 25, 10, 0, 0), **kw):
    with Session() as s:
        for i in range(n):
            ts = start + timedelta(seconds=i)
            s.add(ProtocolDiagnosticLog(
                ReceivedAt=ts, CreatedAt=ts, Protocol=protocol, Status=kw.get("status", "INVALID"),
                SourceIP=kw.get("ip", f"10.0.0.{i % 5}"), IngressPort=kw.get("port"), Outcome=kw.get("outcome"),
                DeviceId=kw.get("device_id"), Topic=kw.get("topic"),
                Payload=kw.get("payload", f"pkt-{i}"), PayloadEncoding="TEXT", PayloadBytes=5,
                PayloadTruncated=False, IsRegistered=False))
        s.commit()


class TestApi:
    def test_pagination_newest_first(self, api):
        Session, c = api
        _seed(Session, 120)
        p1 = c.get("/api/diagnostics/tcp").json()
        assert (p1["page"], p1["page_size"], p1["total"], p1["total_pages"], len(p1["items"])) == (1, 50, 120, 3, 50)
        assert p1["items"][0]["payload_preview"] == "pkt-119"
        assert p1["latest_received_at_display"] == "25-Sep-2026 10:01:59 IST"
        p3 = c.get("/api/diagnostics/tcp?page=3").json()
        assert len(p3["items"]) == 20 and p3["items"][-1]["payload_preview"] == "pkt-0"
        assert len(c.get("/api/diagnostics/tcp?page_size=100").json()["items"]) == 100

    def test_page_size_limited(self, api):
        _, c = api
        assert c.get("/api/diagnostics/tcp?page_size=5000").status_code == 422
        assert c.get("/api/diagnostics/tcp?page_size=250").status_code == 200
        assert c.get("/api/diagnostics/udp").status_code == 422

    def test_protocols_are_separate_and_filters(self, api):
        Session, c = api
        _seed(Session, 3, "TCP", status="VALID", device_id="RTU-1", ip="192.168.0.77")
        _seed(Session, 2, "MQTT", status="INVALID", topic="storm/meters/X/telemetry")
        assert c.get("/api/diagnostics/mqtt").json()["total"] == 2
        assert c.get("/api/diagnostics/tcp?status=VALID").json()["total"] == 3
        assert c.get("/api/diagnostics/tcp?status=INVALID").json()["total"] == 0
        assert c.get("/api/diagnostics/tcp?source_ip=0.77").json()["total"] == 3
        assert c.get("/api/diagnostics/tcp?device_id=rtu").json()["total"] == 3
        assert c.get("/api/diagnostics/mqtt?topic=meters/X").json()["total"] == 2
        assert c.get("/api/diagnostics/tcp?device_id=%25").json()["total"] == 0     # '%' is literal, not a wildcard
        assert c.get("/api/diagnostics/tcp?status=BOGUS").status_code == 422

    def test_detail_returns_full_payload_as_data(self, api):
        Session, c = api
        _seed(Session, 1, payload="<img src=x onerror=alert(1)>" + "A" * 300)
        item = c.get("/api/diagnostics/tcp").json()["items"][0]
        assert len(item["payload_preview"]) <= 160
        d = c.get(f"/api/diagnostics/tcp/{item['id']}").json()
        assert d["payload"].startswith("<img src=x onerror=alert(1)>")           # JSON string, rendered as text by the UI
        assert c.get(f"/api/diagnostics/mqtt/{item['id']}").status_code == 404    # protocol must match

    def test_server_time(self, api):
        _, c = api
        j = c.get("/api/diagnostics/server-time").json()
        assert j["retention_days"] == 30 and j["server_time_display"].endswith(" IST")
        srv = datetime.fromisoformat(j["server_time"])
        assert abs((srv - now_ist()).total_seconds()) < 5
        assert diag_api.format_ist(datetime(2026, 9, 5, 7, 3, 9)) == "05-Sep-2026 07:03:09 IST"

    def test_read_only(self, api):
        Session, c = api
        _seed(Session, 1)
        for method in ("post", "put", "patch", "delete"):
            assert getattr(c, method)("/api/diagnostics/tcp").status_code == 405
            assert getattr(c, method)("/api/diagnostics/tcp/1").status_code == 405
        assert _count(Session, ProtocolDiagnosticLog) == 1


# ─── retention ────────────────────────────────────────────────────────────────

class TestRetention:
    def test_purges_only_older_than_30_days_and_is_idempotent(self, db_env):
        Session = db_env
        _register(Session)
        now = datetime(2026, 10, 30, 12, 0, 0)
        _seed(Session, 7, start=now - timedelta(days=31))                 # expired
        _seed(Session, 5, start=now - timedelta(days=29))                 # kept
        _seed(Session, 1, start=now - timedelta(days=30, seconds=-60))   # just inside -> kept
        with Session() as s:
            s.add(Telemetry(DeviceId="RTU-1", Timestamp=now - timedelta(days=90), ReceivedAt=now - timedelta(days=90),
                            Protocol="MQTT", IsHistorical=False))
            s.add(RawMessage(Protocol="TCP", ReceivedAt=now - timedelta(days=90), Payload="old", IsValid=True))
            s.commit()
        with Session() as s:
            assert purge_expired(s, retention_days=30, batch_size=3, now=now) == 7   # several batches
        with Session() as s:
            assert purge_expired(s, retention_days=30, batch_size=3, now=now) == 0   # idempotent
        assert _count(Session, ProtocolDiagnosticLog) == 6
        assert _count(Session, Telemetry) == 1 and _count(Session, RawMessage) == 1 and _count(Session, Device) == 1

    def test_statement_targets_only_the_diagnostics_table(self):
        stmt = purge_statement(datetime(2026, 9, 1), 5000)
        sql = str(stmt.compile(dialect=mssql.dialect(), compile_kwargs={"literal_binds": True}))
        assert sql.startswith('DELETE FROM [ProtocolDiagnosticLogs] WHERE [ProtocolDiagnosticLogs].[Id] IN (SELECT TOP 5000')
        for other in ("Telemetry", "Devices", "RawMessages", "TCPMessages", "MQTTMessages"):
            assert f"[{other}]" not in sql


# ─── MQTT security unchanged ──────────────────────────────────────────────────

def test_mqtt_broker_still_requires_authentication():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    conf = [l.split("#", 1)[0].strip() for l in (root / "docker/mosquitto/mosquitto.conf").read_text().splitlines()]
    conf = [l for l in conf if l]
    assert "allow_anonymous false" in conf and "allow_anonymous true" not in conf
    assert any(l.startswith("password_file") for l in conf)


def test_diagnostics_api_exposes_no_secret_fields():
    fields = set(diag_api.DiagnosticDetail.model_fields) | set(diag_api.DiagnosticPage.model_fields) \
        | set(diag_api.ServerTimeOut.model_fields)
    assert not {f for f in fields if any(w in f for w in ("password", "secret", "token", "credential", "key"))}


# ═════════════════════════════════════════════════════════════════════════════
# Testing / Protocol Monitor API (combined stream, detail, sources, summary)
# Records are produced by the REAL TCP server / MQTT consumer code paths.
# ═════════════════════════════════════════════════════════════════════════════

SCANNER_58 = bytes.fromhex("1603010035010000310303") + bytes(range(1, 48))   # 58-byte binary probe (TLS-like)


def _mqtt(topic, payload, qos=1):
    from app.mqtt.consumer import MQTTConsumer
    MQTTConsumer()._handle_message(None, None, SimpleNamespace(topic=topic, payload=payload, qos=qos))


@pytest.fixture()
def live(db_env, monkeypatch):
    """Registered RTU-1 plus real traffic of every kind through the real ingestion code."""
    Session = db_env
    _register(Session)
    monkeypatch.setattr(diag_api, "_tcp_listener_state",
                        lambda: diag_api.ServiceState(status="ok", details="test"))
    import app.api.health as health_mod
    monkeypatch.setattr(health_mod, "check_database_connection", lambda: True)
    assert len(SCANNER_58) == 58
    _run_tcp([
        _json_packet("RTU-1"),                                 # VALID
        SCANNER_58,                                            # INVALID binary scanner probe
        b"HELLO\x00\x01\x13 world\r\n",                         # INVALID with control bytes
        _json_packet("STRANGER-9"),                            # UNKNOWN_DEVICE
    ])
    body = {"deviceId": "RTU-1", "siteid": "BENCH", "ts": now_ist().strftime("%Y-%m-%d %H:%M:%S"),
            "flow": 18.42, "flowUnit": "m3/h", "totalToday": 324.81, "totalYesterday": None,
            "battery": None, "READ01": "000000", "testRun": "x"}
    _mqtt("storm/meters/RTU-1/telemetry",
          json.dumps(body)[:-1].encode() + b', "PRESSURE": null, "PRESSURE": 1.5}')   # duplicate key
    _mqtt("storm/meters/RTU-1/telemetry", b"{broken")
    app = FastAPI()
    app.include_router(diag_api.router)

    def _db():
        s = Session()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _db
    return Session, TestClient(app)


def _by(items, **match):
    return [i for i in items if all(i.get(k) == v for k, v in match.items())]


class TestTestingApi:
    def test_combined_stream_newest_first_with_labels(self, live):
        _, c = live
        j = c.get("/api/diagnostics/packets?window=today").json()
        assert j["total"] == 6 and j["page_size"] == 50
        times = [i["received_at"] for i in j["items"]]
        assert times == sorted(times, reverse=True)
        assert {i["protocol_label"] for i in j["items"]} == {"TCP / ASCII", "MQTT / JSON"}
        assert [i["status"] for i in _by(j["items"], protocol="TCP")].count("INVALID") == 2

    def test_stream_shows_parsed_flow_for_valid_and_unknown_not_invalid(self, live):
        _, c = live
        items = c.get("/api/diagnostics/packets?window=today").json()["items"]
        mq = _by(items, protocol="MQTT", status="VALID")[0]
        assert (mq["flow"], mq["total_today"], mq["device_id"]) == (18.42, 324.81, "RTU-1")
        assert mq["site_id"] == "SITE-A"                 # registered device: the registry site wins
        unk = _by(items, status="UNKNOWN_DEVICE")[0]
        assert unk["flow"] == 12.5 and unk["device_id"] == "STRANGER-9"
        for inv in _by(items, status="INVALID"):
            assert inv["flow"] is None and inv["total_today"] is None and inv["device_id"] is None

    def test_filters(self, live):
        _, c = live
        g = lambda q: c.get(f"/api/diagnostics/packets?window=today&{q}").json()["total"]
        assert g("protocol=TCP") == 4 and g("protocol=MQTT") == 2
        assert g("status=INVALID") == 3 and g("status=UNKNOWN_DEVICE") == 1 and g("status=VALID") == 2
        assert g("device_id=860000000000001") == 2          # matches the registered IMEI
        assert g("site_id=SITE-A") == 2 and g("site_id=BENCH") == 0
        assert g("source_ip=127.0.0") == 4 and g("topic=RTU-1/telemetry") == 2
        assert c.get("/api/diagnostics/packets?protocol=UDP").status_code == 422
        assert c.get("/api/diagnostics/packets?window=bogus").status_code == 422
        assert c.get("/api/diagnostics/packets?window=custom&from=2026-09-29T10:00:00&to=2026-09-28T10:00:00").status_code == 422
        future = (now_ist() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")
        assert c.get(f"/api/diagnostics/packets?window=custom&from={future}").json()["total"] == 0

    def test_binary_scanner_packet_fully_visible(self, live):
        _, c = live
        items = c.get("/api/diagnostics/packets?window=today&protocol=TCP&status=INVALID").json()["items"]
        row = [i for i in items if i["size"] == 58][0]
        d = c.get(f"/api/diagnostics/packets/{row['id']}").json()
        assert d["payload_format"] == "BINARY" and d["payload_text"] is None and d["payload_complete"] is True
        assert d["payload_hex"] == SCANNER_58.hex(" ").upper()
        assert d["payload_escaped"].startswith("\\x16\\x03\\x01\\x005")
        assert d["error_reason"] == "MALFORMED_PACKET: No TCP parser could handle packet from 127.0.0.1 (58 bytes)"
        assert d["parse_status"] == "REJECTED" and d["telemetry"] is None
        assert d["database_status"] == "NOT STORED - parse error"
        assert d["acknowledgement"].startswith("none sent - NullAck")
        assert d["transport_received"].startswith("YES") and d["raw_message_id"] is not None

    def test_control_bytes_escaped_and_raw_text_exact(self, live):
        _, c = live
        items = c.get("/api/diagnostics/packets?window=today&protocol=TCP&status=INVALID").json()["items"]
        row = [i for i in items if i["size"] != 58][0]
        d = c.get(f"/api/diagnostics/packets/{row['id']}").json()
        assert d["payload_format"] == "BINARY"                      # control bytes -> stored as hex
        assert d["payload_escaped"] == "HELLO\\x00\\x01\\x13 world\\r\\n"
        assert d["payload_hex"].startswith("48 45 4C 4C 4F 00 01 13")

    def test_valid_mqtt_detail_parsed_nulls_and_protocol_check(self, live):
        Session, c = live
        items = c.get("/api/diagnostics/packets?window=today&protocol=MQTT&status=VALID").json()["items"]
        d = c.get(f"/api/diagnostics/packets/{items[0]['id']}").json()
        t = d["telemetry"]
        assert t["flow"] == 18.42 and t["total_today"] == 324.81 and t["read01"] == "000000"
        assert t["battery"] is None and t["total_yesterday"] is None      # NULL stays NULL, never 0
        assert t["pressure"] == 1.5                                        # ONE canonical pressure
        fc = d["field_check"]
        assert fc["duplicate_keys"] == ["PRESSURE"] and fc["undocumented_keys"] == ["testRun"]
        assert fc["missing_required"] == []
        assert [r["field"] for r in fc["fields"]][:3] == ["deviceId", "siteid", "ts"]
        assert d["payload_text"].endswith('"PRESSURE": null, "PRESSURE": 1.5}')   # raw kept verbatim
        assert d["parse_status"] == "ACCEPTED" and d["telemetry_id"] is not None
        assert d["database_status"] == f"STORED - telemetry row {d['telemetry_id']}"
        assert d["acknowledgement"].startswith("MQTT QoS 1")

    def test_unknown_device_parsed_but_not_stored(self, live):
        Session, c = live
        items = c.get("/api/diagnostics/packets?window=today&status=UNKNOWN_DEVICE").json()["items"]
        d = c.get(f"/api/diagnostics/packets/{items[0]['id']}").json()
        assert d["telemetry"]["device_id"] == "STRANGER-9" and d["telemetry_id"] is None
        assert d["database_status"] == "NOT STORED - device not registered (no auto-registration)"
        with Session() as s:
            assert s.scalar(select(func.count()).select_from(Device).where(Device.DeviceId == "STRANGER-9")) == 0

    def test_sources_include_unknown_and_invalid(self, live):
        _, c = live
        j = c.get("/api/diagnostics/sources?window=today").json()
        keys = {i["key"]: i for i in j["items"]}
        rtu_tcp, rtu_mqtt = keys["TCP:RTU-1@8100"], keys["MQTT:RTU-1"]
        assert rtu_tcp["is_registered"] and rtu_tcp["packet_count"] == 1 and rtu_tcp["imei"] == "860000000000001"
        assert rtu_mqtt["packet_count"] == 1 and rtu_mqtt["last_status"] == "VALID"
        # an INVALID message is never attributed to a device: it is grouped by its topic
        broken = keys["MQTT:storm/meters/RTU-1/telemetry"]
        assert broken["device_id"] is None and broken["last_status"] == "INVALID" and broken["packet_count"] == 1
        assert keys["TCP:STRANGER-9@8100"]["is_registered"] is False and keys["TCP:STRANGER-9@8100"]["last_flow"] == 12.5
        assert keys["TCP:127.0.0.1@8100"]["packet_count"] == 2 and keys["TCP:127.0.0.1@8100"]["device_id"] is None

    def test_summary_counts_and_services(self, live):
        _, c = live
        s = c.get("/api/diagnostics/summary").json()
        assert (s["total"], s["valid"], s["unknown_device"], s["invalid"]) == (6, 2, 1, 3)
        assert s["by_protocol"]["TCP"]["INVALID"] == 2 and s["by_protocol"]["MQTT"]["VALID"] == 1
        assert s["last_packet_protocol"] == "MQTT" and s["server_time_display"].endswith(" IST")
        assert set(s["services"]) == {"api", "database", "mqtt_broker", "tcp_listener"}
        assert s["services"]["database"]["status"] == "ok"

    def test_new_endpoints_are_read_only(self, live):
        _, c = live
        for path in ("/api/diagnostics/packets", "/api/diagnostics/packets/1", "/api/diagnostics/sources",
                     "/api/diagnostics/summary"):
            for method in ("post", "put", "patch", "delete"):
                assert getattr(c, method)(path).status_code == 405, (method, path)

    def test_existing_protocol_endpoints_unchanged(self, live):
        _, c = live
        assert c.get("/api/diagnostics/tcp").json()["total"] == 4
        assert c.get("/api/diagnostics/mqtt").json()["total"] == 2


def test_tcp_probe_reports_listening_and_down(monkeypatch):
    import socket as _s
    srv = _s.socket()
    srv.bind(("127.0.0.1", 0)); srv.listen(1)
    port = srv.getsockname()[1]
    from app.config import get_settings
    s = get_settings()
    monkeypatch.setattr(s, "DIAG_TCP_PROBE_HOST", "127.0.0.1")
    monkeypatch.setattr(s, "TCP_PORT", port)
    diag_api._tcp_probe_cache.update(at=0.0, value=None)
    assert diag_api._tcp_listener_state().status == "ok"
    srv.close()
    diag_api._tcp_probe_cache.update(at=0.0, value=None)
    assert diag_api._tcp_listener_state().status == "down"
    monkeypatch.setattr(s, "DIAG_TCP_PROBE_HOST", "")
    assert diag_api._tcp_listener_state().status == "unknown"
    diag_api._tcp_probe_cache.update(at=0.0, value=None)


class TestDeploymentHealthCheckUrls:
    """Every /api/diagnostics/... URL that the deploy health check calls must be served by the route it
    means, return 200, and must not be swallowed by the '/{protocol}' path route (which answers 422 for
    anything but tcp|mqtt - the production symptom when an older API image lacked /packets)."""

    def _urls(self):
        import re
        from pathlib import Path
        src = (Path(__file__).resolve().parents[2] / "scripts" / "deploy" / "StormRtu.psm1").read_text()
        return sorted(set(re.findall(r"\$httpsPort(/api/diagnostics/[A-Za-z0-9_/]+)", src)))

    def test_health_check_covers_tcp_mqtt_and_packets(self):
        urls = self._urls()
        for needed in ("/api/diagnostics/tcp", "/api/diagnostics/mqtt", "/api/diagnostics/packets"):
            assert needed in urls, urls

    def test_each_url_is_routed_to_its_own_handler_and_returns_200(self, live):
        _, c = live
        names = {"tcp": "list_diagnostics", "mqtt": "list_diagnostics", "packets": "testing_packets"}
        for url in self._urls():
            tail = url.rsplit("/", 1)[1]
            scope = {"type": "http", "method": "GET", "path": url}
            from starlette.routing import Match
            first = next(r for r in diag_api.router.routes if r.matches(scope)[0] == Match.FULL)
            assert first.endpoint.__name__ == names[tail], (url, first.endpoint.__name__)
            assert c.get(url + "?page=1&page_size=50").status_code == 200, url

    def test_unknown_protocol_segment_is_still_rejected(self, live):
        _, c = live
        assert c.get("/api/diagnostics/bogus").status_code == 422


# ─── ingress port: 444 (Scanvix test listener) vs 8100 (existing listener) ───

SCANVIX_SP = (b"#SP,STORM-ENER,866224083271188,12:12:25,30/09/2026,,28,V001,,,,,,,,,"
              b"00000,00000,00000,00000,00000,00000,00000,.")


def _free_port():
    import socket
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_dual(monkeypatch, sends):
    """Start the REAL TCPServer with both listeners; sends = [("main"|"test", bytes)]."""
    from app.tcp import server as tcp_mod
    main_p, test_p = _free_port(), _free_port()
    st = tcp_mod.get_settings().model_copy(update=dict(
        TCP_HOST="127.0.0.1", TCP_PORT=main_p, TCP_PUBLIC_PORT=8100, TCP_TEST_PORT=test_p, TCP_TEST_PUBLIC_PORT=444))
    monkeypatch.setattr(tcp_mod, "get_settings", lambda: st)

    async def main():
        srv = tcp_mod.TCPServer()
        await srv.start()
        for which, data in sends:
            r, w = await asyncio.open_connection("127.0.0.1", test_p if which == "test" else main_p)
            w.write(data)
            await w.drain()
            await asyncio.sleep(0.15)
            w.close()
            await w.wait_closed()
            await asyncio.sleep(0.1)
        await srv.stop()

    asyncio.run(main())


class TestIngressPort:
    def test_each_listener_records_its_own_public_port(self, db_env, monkeypatch):
        Session = db_env
        _register(Session)
        _run_dual(monkeypatch, [("test", SCANVIX_SP), ("main", _json_packet("RTU-1")),
                                ("main", SCANVIX_SP), ("test", b"GET / HTTP/1.1\r\n\r\n")])
        rows = _diag_rows(Session, "TCP")
        assert [r.IngressPort for r in rows] == [444, 8100, 8100, 444]
        # the #SP packet is NOT valid for the current parser: still recorded, as PARSE_ERROR, on either port
        assert [r.Status for r in rows] == ["INVALID", "VALID", "INVALID", "INVALID"]
        assert rows[0].Outcome == "PARSE_ERROR" and rows[0].Payload.startswith("#SP,STORM-ENER,")
        assert rows[0].PayloadBytes == len(SCANVIX_SP) and rows[0].DeviceId is None
        assert rows[0].SourceIP == "127.0.0.1"          # the real peer; never derived from the payload

    def test_default_listener_keeps_working_without_a_test_port(self, db_env):
        Session = db_env
        _run_tcp([b"garbage"])                          # plain handle_client, no ingress given
        assert _diag_rows(Session, "TCP")[0].IngressPort == 8100

    def test_test_port_must_differ_from_main_port(self, monkeypatch):
        from app.tcp import server as tcp_mod
        st = tcp_mod.get_settings().model_copy(update=dict(TCP_HOST="127.0.0.1", TCP_PORT=_free_port(), TCP_TEST_PORT=0))
        st2 = st.model_copy(update=dict(TCP_TEST_PORT=st.TCP_PORT))
        monkeypatch.setattr(tcp_mod, "get_settings", lambda: st2)
        with pytest.raises(RuntimeError):
            asyncio.run(tcp_mod.TCPServer().start())

    def test_mqtt_rows_have_no_ingress_port(self, db_env):
        Session = db_env
        _register(Session)
        TestMqttCapture()._deliver("storm/meters/RTU-1/telemetry", _json_packet("RTU-1"))
        assert _diag_rows(Session, "MQTT")[0].IngressPort is None


class TestIngressPortApi:
    def _seed_ports(self, Session):
        now = now_ist().replace(microsecond=0) - timedelta(minutes=5)
        _seed(Session, 2, start=now, ip="172.18.0.1", port=444, payload=SCANVIX_SP.decode(), outcome="PARSE_ERROR")
        _seed(Session, 3, start=now + timedelta(seconds=10), ip="172.18.0.1", port=8100, outcome="PARSE_ERROR")
        _seed(Session, 1, start=now + timedelta(seconds=20), ip="172.18.0.1", port=None, outcome="PARSE_ERROR")  # pre-007 row

    def test_port_filter_444_and_8100(self, api):
        Session, c = api
        self._seed_ports(Session)
        g = lambda q: c.get(f"/api/diagnostics/packets?window=today&{q}").json()
        assert g("")["total"] == 6
        j444, j8100 = g("port=444"), g("port=8100")
        assert j444["total"] == 2 and {i["ingress_port"] for i in j444["items"]} == {444}
        assert {i["listener"] for i in j444["items"]} == {"scanvix-test"}
        assert {i["listener_label"] for i in j444["items"]} == {"SCANVIX TEST"}
        assert j8100["total"] == 3 and {i["listener"] for i in j8100["items"]} == {"existing-tcp"}
        assert g("port=444&protocol=TCP")["total"] == 2 and g("port=9999")["total"] == 0
        assert c.get("/api/diagnostics/packets?port=0").status_code == 422
        assert c.get("/api/diagnostics/packets?port=abc").status_code == 422
        old = [i for i in g("")["items"] if i["ingress_port"] is None]
        assert len(old) == 1 and old[0]["listener"] is None          # unknown stays unknown, never guessed

    def test_filtering_is_server_side(self, api):
        Session, c = api
        self._seed_ports(Session)
        j = c.get("/api/diagnostics/packets?window=today&port=444&page_size=50").json()
        assert j["total"] == 2 and len(j["items"]) == 2

    def test_docker_gateway_source_is_just_the_peer_address(self, api):
        Session, c = api
        self._seed_ports(Session)
        items = c.get("/api/diagnostics/packets?window=today&port=444").json()["items"]
        assert {i["source_ip"] for i in items} == {"172.18.0.1"}
        assert not any("external" in k or "public" in k for k in items[0])      # no invented client IP field
        d = c.get(f"/api/diagnostics/packets/{items[0]['id']}").json()
        assert d["ingress_port"] == 444 and d["listener"] == "scanvix-test" and d["status"] == "INVALID"
        assert d["payload_text"].startswith("#SP,STORM-ENER,")

    def test_sources_are_split_per_port(self, api):
        Session, c = api
        self._seed_ports(Session)
        j = c.get("/api/diagnostics/sources?window=today").json()
        by = {(s["ingress_port"], s["key"]): s for s in j["items"]}
        assert (444, "TCP:172.18.0.1@444") in by and (8100, "TCP:172.18.0.1@8100") in by
        assert by[(444, "TCP:172.18.0.1@444")]["packet_count"] == 2 and by[(8100, "TCP:172.18.0.1@8100")]["packet_count"] == 3
        assert by[(444, "TCP:172.18.0.1@444")]["listener_label"] == "SCANVIX TEST"


# ─── Scanvix #SP frame through the real TCP server ───────────────────────────

SP_146 = (b"#SP,STORM-ENER,\x00866224083271188,12:52:33,05/10/2026,\x01,28,V001\x00,"
          + b",".join([b"\x00\x00\x00\x00"] * 8) + b",00000,00000,00000,00000,00000,00000,00000,.")


class TestScanvixSpThroughServer:
    def test_registered_imei_is_stored_and_diagnosed_valid_with_raw_bytes_kept(self, db_env):
        Session = db_env
        _register(Session, device_id="866224083271188", imei="866224083271188", site="SITE-S", name="Scanvix 1")
        _run_tcp([SP_146])
        row = _diag_rows(Session, "TCP")[0]
        assert (row.Status, row.Outcome, row.IsRegistered, row.DeviceId, row.IMEI) == ("VALID", "PROCESSED", True, "866224083271188", "866224083271188")
        assert row.PayloadBytes == 146 and row.ErrorReason is None
        with Session() as s:
            t = s.scalars(select(Telemetry)).one()
            assert (t.DeviceId, t.Protocol, t.SensorType, t.SignalDbm, t.FirmwareVersion) == ("866224083271188", "TCP", "rs485", 28, "V001")
            assert (t.Flow, t.TotalToday, t.TotalYesterday) == (0.0, 0.0, 0.0) and t.READ01 == "00000"
            assert (t.Timestamp.year, t.Timestamp.month, t.Timestamp.day, t.Timestamp.hour) == (2026, 10, 5, 12)
            raw = s.scalars(select(RawMessage)).one()
            assert raw.IsValid is True and "\x00" in raw.Payload and "\x01" in raw.Payload      # not normalised
        # the diagnostics detail keeps the exact bytes (HEX view) and re-parses successfully
        from app.diagnostics import inspect
        assert inspect.reparse("TCP", None, "127.0.0.1", SP_146, "TEXT", False).ok

    def test_unknown_imei_is_unknown_device_and_creates_nothing(self, db_env):
        Session = db_env
        _run_tcp([SP_146])
        row = _diag_rows(Session, "TCP")[0]
        assert (row.Status, row.Outcome, row.DeviceId) == ("UNKNOWN_DEVICE", "UNKNOWN_DEVICE", "866224083271188")
        assert _count(Session, Device) == 0 and _count(Session, Telemetry) == 0

    def test_malformed_sp_packet_is_still_a_visible_parse_error(self, db_env):
        Session = db_env
        _run_tcp([SP_146[:-1] + b"?"])
        row = _diag_rows(Session, "TCP")[0]
        assert (row.Status, row.Outcome) == ("INVALID", "PARSE_ERROR") and "Scanvix #SP frame rejected" in row.ErrorReason
        assert _count(Session, Telemetry) == 0

