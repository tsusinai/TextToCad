"""Tests for negative-feature pattern_of (linear/polar cutter arrays).

Iteration 5: pattern nodes with parameters.pattern_of array the referenced
cutter node and subtract every instance from the host input; the baselines
below are volume/face-exact matches against equivalent hand-written multi-cut
constructions (the polar case also reproduces the golden flange value).
"""
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app
from ir_executor import IRExecutionError, execute_ir, shape_metrics
from ir_validate import IRValidationError

requires_kernel = pytest.mark.skipif(app.cq is None, reason="CadQuery required for pattern geometry")


def _linear_ir(mode: str, cutter_radius: float = 4.0) -> dict:
    nodes = [
        {"id": "host", "kind": "primitive", "operation": "box",
         "parameters": {"size": [100, 40, 10]}, "frame": "xy"},
        {"id": "hole", "kind": "primitive", "operation": "cylinder",
         "parameters": {"radius": cutter_radius, "height": 14, "position": [10, 0, -2]}},
    ]
    if mode == "manual":
        for index in (1, 2, 3):
            nodes.append({
                "id": f"h{index}", "kind": "primitive", "operation": "cylinder",
                "parameters": {"radius": cutter_radius, "height": 14, "position": [10 + 25 * index, 0, -2]},
            })
        nodes.append({"id": "drilled", "kind": "feature", "operation": "cut",
                      "inputs": ["host", "hole", "h1", "h2", "h3"], "parameters": {}})
    else:
        nodes.append({"id": "drilled", "kind": "feature", "operation": "linear_pattern",
                      "inputs": ["host"],
                      "parameters": {"pattern_of": "hole", "count": 4, "spacing": [25, 0, 0]}})
    return {
        "schema_version": "0.2",
        "document": {"id": "linear", "intent": "linear hole array", "units": "mm"},
        "units": "mm", "process": "fdm", "parameters": {},
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": nodes, "constraints": [],
        "outputs": [{"id": "main", "node": "drilled"}],
    }


def _flange_ir(mode: str) -> dict:
    nodes = [
        {"id": "body", "kind": "primitive", "operation": "cylinder",
         "parameters": {"radius": 30, "height": 10}, "frame": "xy"},
        {"id": "h0", "kind": "primitive", "operation": "cylinder",
         "parameters": {"radius": 4, "height": 14, "position": [16, 0, -2]}},
    ]
    if mode == "manual":
        for index, (x, y) in enumerate(((-16, 0), (0, 16), (0, -16))):
            nodes.append({
                "id": f"h{index + 1}", "kind": "primitive", "operation": "cylinder",
                "parameters": {"radius": 4, "height": 14, "position": [x, y, -2]},
            })
        nodes.append({"id": "drilled", "kind": "feature", "operation": "cut",
                      "inputs": ["body", "h0", "h1", "h2", "h3"], "parameters": {}})
    else:
        nodes.append({"id": "drilled", "kind": "feature", "operation": "polar_pattern",
                      "inputs": ["body"],
                      "parameters": {"pattern_of": "h0", "count": 4, "angle": 360, "axis": [0, 0, 1]}})
    return {
        "schema_version": "0.2",
        "document": {"id": "flange", "intent": "polar hole array", "units": "mm"},
        "units": "mm", "process": "fdm", "parameters": {},
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": nodes, "constraints": [],
        "outputs": [{"id": "main", "node": "drilled"}],
    }


@requires_kernel
def test_linear_pattern_of_matches_manual_multi_cut():
    manual = shape_metrics(execute_ir(app.validate_ir(_linear_ir("manual")))["shape"])
    patterned = shape_metrics(execute_ir(app.validate_ir(_linear_ir("pattern")))["shape"])
    assert patterned["volume_mm3"] == pytest.approx(manual["volume_mm3"], rel=1e-6)
    assert patterned["face_count"] == manual["face_count"] == 8
    assert patterned["solid_count"] == 1
    assert (patterned["bbox_mm"]["x"], patterned["bbox_mm"]["y"], patterned["bbox_mm"]["z"]) == (100.0, 40.0, 10.0)
    assert patterned["volume_mm3"] == pytest.approx(38994.690351, rel=1e-4)


@requires_kernel
def test_polar_pattern_of_reproduces_golden_flange():
    patterned = shape_metrics(execute_ir(app.validate_ir(_flange_ir("pattern")))["shape"])
    # Same construction as the golden crafted flange (26263.71 mm³, 7 faces).
    assert patterned["volume_mm3"] == pytest.approx(26263.714584, rel=1e-4)
    assert patterned["face_count"] == 7
    assert patterned["solid_count"] == 1


def test_pattern_of_dangling_reference_rejected_by_validator():
    bad = _flange_ir("pattern")
    bad["nodes"][-1]["parameters"]["pattern_of"] = "ghost_cutter"
    with pytest.raises(IRValidationError) as exc:
        app.validate_ir(bad)
    messages = " ".join(issue["message"] for issue in exc.value.issues)
    assert "ghost_cutter" in messages


@requires_kernel
def test_pattern_of_unknown_reference_raises_execution_error():
    bad = _flange_ir("pattern")
    bad["nodes"][-1]["parameters"]["pattern_of"] = "ghost_cutter"
    with pytest.raises(IRExecutionError, match="pattern_of"):
        execute_ir(bad)  # executor path without prior validation


@requires_kernel
def test_pattern_of_cache_key_tracks_cutter_geometry():
    small = shape_metrics(execute_ir(app.validate_ir(_linear_ir("pattern", cutter_radius=4.0)))["shape"])
    large = shape_metrics(execute_ir(app.validate_ir(_linear_ir("pattern", cutter_radius=6.0)))["shape"])
    # Same pattern node, different cutter radii: the module-level shape cache
    # must not return the first result for the second execution.
    assert small["volume_mm3"] == pytest.approx(38994.690351, rel=1e-4)
    assert large["volume_mm3"] < small["volume_mm3"]
    # The box is origin-centred (x in [-50, 50]); with r=6 only the holes at
    # x=10/35 still cut (x=60/85 fall outside), so exactly two bores deepen.
    assert large["volume_mm3"] == pytest.approx(small["volume_mm3"] - 2 * 3.14159265 * (36 - 16) * 10, rel=1e-3)
