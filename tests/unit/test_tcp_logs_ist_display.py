"""
Storm Energy RTU Platform — regression test for the TCP Test Log
"Received Time" +5:30 display bug.

Root cause (see ansible/scanvix_rtu/roles/tcp_log_viewer/files/tcp_logs.py):
  - app/timezone.py's now_ist() is the single source of truth for how this
    project stores ReceivedAt/CreatedAt: a NAIVE datetime whose wall-clock
    numbers already represent Asia/Kolkata time (not naive UTC). Every
    ReceivedAt/CreatedAt column in app/database/models.py defaults to
    now_ist() -- confirmed by direct inspection, not assumed.
  - The TCP Test Log viewer (tcp_logs.py) had a RECEIVED_AT_STORED_AS = "utc"
    flag that told its own _format_ist() helper to treat that already-IST
    naive value as UTC and convert it to IST a SECOND time (+5:30 again),
    which is exactly the "Received Time ~5h30m ahead of actual IST" bug
    reported against the live TCP Test Log page.
  - The fix is RECEIVED_AT_STORED_AS = "ist", so a value that already
    represents IST wall-clock time is only ever labelled, never re-converted.

This test loads the real deployed source file directly (the same file
Ansible copies verbatim to app/api/tcp_logs.py -- see
roles/tcp_log_viewer/tasks/deploy.yml) via importlib, stubbing only the
module's `from app.database.database import engine` import (a live SQL
Server connection is neither available nor desired for a unit test) so the
actual _format_ist()/RECEIVED_AT_STORED_AS logic under test is exactly the
shipped code, not a reimplementation.
"""
import importlib.util
import os
import sys
import types
from datetime import datetime, timezone, timedelta

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
TCP_LOGS_PATH = os.path.join(
    REPO_ROOT, "ansible", "scanvix_rtu", "roles", "tcp_log_viewer", "files", "tcp_logs.py"
)


def _load_tcp_logs_module():
    """Import the real tcp_logs.py, stubbing only its DB engine dependency."""
    # Stub app.database.database.engine so module-level `from app.database.database
    # import engine` succeeds without a real Settings()/SQL Server connection.
    fake_db_module = types.ModuleType("app.database.database")
    fake_db_module.engine = object()
    sys.modules.setdefault("app", types.ModuleType("app"))
    sys.modules.setdefault("app.database", types.ModuleType("app.database"))
    sys.modules["app.database.database"] = fake_db_module

    spec = importlib.util.spec_from_file_location("tcp_logs_under_test", TCP_LOGS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tcp_logs():
    return _load_tcp_logs_module()


class TestReceivedAtStoredAsFlagFixed:

    def test_flag_is_ist_not_utc(self, tcp_logs):
        # The actual bug: this flag must match reality (ReceivedAt is stored
        # as naive-but-IST via app.timezone.now_ist()), not "utc".
        assert tcp_logs.RECEIVED_AT_STORED_AS == "ist"


class TestFormatIstNoDoubleConversion:
    """
    app.database.models.ReceivedAt/CreatedAt columns store a NAIVE datetime
    whose wall-clock numbers already represent IST (app.timezone.now_ist()).
    _format_ist() must therefore return that value unchanged (only labelled
    "IST"), never shifted by an additional +5:30.
    """

    def test_naive_ist_value_is_not_shifted(self, tcp_logs):
        # Simulates a real ReceivedAt row exactly as SQLAlchemy/pyodbc would
        # hand it back: naive, wall-clock numbers = IST.
        stored = datetime(2026, 9, 21, 13, 3, 48)
        assert tcp_logs._format_ist(stored) == "21-Sep-2026 13:03:48 IST"

    def test_regression_reproduces_the_reported_bug_when_flag_is_utc(self, tcp_logs, monkeypatch):
        # Prove the mechanism: forcing the flag back to the old, wrong value
        # reproduces the exact symptom originally reported against the live
        # TCP Test Log (actual IST ~13:03:48 displayed as 18:33:48 IST).
        monkeypatch.setattr(tcp_logs, "RECEIVED_AT_STORED_AS", "utc")
        stored = datetime(2026, 9, 21, 13, 3, 48)
        assert tcp_logs._format_ist(stored) == "21-Sep-2026 18:33:48 IST"

    def test_string_datetime_from_db_driver_also_not_shifted(self, tcp_logs):
        # Some DB drivers/paths may hand back an ISO string rather than a
        # datetime object; _format_ist() parses it before formatting.
        assert tcp_logs._format_ist("2026-09-21T13:03:48") == "21-Sep-2026 13:03:48 IST"

    def test_none_returns_empty_string(self, tcp_logs):
        assert tcp_logs._format_ist(None) == ""

    def test_already_tz_aware_ist_value_passes_through_unchanged(self, tcp_logs):
        # If a value ever does arrive tz-aware IST (e.g. a future schema
        # change), it must not be re-converted either.
        ist = timezone(timedelta(hours=5, minutes=30))
        aware = datetime(2026, 9, 21, 13, 3, 48, tzinfo=ist)
        assert tcp_logs._format_ist(aware) == "21-Sep-2026 13:03:48 IST"


class TestRtuMeasurementTimestampUntouchedByThisFix:
    """This bug and fix are scoped to ReceivedAt display only. Guard that the
    viewer never touches RTU-supplied telemetry timestamp semantics -- it has
    no telemetry `ts`/Timestamp field in its SELECT or output at all."""

    def test_viewer_sql_selects_no_telemetry_timestamp_column(self):
        with open(TCP_LOGS_PATH, encoding="utf-8") as f:
            src = f.read()
        assert "t.Timestamp" not in src
        assert "Telemetry" not in src
