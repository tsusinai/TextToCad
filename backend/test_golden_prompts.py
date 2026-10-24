"""Golden prompt regression suite (iteration 2, Task 1).

Two layers of geometry baselines protect the deterministic planner and the
manual IR compilation path against silent regressions:

1. Deterministic planner goldens: explicit primitive prompts must still
   compile through ``_deterministic_ir_plan`` and execute to a single solid
   with stable bounding box (±0.05 mm), volume (±1%) and exact face counts.
2. Manual IR goldens: hand-written Semantic CAD IR v0.2 documents (flange
   hole pattern, successful fillet, regular polygon prism) must execute with
   the recorded metrics and without any ``degraded_operations`` in the
   execution trace (fillet/shell/boolean fallbacks would be recorded there
   by ``ir_executor``).

All expected values below were captured from real executions of the current
(correct) pipeline (CadQuery 2.4.0) and then frozen; they are baselines, not
hand-computed ideals.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app


requires_kernel = pytest.mark.skipif(
    app.cq is None, reason="CadQuery is available in the Docker quality environment"
)


# ---------------------------------------------------------------------------
# Layer 1: deterministic planner golden prompts
# ---------------------------------------------------------------------------

GOLDEN_PROMPTS = [
    {
        "id": "cube-20mm",
        "prompt": "a cube 20 mm",
        "operation": "box",
        "bbox_mm": {"x": 20.0, "y": 20.0, "z": 20.0},
        "volume_mm3": 8000.0,
        "face_count": 6,
    },
    {
        "id": "sphere-40mm",
        "prompt": "a sphere 40 mm diameter",
        "operation": "sphere",
        "bbox_mm": {"x": 40.0, "y": 40.0, "z": 40.0},
        "volume_mm3": 33510.321638,
        "face_count": 1,
    },
    {
        "id": "cylinder-30x50",
        "prompt": "a cylinder 30 mm diameter and 50 mm tall",
        "operation": "cylinder",
        "bbox_mm": {"x": 30.0, "y": 30.0, "z": 50.0},
        "volume_mm3": 35342.917353,
        "face_count": 3,
    },
    {
        "id": "cone-30x40",
        "prompt": "a cone 30 mm diameter and 40 mm height",
        "operation": "cone",
        "bbox_mm": {"x": 30.0, "y": 30.0, "z": 40.0},
        "volume_mm3": 9431.065335,
        "face_count": 3,
    },
    {
        # 60 mm ring -> major radius 30, minor radius 7.5 (derived by planner).
        "id": "torus-60mm",
        "prompt": "a torus ring 60 mm diameter",
        "operation": "torus",
        "bbox_mm": {"x": 75.0, "y": 75.0, "z": 15.0},
        "volume_mm3": 33309.914854,
        "face_count": 1,
    },
    {
        "id": "hexagon-prism",
        "prompt": "a hexagon prism 30 mm wide",
        "operation": "regular_polygon",
        "bbox_mm": {"x": 30.0, "y": 20.1, "z": 42.0},
        "volume_mm3": 17630.756413,
        "face_count": 8,
    },
    {
        # tube: outer radius 20, derived through-hole radius 10.
        "id": "hollow-cylinder",
        "prompt": "a hollow cylinder 40 mm diameter and 50 mm tall",
        "operation": "cylinder",
        "bbox_mm": {"x": 40.0, "y": 40.0, "z": 50.0},
        "volume_mm3": 47123.889804,
        "face_count": 4,
    },
    {
        "id": "chinese-pentagon-prism",
        "prompt": "一个五边形棱柱",
        "operation": "regular_polygon",
        "bbox_mm": {"x": 120.0, "y": 120.0, "z": 42.0},
        "volume_mm3": 417906.519777,
        "face_count": 7,
    },
    {
        # plural regression: "blocks" must still satisfy the box token guard.
        "id": "two-blocks",
        "prompt": "two blocks 20 mm",
        "operation": "box",
        "bbox_mm": {"x": 120.0, "y": 80.4, "z": 24.0},
        "volume_mm3": 231552.0,
        "face_count": 6,
    },
    {
        # L-bracket style mounting plate: box + centred through hole cut.
        "id": "holed-mounting-box",
        "prompt": "a mounting box 60 mm wide, 40 mm deep, 10 mm tall with a hole",
        "operation": "box",
        "bbox_mm": {"x": 60.0, "y": 40.0, "z": 10.0},
        "volume_mm3": 20858.407346,
        "face_count": 7,
    },
]


@requires_kernel
@pytest.mark.parametrize("golden", GOLDEN_PROMPTS, ids=[item["id"] for item in GOLDEN_PROMPTS])
def test_deterministic_planner_golden_prompt(golden):
    _, params, _ = app.parse_prompt_detailed(golden["prompt"])
    ir = app._deterministic_ir_plan(golden["prompt"], "fdm", "mm", params)
    assert ir["provenance"]["planner"] == "deterministic_primitive"
    assert ir["nodes"][0]["operation"] == golden["operation"]

    normalized = app.validate_ir(ir)
    execution = app.execute_ir(normalized)
    metrics = app.shape_metrics(execution["shape"])

    assert metrics["valid_brep"] is True
    assert metrics["solid_count"] == 1
    for axis, expected in golden["bbox_mm"].items():
        assert metrics["bbox_mm"][axis] == pytest.approx(expected, abs=0.05), axis
    assert metrics["volume_mm3"] == pytest.approx(golden["volume_mm3"], rel=0.01)
    assert metrics["face_count"] == golden["face_count"]


# ---------------------------------------------------------------------------
# Layer 2: manual IR compilation goldens (validate -> execute, no planner)
# ---------------------------------------------------------------------------


def _flange_ir() -> dict:
    """70 mm flange, 10 mm thick, four 8 mm holes on a 48 mm bolt circle."""
    cutters = []
    for index, (x, y) in enumerate(((24, 0), (0, 24), (-24, 0), (0, -24))):
        cutters.append({
            "id": f"cutter_{index * 90}",
            "kind": "primitive",
            "operation": "cylinder",
            "parameters": {
                "radius": "hole_radius",
                "height": 18,
                "position": [x, y, -4],
            },
            "frame": "xy",
        })
    return {
        "schema_version": "0.2",
        "document": {"id": "flange", "intent": "flange 70 mm with 4 holes", "units": "mm"},
        "parameters": {
            "radius": {"value": 35, "unit": "mm", "source": "user", "role": "dimension"},
            "height": {"value": 10, "unit": "mm", "source": "user", "role": "dimension"},
            "hole_radius": {"value": 4, "unit": "mm", "source": "user", "role": "dimension"},
        },
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {
                "id": "flange",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": "radius", "height": "height"},
                "frame": "xy",
            },
            *cutters,
            {
                "id": "cut_hole_pattern_1",
                "kind": "feature",
                "operation": "cut",
                "inputs": ["flange"] + [cutter["id"] for cutter in cutters],
                "parameters": {},
            },
        ],
        "outputs": [{"id": "main", "node": "cut_hole_pattern_1", "format": ["step"]}],
    }


def _fillet_box_ir() -> dict:
    return {
        "schema_version": "0.2",
        "document": {"id": "fillet-box", "intent": "rounded box", "units": "mm"},
        "parameters": {
            "width": {"value": 30, "unit": "mm", "source": "user", "role": "dimension"},
            "depth": {"value": 20, "unit": "mm", "source": "user", "role": "dimension"},
            "height": {"value": 10, "unit": "mm", "source": "user", "role": "dimension"},
            "radius": {"value": 2, "unit": "mm", "source": "user", "role": "manufacturing"},
        },
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {
                "id": "body",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": ["width", "depth", "height"]},
                "frame": "xy",
            },
            {
                "id": "edge_treatment",
                "kind": "feature",
                "operation": "fillet",
                "inputs": ["body"],
                "parameters": {"radius": "radius"},
            },
        ],
        "outputs": [{"id": "main", "node": "edge_treatment", "format": ["step"]}],
    }


def _polygon_prism_ir() -> dict:
    return {
        "schema_version": "0.2",
        "document": {"id": "hex-prism", "intent": "hexagon prism", "units": "mm"},
        "parameters": {
            "width": {"value": 30, "unit": "mm", "source": "user", "role": "dimension"},
            "depth": {"value": 30, "unit": "mm", "source": "user", "role": "dimension"},
            "height": {"value": 12, "unit": "mm", "source": "user", "role": "dimension"},
        },
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {
                "id": "body",
                "kind": "primitive",
                "operation": "regular_polygon",
                "parameters": {
                    "sides": 6,
                    "width": "width",
                    "depth": "depth",
                    "height": "height",
                },
                "frame": "xy",
            },
        ],
        "outputs": [{"id": "main", "node": "body", "format": ["step"]}],
    }


def _assert_no_degraded_operations(trace):
    degraded = [
        (event.get("id"), event.get("degraded_operations"))
        for event in trace
        if event.get("degraded_operations")
    ]
    assert degraded == [], f"execution degraded silently: {degraded}"


@requires_kernel
def test_manual_ir_flange_with_four_hole_pattern():
    execution = app.execute_ir(app.validate_ir(_flange_ir()))
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["valid_brep"] is True
    assert metrics["solid_count"] == 1
    assert metrics["bbox_mm"] == {"x": 70.0, "y": 70.0, "z": 10.0}
    assert metrics["volume_mm3"] == pytest.approx(36473.890708, rel=0.01)
    assert metrics["face_count"] == 7  # 2 planar + outer wall + 4 bores
    _assert_no_degraded_operations(execution["trace"])


@requires_kernel
def test_manual_ir_fillet_box_success_path():
    execution = app.execute_ir(app.validate_ir(_fillet_box_ir()))
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["valid_brep"] is True
    assert metrics["solid_count"] == 1
    assert metrics["bbox_mm"] == {"x": 30.0, "y": 20.0, "z": 10.0}
    assert metrics["volume_mm3"] == pytest.approx(5804.696111, rel=0.01)
    assert metrics["face_count"] == 26  # 6 planar + 12 cylinders + 8 corner spheres
    _assert_no_degraded_operations(execution["trace"])


@requires_kernel
def test_manual_ir_regular_polygon_prism():
    execution = app.execute_ir(app.validate_ir(_polygon_prism_ir()))
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["valid_brep"] is True
    assert metrics["solid_count"] == 1
    assert metrics["bbox_mm"] == {"x": 30.0, "y": 30.0, "z": 12.0}
    assert metrics["volume_mm3"] == pytest.approx(7518.446165, rel=0.01)
    assert metrics["face_count"] == 8  # 6 sides + 2 caps
    _assert_no_degraded_operations(execution["trace"])
