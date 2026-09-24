"""Tests for the RTU simulator telemetry generator."""
import sys
sys.path.insert(0, "backend")

from scripts.telemetry_generator import (
    make_duplicate, make_historical_batch,
    make_invalid_payload, make_telemetry,
)


def test_make_telemetry_has_required_fields():
    t = make_telemetry("123", "BENCH")
    assert t["deviceId"] == "123"
    assert t["siteid"]   == "BENCH"
    assert "ts"          in t
    assert "flow"        in t

def test_make_telemetry_optional_fields_are_none():
    t = make_telemetry("123")
    assert t["battery"]  is None
    assert t["READ01"]   is None
    assert t["PRESSURE"] is None

def test_make_historical_batch_length():
    batch = make_historical_batch("123", count=5)
    assert len(batch) == 5

def test_make_historical_batch_timestamps_are_ordered():
    batch = make_historical_batch("123", count=3, start_hours_ago=1)
    ts = [r["ts"] for r in batch]
    assert ts == sorted(ts)

def test_make_duplicate_is_equal():
    base = make_telemetry("123")
    dup  = make_duplicate(base)
    assert dup == base
    assert dup is not base

def test_make_invalid_payload_is_string():
    p = make_invalid_payload()
    assert isinstance(p, str)
