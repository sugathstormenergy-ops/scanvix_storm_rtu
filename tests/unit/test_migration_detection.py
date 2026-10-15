"""
Regression tests for deploy.ps1 -MigrateDatabase migration detection (live failure on
2026-09-28): STORM_ENERGY_RTU had 001-005 applied and 006 absent, but the preflight
reported "Base schema objects are missing".

Root cause: Get-StormSchemaState returned the missing object names as ONE STRING_AGG value
through sqlcmd, which cuts variable-length columns at 256 characters in text output. The 7
missing 006 objects (296 characters) became "...,IN"; "IN" is created by no migration, so
the (correct, fail-closed) classifier refused a legitimate pending migration.

These tests run the REAL PowerShell module (pwsh) against tests/unit/deploy_sim/fake_sqlcmd.py,
which reproduces the 256-character truncation.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SIM = Path(__file__).resolve().parent / "deploy_sim"
PWSH = shutil.which("pwsh")
pytestmark = pytest.mark.skipif(PWSH is None, reason="PowerShell (pwsh) not installed")

SQL_OBJ_RX = {
    "TABLE": r"(?i)\bCREATE\s+TABLE\s+(?:dbo\.)?\[?(\w+)\]?",
    "CONSTRAINT": r"(?i)\bCONSTRAINT\s+\[?(\w+)\]?",
    "INDEX": r"(?i)\bCREATE\s+(?:UNIQUE\s+)?(?:(?:NON)?CLUSTERED\s+)?INDEX\s+\[?(\w+)\]?",
}


def objects(*files):
    keys = set()
    for f in files:
        text = re.sub(r"--[^\r\n]*", "", (ROOT / "database" / f).read_text(encoding="utf-8"))
        for kind, rx in SQL_OBJ_RX.items():
            keys |= {f"{kind}:{n}" for n in re.findall(rx, text)}
    return keys


MIG_006 = objects("006_protocol_diagnostics.sql")
MIG_005 = objects("005_device_metadata.sql")
ALL = objects("002_tables.sql", "003_indexes.sql", "004_constraints.sql", "005_device_metadata.sql",
              "006_protocol_diagnostics.sql")
BASE_001_005 = ALL - MIG_006                      # what the live database has today


# First column of the schema query, copied from .local/logs/deploy-20260928-160130.log (line 37).
LIVE_TRUNCATED = "TABLE:ProtocolDiagnosticLogs,CONSTRAINT:PK_ProtocolDiagnosticLogs,CONSTRAINT:CK_ProtocolDiagnosticLogs_Protocol,CONSTRAINT:CK_ProtocolDiagnosticLogs_Status,CONSTRAINT:CK_ProtocolDiagnosticLogs_Encoding,INDEX:IX_ProtocolDiagnosticLogs_Protocol_ReceivedAt,IN"


def run(tmp_path, present, scenario="migrate", **extra):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"present": sorted(present), "runs": [], **extra}))
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    wrapper = bindir / "sqlcmd"
    wrapper.write_text(f'#!/bin/sh\nexec python3 "{SIM / "fake_sqlcmd.py"}" "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
    env = {**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}", "FAKE_SQL_STATE": str(state)}
    env.pop("STORM_APP_LOGIN", None)
    p = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-File", str(SIM / "drive.ps1"),
                        "-RepoRoot", str(ROOT), "-Scenario", scenario],
                       capture_output=True, text=True, env=env, timeout=120)
    line = next((l for l in p.stdout.splitlines() if l.startswith("RESULT:")), None)
    assert line, p.stdout + p.stderr
    return json.loads(line[len("RESULT:"):]), json.loads(state.read_text())


def test_fixture_matches_live_state():
    assert len(MIG_006) == 7 and not (MIG_006 & BASE_001_005)
    assert len(",".join(sorted(MIG_006))) > 256          # the aggregate the old code relied on


def test_root_cause_reproduced_old_aggregate_is_truncated(tmp_path):
    res, _ = run(tmp_path, BASE_001_005, scenario="legacy-aggregate")
    # exactly what the live log showed: 256 characters ending in the fragment "IN"
    assert len(res["aggregate"]) == 256 and res["aggregate"].endswith(",IN")
    assert "IN" not in {k.split(":", 1)[1] for k in ALL}
    assert res["aggregate"] == LIVE_TRUNCATED


def test_case1_live_state_selects_only_006(tmp_path):
    res, state = run(tmp_path, BASE_001_005)
    assert res["complete"] is False and res["migrationOnly"] is True
    assert sorted(res["missing"]) == sorted(MIG_006)
    assert res["migrate"] == "ok"
    assert state["runs"] == [{"file": "006_protocol_diagnostics.sql", "login": "storm_rtu_app"}]
    assert res["loginEnvAfter"] == ""


def test_case1_then_second_run_selects_nothing(tmp_path):
    run(tmp_path, BASE_001_005)
    state_file = tmp_path / "state.json"
    present_after = json.loads(state_file.read_text())["present"]
    res, state = run(tmp_path, present_after)
    assert res["complete"] is True and res["missing"] == []
    assert res["migrate"] == "ok" and state["runs"] == []


def test_case2_everything_present_nothing_pending(tmp_path):
    res, state = run(tmp_path, ALL)
    assert res["complete"] is True and res["migrationOnly"] is False
    assert state["runs"] == []


@pytest.mark.parametrize("base_missing", ["TABLE:Telemetry", "CONSTRAINT:UQ_Devices_DeviceId",
                                          "INDEX:IX_Telemetry_Device_Ts"])
def test_case3_missing_base_object_still_stops(tmp_path, base_missing):
    assert base_missing in BASE_001_005 and base_missing not in (MIG_005 | MIG_006)
    res, state = run(tmp_path, BASE_001_005 - {base_missing})
    assert res["migrationOnly"] is False and base_missing in res["missing"]
    assert res["migrate"].startswith("error: Base schema objects are missing")
    assert state["runs"] == []


def test_both_migrations_pending_run_in_order(tmp_path):
    res, state = run(tmp_path, ALL - MIG_005 - MIG_006)
    assert res["migrationOnly"] is True
    assert [r["file"] for r in state["runs"]] == ["005_device_metadata.sql", "006_protocol_diagnostics.sql"]


def test_incomplete_catalog_output_fails_closed(tmp_path):
    res, state = run(tmp_path, BASE_001_005, drop_last_row=True)
    assert "Schema check output is incomplete" in res.get("stateError", "")
    assert state["runs"] == []
