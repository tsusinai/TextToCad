"""Tests for the main-chain assembly clearance check (iteration 6).

Multi-output IR documents get a pairwise entity mating report in
checks["assembly_clearance"] — warning-level, never fatal.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app
from ir_executor import execute_ir

requires_kernel = pytest.mark.skipif(app.cq is None, reason="CadQuery required for clearance geometry")


def _two_cylinder_ir(offset_x: float) -> dict:
    return {
        "schema_version": "0.2",
        "document": {"id": "pair", "intent": "two output cylinders", "units": "mm"},
        "units": "mm", "process": "fdm", "parameters": {},
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {"id": "left", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": 5, "height": 10, "position": [0, 0, 0]}, "frame": "xy"},
            {"id": "right", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": 5, "height": 10, "position": [offset_x, 0, 0]}, "frame": "xy"},
        ],
        "constraints": [],
        "outputs": [
            {"id": "out_left", "node": "left"},
            {"id": "out_right", "node": "right"},
        ],
    }


@requires_kernel
def test_well_separated_pair_reports_pass():
    execution = execute_ir(app.validate_ir(_two_cylinder_ir(30.0)))
    report = app._assembly_clearance_report(execution["output_shapes"])
    assert report is not None
    assert report["checked_pairs"] == 1
    assert report["hard"] is False
    assert report["status"] == "pass"
    pair = report["pairs"][0]
    assert pair["pair"] == ["left", "right"]
    assert pair["distance_mm"] == pytest.approx(20.0, abs=0.05)  # 30 - 2 x r5


@requires_kernel
def test_overlapping_pair_reports_interference():
    execution = execute_ir(app.validate_ir(_two_cylinder_ir(6.0)))
    report = app._assembly_clearance_report(execution["output_shapes"])
    assert report["status"] == "interference"
    pair = report["pairs"][0]
    assert pair["interference"] is True
    # Two r=5 cylinders 6 mm apart overlap over a lens-shaped cross-section.
    assert pair["intersection_volume_mm3"] > 1.0


@requires_kernel
def test_single_output_returns_none():
    execution = execute_ir(app.validate_ir(_two_cylinder_ir(30.0)))
    single = {"left": execution["output_shapes"]["left"]}
    assert app._assembly_clearance_report(single) is None
    assert app._assembly_clearance_report({}) is None


@requires_kernel
def test_generation_checks_carry_assembly_clearance(monkeypatch):
    """End-to-end wiring: a multi-output IR surfaces the report in checks."""
    import shutil

    def _fake_llm(prompt, process, units):
        raise RuntimeError("LLM disabled for test")

    interfering_ir = _two_cylinder_ir(6.0)

    def _fake_planner(prompt, process, units, params):
        return interfering_ir

    monkeypatch.setattr(app, "_llm_ir_json", _fake_llm)
    monkeypatch.setattr(app, "_deterministic_ir_plan", _fake_planner)
    request = app.GenerateRequest(prompt="two overlapping test cylinders")
    response = app._generate_ir_model(request)
    try:
        report = response.checks.get("assembly_clearance")
        assert report is not None, "multi-output generation must attach the clearance report"
        assert report["status"] == "interference"
        assert report["hard"] is False
        assert report["checked_pairs"] == 1
        assert report["pairs"][0]["interference"] is True
    finally:
        shutil.rmtree(app.ARTIFACT_ROOT / response.model_id, ignore_errors=True)
