"""
Guards for the Docker Compose deployment (Windows server 192.168.0.50).

- compose.yml never takes host ports owned by existing services on .50
- storm-api is published on loopback only
- every service has a restart policy, healthcheck and rotated logs
- requirements-prod.txt pins match requirements.txt
- container healthcheck helper (tcp-listen / http)
- /health honesty: disabled components are "disabled", an unreachable
  database is never reported as healthy
"""
from __future__ import annotations

import importlib.util
import os
import re
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

# Host ports owned by existing applications on 192.168.0.50 — must never be bound.
RESERVED_HOST_PORTS = {80, 1433, 1434, 1883, 3389, 8089, 8090}
APPROVED_HOST_PORTS = {443, 8080, 1884, 8100, 444, 8000}


def _load_compose() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load((ROOT / "compose.yml").read_text(encoding="utf-8"))


def _default(value: str) -> str:
    """Resolve '${VAR:-default}' to its default for static inspection."""
    return re.sub(r"\$\{[A-Z_]+:-([^}]*)\}", r"\1", str(value))


def _published(compose: dict):
    for name, svc in compose["services"].items():
        for spec in svc.get("ports", []):
            parts = _default(spec).split(":")
            if len(parts) == 3:
                host_ip, host_port, target = parts
            else:
                host_ip, (host_port, target) = "0.0.0.0", parts
            yield name, host_ip, int(host_port), int(target)


class TestComposePorts:
    def test_expected_services(self):
        assert set(_load_compose()["services"]) == {"storm-api", "storm-tcp", "mosquitto", "storm-frontend", "reverse-proxy"}

    def test_frontend_has_no_host_port(self):
        # The web UI is reachable only through reverse-proxy (no separate public port).
        assert "ports" not in _load_compose()["services"]["storm-frontend"]

    def test_no_reserved_host_ports(self):
        for name, _ip, host_port, _t in _published(_load_compose()):
            assert host_port not in RESERVED_HOST_PORTS, f"{name} binds reserved host port {host_port}"

    def test_only_approved_host_ports(self):
        used = {p for _n, _i, p, _t in _published(_load_compose())}
        assert used == APPROVED_HOST_PORTS

    def test_api_is_loopback_only(self):
        api = [(ip, hp, t) for n, ip, hp, t in _published(_load_compose()) if n == "storm-api"]
        assert api == [("127.0.0.1", 8000, 8000)]

    def test_native_container_ports(self):
        targets = {n: t for n, _i, _h, t in _published(_load_compose())}
        assert targets["storm-tcp"] == 8100          # the listener port inside the container never changes
        assert targets["mosquitto"] == 1883


class TestComposeRuntimePolicy:
    def test_restart_healthcheck_logging(self):
        for name, svc in _load_compose()["services"].items():
            assert svc.get("restart") == "unless-stopped", name
            assert "healthcheck" in svc, name
            opts = svc["logging"]["options"]
            assert opts["max-size"] and opts["max-file"], name

    def test_no_privileged_containers(self):
        for name, svc in _load_compose()["services"].items():
            assert not svc.get("privileged"), name

    def test_api_runs_without_tcp_listener_and_tcp_runs_standalone(self):
        services = _load_compose()["services"]
        assert services["storm-api"]["environment"]["ENABLE_TCP_SERVER"] == "false"
        assert services["storm-tcp"]["command"] == ["python", "-m", "app.tcp.server"]

    def test_sql_server_reached_via_host_gateway(self):
        services = _load_compose()["services"]
        for name in ("storm-api", "storm-tcp"):
            assert _default(services[name]["environment"]["SQL_SERVER"]) == "host.docker.internal"

    def test_no_literal_secrets_in_compose(self):
        text = (ROOT / "compose.yml").read_text(encoding="utf-8")
        assert not re.search(r"(PASSWORD|SECRET)[A-Z_]*:\s*[\"']?[A-Za-z0-9]{6,}", text)


def _pins(path: Path) -> dict[str, str]:
    pins = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if "==" in line:
            name, ver = line.split("==", 1)
            pins[re.sub(r"\[.*\]", "", name).lower()] = ver.strip()
    return pins


def test_requirements_prod_pins_match_requirements_txt():
    prod = _pins(ROOT / "backend" / "requirements-prod.txt")
    full = _pins(ROOT / "backend" / "requirements.txt")
    assert prod, "requirements-prod.txt is empty"
    for name, ver in prod.items():
        assert full.get(name) == ver, f"{name}: prod={ver} requirements.txt={full.get(name)}"
    for dev_only in ("pytest", "faker", "pytest-mock", "pytest-asyncio"):
        assert dev_only not in prod


def _healthcheck_module():
    spec = importlib.util.spec_from_file_location(
        "storm_healthcheck", ROOT / "backend" / "docker" / "healthcheck.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.skipif(not os.path.exists("/proc/net/tcp"), reason="Linux /proc required")
def test_tcp_listen_healthcheck_detects_listener():
    hc = _healthcheck_module()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert hc.check_tcp_listen(port) == 0
    finally:
        srv.close()
    assert hc.check_tcp_listen(port) == 1


class TestHealthHonesty:
    @pytest.fixture()
    def health(self, monkeypatch):
        monkeypatch.setenv("API_SECRET_KEY", "test-only")
        monkeypatch.setenv("SQL_SERVER", "127.0.0.1")
        pytest.importorskip("fastapi")
        from app.api import health as health_mod
        from app.config import Settings
        return health_mod, Settings

    def _patch(self, monkeypatch, health_mod, Settings, *, db_ok, tcp_enabled, mqtt_connected=True):
        settings = Settings(API_SECRET_KEY="t", SQL_SERVER="h",
                            ENABLE_TCP_SERVER=tcp_enabled, ENABLE_MQTT_CONSUMER=True)
        monkeypatch.setattr(health_mod, "get_settings", lambda: settings)
        monkeypatch.setattr(health_mod, "check_database_connection", lambda: db_ok)

        class _Mqtt:
            is_connected = mqtt_connected
            stats = {"messages_processed": 0, "errors": 0}
        health_mod.set_service_refs(_Mqtt(), None)

    def test_disabled_tcp_does_not_degrade(self, monkeypatch, health):
        health_mod, Settings = health
        self._patch(monkeypatch, health_mod, Settings, db_ok=True, tcp_enabled=False)
        resp = health_mod.health_check()
        assert resp.tcp.status == "disabled"
        assert resp.status == "ok"

    def test_database_down_is_never_hidden(self, monkeypatch, health):
        health_mod, Settings = health
        self._patch(monkeypatch, health_mod, Settings, db_ok=False, tcp_enabled=False)
        resp = health_mod.health_check()
        assert resp.database.status == "down"
        assert resp.status == "down"

    def test_enabled_tcp_missing_is_degraded(self, monkeypatch, health):
        health_mod, Settings = health
        self._patch(monkeypatch, health_mod, Settings, db_ok=True, tcp_enabled=True)
        assert health_mod.health_check().status == "degraded"

    def test_live_endpoint_makes_no_database_claim(self, health):
        health_mod, _ = health
        resp = health_mod.health_live()
        assert resp.status == "ok"
        assert "database" not in resp.details.lower()


class TestReverseProxyTls:
    def test_certificate_directory_mounted_read_only(self):
        rp = _load_compose()["services"]["reverse-proxy"]
        cert_mounts = [v for v in rp["volumes"] if isinstance(v, dict) and v.get("target") == "/etc/nginx/certs"]
        assert len(cert_mounts) == 1
        assert cert_mounts[0]["read_only"] is True
        assert cert_mounts[0]["bind"]["create_host_path"] is False

    def test_template_uses_configurable_file_names(self):
        tpl = (ROOT / "docker" / "nginx" / "templates" / "storm.conf.template").read_text(encoding="utf-8")
        assert "ssl_certificate           /etc/nginx/certs/${STORM_TLS_CERT_FILE};" in tpl
        assert "ssl_certificate_key       /etc/nginx/certs/${STORM_TLS_KEY_FILE};" in tpl
        env = _load_compose()["services"]["reverse-proxy"]["environment"]
        assert env["NGINX_ENVSUBST_FILTER"] == "^STORM_TLS_"

    def test_proxy_routes_ui_and_api(self):
        tpl = (ROOT / "docker" / "nginx" / "templates" / "storm.conf.template").read_text(encoding="utf-8")
        assert "set $storm_frontend http://storm-frontend:8080;" in tpl
        assert re.search(r"location / \{ proxy_pass \$storm_frontend; \}", tpl)
        for loc in ("location /api/ ", "location = /api ", "location = /health ", "location /health/ "):
            line = next(l for l in tpl.splitlines() if l.strip().startswith(loc.strip()))
            assert "$storm_api" in line, line
        assert "return 404 '{\"detail\":\"Not found. Storm Energy RTU web UI is not deployed" not in tpl

    def test_proxy_waits_for_frontend(self):
        deps = _load_compose()["services"]["reverse-proxy"]["depends_on"]
        assert deps["storm-frontend"]["condition"] == "service_healthy"
        assert deps["storm-api"]["condition"] == "service_healthy"

    def test_no_private_keys_in_repository(self):
        tracked_like = [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts and ".local" not in p.parts]
        for path in tracked_like:
            if path.suffix in {".pem", ".key", ".crt"} and path.parent.name != "certs":
                pytest.fail(f"certificate/key material in repository: {path}")
            if path.suffix in {".py", ".yml", ".yaml", ".conf", ".ps1", ".psm1", ".sh", ".md", ".template", ".example"}:
                assert "BEGIN RSA PRIVATE KEY" not in path.read_text(encoding="utf-8", errors="ignore") or path.name.startswith("test_"), path


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_tls_check_script_validates_san_key_and_expiry(tmp_path):
    def run(*cmd):
        subprocess.run(cmd, cwd=tmp_path, check=True, capture_output=True)

    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "5", "-subj", "/CN=mqtt.stormenergy.in",
        "-addext", "subjectAltName=DNS:mqtt.stormenergy.in", "-keyout", "key.pem", "-out", "crt.pem")
    run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "5", "-subj", "/CN=other",
        "-keyout", "other.pem", "-out", "other-crt.pem")
    script = (ROOT / "scripts" / "deploy" / "tls-check.sh").read_text(encoding="utf-8")
    script = script.replace("apk add --no-cache openssl >/dev/null 2>&1 ||", "true ||").replace("/certs/", f"{tmp_path}/")
    (tmp_path / "check.sh").write_text(script, encoding="utf-8")

    def check(cert, key, host):
        env = {**os.environ, "STORM_TLS_CERT_FILE": cert, "STORM_TLS_KEY_FILE": key, "STORM_TLS_HOST": host}
        out = subprocess.run(["sh", str(tmp_path / "check.sh")], env=env, capture_output=True, text=True).stdout
        return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)

    ok = check("crt.pem", "key.pem", "mqtt.stormenergy.in")
    assert ok["HOST_MATCH"] == "yes" and ok["KEY_MATCH"] == "yes" and ok["EXPIRED"] == "no"
    assert ok["EXPIRES_14D"] == "yes"          # 5-day certificate triggers the renewal warning
    assert "PRIVATE" not in "".join(ok.values())
    bad = check("crt.pem", "other.pem", "192.168.0.50")
    assert bad["HOST_MATCH"] == "no" and bad["KEY_MATCH"] == "no"
    assert check("missing.pem", "key.pem", "x")["ERROR"] == "certificate-file-not-found"


class TestPhaseASqlSafety:
    """E1/E2/E3 guards for the Phase A database initialisation."""

    SQL_FILES = ["001_database.sql", "002_tables.sql", "003_indexes.sql", "004_constraints.sql",
                 "security/create_app_login.sql"]

    def _sql(self, name):
        return (ROOT / "database" / name).read_text(encoding="utf-8").replace("\r\n", "\n")

    def test_e1_no_sqlcmd_variable_inside_comments(self):
        # sqlcmd expands $(VAR) inside comments too -> a password in a comment is sent as batch text
        for name in self.SQL_FILES:
            for n, line in enumerate(self._sql(name).split("\n"), 1):
                if "--" in line:
                    assert "$(" not in line.split("--", 1)[1], f"{name}:{n} sqlcmd variable in a comment"

    def test_e1_password_variable_used_exactly_once_in_create_login(self):
        sql = self._sql("security/create_app_login.sql")
        assert sql.count("$(STORM_APP_PASSWORD)") == 1
        line = next(l for l in sql.split("\n") if "$(STORM_APP_PASSWORD)" in l)
        assert "WITH PASSWORD" in line

    def test_e3_read_committed_snapshot_alter_is_guarded(self):
        sql = self._sql("001_database.sql")
        before_alter = sql[: sql.index("ALTER DATABASE")]
        guard = before_alter[before_alter.rindex("IF "):]
        assert "is_read_committed_snapshot_on = 0" in guard

    def test_no_destructive_statements_and_no_storm_database_reference(self):
        for name in self.SQL_FILES:
            code = re.sub(r"--[^\n]*", "", self._sql(name))
            # the only DELETE allowed is the retention permission on the diagnostics table
            code = re.sub(r"N?'[^']*'", "''", code)          # PRINT/THROW message text is not SQL
            code = code.replace("GRANT DELETE ON OBJECT::dbo.ProtocolDiagnosticLogs", "GRANT_DIAG_RETENTION")
            assert not re.search(r"\b(DROP|DELETE|TRUNCATE|RESTORE)\b", code, re.I), name
            for db in re.findall(r"\bUSE\s+\[?(\w+)\]?", code, re.I):
                assert db in {"master", "STORM_ENERGY_RTU"}, f"{name} switches to {db}"
            assert not re.search(r"\[Storm\]|\bStorm\.", code), name

    def test_e2_required_schema_derivation_matches_scripts(self):
        # Mirrors Get-StormRequiredSchema in scripts/deploy/StormRtu.psm1
        found = set()
        for name in ["002_tables.sql", "003_indexes.sql", "004_constraints.sql"]:
            code = re.sub(r"--[^\n]*", "", self._sql(name))
            found |= {("TABLE", m) for m in re.findall(r"(?i)\bCREATE\s+TABLE\s+(?:dbo\.)?\[?(\w+)", code)}
            found |= {("CONSTRAINT", m) for m in re.findall(r"(?i)\bCONSTRAINT\s+\[?(\w+)", code)}
            found |= {("INDEX", m) for m in re.findall(r"(?i)\bCREATE\s+(?:UNIQUE\s+)?(?:(?:NON)?CLUSTERED\s+)?INDEX\s+\[?(\w+)", code)}
        kinds = {k: sum(1 for kk, _ in found if kk == k) for k in ("TABLE", "CONSTRAINT", "INDEX")}
        # 15 base constraints + 4 device-metadata checks (005) + ProtocolDiagnosticLogs PK/3 checks (006)
        assert kinds == {"TABLE": 9, "CONSTRAINT": 23, "INDEX": 8}
        # the migration must create exactly the objects a fresh install gets from 002
        mig = re.sub(r"--[^\n]*", "", self._sql("005_device_metadata.sql"))
        mig_constraints = {m for m in re.findall(r"(?i)\bCONSTRAINT\s+\[?(\w+)", mig)}
        assert mig_constraints == {"CK_Devices_Latitude", "CK_Devices_Longitude", "CK_Devices_LatLngPair",
                                   "CK_Devices_NotNullIsland"}
        assert mig_constraints <= {n for k, n in found if k == "CONSTRAINT"}

    def test_metadata_migration_is_additive_and_idempotent(self):
        sql = self._sql("005_device_metadata.sql")
        code = re.sub(r"--[^\n]*", "", sql)
        assert not re.search(r"\b(DROP|DELETE|TRUNCATE|UPDATE|RESTORE)\b", code, re.I)
        assert [db for db in re.findall(r"\bUSE\s+\[?(\w+)\]?", code, re.I)] == ["STORM_ENERGY_RTU"]
        assert not re.search(r"\[Storm\]|\bStorm\.", code)
        for col in ("Name", "Latitude", "Longitude"):
            assert re.search(rf"COL_LENGTH\(N?'dbo\.Devices',\s*N?'{col}'\)\s+IS\s+NULL", code, re.I), col
        assert code.count("sys.check_constraints") >= 4
        for col, typ in (("Name", "NVARCHAR(100)"), ("Latitude", "DECIMAL(9,6)"), ("Longitude", "DECIMAL(9,6)")):
            assert re.search(rf"ADD\s+\[?{col}\]?\s+{re.escape(typ)}\s+NULL", code, re.I), col
        assert sql.isascii()

    def test_diagnostics_migration_is_additive_and_limits_delete_to_its_table(self):
        sql = self._sql("006_protocol_diagnostics.sql")
        code = re.sub(r"--[^\n]*", "", sql)
        assert sql.isascii()
        assert [db for db in re.findall(r"\bUSE\s+\[?(\w+)\]?", code, re.I)] == ["STORM_ENERGY_RTU"]
        assert not re.search(r"\b(DROP|TRUNCATE|UPDATE|RESTORE|ALTER\s+TABLE)\b", code, re.I)
        assert re.findall(r"(?i)\bDELETE\b[^;]*", re.sub(r"N?'[^']*'", "''", code)) == ["DELETE ON OBJECT::dbo.ProtocolDiagnosticLogs TO [$(STORM_APP_LOGIN)]"]
        assert "ON SCHEMA::" not in code and "REFERENCES" not in code.upper()   # no schema-wide grant, no FK to Devices
        assert re.findall(r"(?i)CREATE\s+TABLE\s+(?:dbo\.)?(\w+)", code) == ["ProtocolDiagnosticLogs"]
        # identical table definition for fresh installs (002) and existing databases (006)
        table = code[code.index("CREATE TABLE"):code.index(");", code.index("CREATE TABLE"))]
        assert table in re.sub(r"--[^\n]*", "", self._sql("002_tables.sql"))
        # login script grants the same object-level DELETE (fresh installs)
        assert "GRANT DELETE ON OBJECT::dbo.ProtocolDiagnosticLogs TO [$(STORM_APP_LOGIN)]" in self._sql("security/create_app_login.sql")

    def test_e2_partial_database_fails_closed(self):
        psm = (ROOT / "scripts" / "deploy" / "StormRtu.psm1").read_text(encoding="utf-8")
        body = psm[psm.index("function Invoke-StormDatabaseInit"):psm.index("function Invoke-StormHealthCheck")]
        assert "$schema = Get-StormSchemaState" in body
        assert "initialisation is INCOMPLETE" in body
        # The incomplete branch must throw before the login section is reached
        incomplete = body[body.index("} else {", body.index("elseif ($schema.Complete)")):body.index("$login = Get-StormEnvValue")]
        assert "throw" in incomplete and "sqlcmd" not in incomplete.replace("sqlcmd -S localhost -E -C -b -i database", "")
        assert not re.search(r"(?i)DROP\s+DATABASE", psm)
