"""Tests for stage telemetry aggregation (iteration 2, Task 4)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app


def test_summarize_telemetry_aggregates_completed_events():
    recorder = app.GenerationRecorder()
    recorder.emit("parsing", "interpretation", "running")
    recorder.emit("parsing", "interpretation", "succeeded")
    recorder.emit("planning", "ir_plan", "running")
    recorder.emit("planning", "ir_plan", "succeeded")
    recorder.emit("exporting", "exports", "running")  # left running: must not count

    summary = app._summarize_telemetry(recorder, llm_calls=1, vlm_calls=2)
    assert set(summary["stages"]) == {"parsing", "planning"}
    # Windows' coarse monotonic clock can legitimately yield 0 ms durations,
    # so only require non-negative ints and a consistent total.
    for stage, total in summary["stages"].items():
        assert isinstance(total, int) and total >= 0, stage
    assert summary["total_ms"] == sum(summary["stages"].values())
    assert summary["llm_calls"] == 1
    assert summary["vlm_calls"] == 2


def test_summarize_telemetry_none_recorder_returns_zeroes():
    summary = app._summarize_telemetry(None)
    assert summary == {"total_ms": 0, "stages": {}, "llm_calls": 0, "vlm_calls": 0}


def test_bump_telemetry_increments_monotonically():
    before = dict(app._TELEMETRY_TOTALS)
    try:
        first = app._bump_telemetry("generations")
        second = app._bump_telemetry("generations")
        assert second == first + 1
        assert app._TELEMETRY_TOTALS["generations"] == before.get("generations", 0) + 2
    finally:
        app._TELEMETRY_TOTALS.clear()
        app._TELEMETRY_TOTALS.update(before)


def test_health_exposes_telemetry_totals():
    from fastapi.testclient import TestClient

    client = TestClient(app.app)
    response = client.get("/health")
    assert response.status_code == 200
    totals = response.json()["telemetry_totals"]
    assert isinstance(totals, dict)
    assert {"generations", "agent_generations", "failures"} <= set(totals)
    assert all(isinstance(value, int) for value in totals.values())
