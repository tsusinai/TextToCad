"""Regression tests for the text-to-CAD interpretation and quality contract.

These tests deliberately avoid starting CadQuery. Geometry/export smoke tests run in
the Docker image where the CAD kernel is available.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app


def test_explicit_units_are_normalized_to_mm():
    _, params, provenance = app.parse_prompt_detailed(
        "a block 12 cm wide, 8 cm deep and 4 cm tall",
        units="mm",
    )
    assert params.width == 120.0
    assert params.depth == 80.0
    assert params.height == 40.0
    assert provenance["units"]["confidence"] == "explicit"


def test_selected_unit_scales_unitless_dimension_triplet():
    _, params, provenance = app.parse_prompt_detailed(
        "a block 12 x 8 x 4",
        units="cm",
    )
    assert (params.width, params.depth, params.height) == (120.0, 80.0, 40.0)
    assert provenance["units"]["dimension_triplet"] == [12.0, 8.0, 4.0]


def test_diameter_is_used_for_both_circular_footprint_axes():
    _, params, _ = app.parse_prompt_detailed(
        "plant pot, 90 mm diameter and 82 mm tall",
    )
    assert params.kind == "plant"
    assert params.width == 90.0
    assert params.depth == 90.0
    assert params.height == 82.0


def test_feature_dimensions_do_not_become_body_dimensions():
    _, params, provenance = app.parse_prompt_detailed(
        "a cable clip for a 6 mm cable with a 3 mm snap opening",
    )
    assert params.kind == "clip"
    assert params.width != 6.0
    assert params.width == 120.0
    assert provenance["fields"]["width"]["status"] == "default"


def test_ir_divider_count_matches_geometry_loop():
    _, params, provenance = app.parse_prompt_detailed(
        "organizer 120 mm wide, 80 mm deep with 3 compartments",
    )
    ir = app.build_design_ir(
        "organizer 120 mm wide, 80 mm deep with 3 compartments",
        params,
        "standard",
        False,
        provenance["assumptions"],
        provenance,
    )
    divider = next(feature for feature in ir["features"] if feature["id"] == "dividers")
    assert divider["requested_count"] == 3
    assert divider["count"] == 2


def test_english_l_bracket_alias_is_supported():
    title, params, _ = app.parse_prompt_detailed(
        "L bracket 20x20, plate thickness 5",
    )
    assert title == "Parametric L bracket"
    assert params.kind == "angle"
    assert (params.width, params.depth, params.wall) == (20.0, 20.0, 5.0)


def test_llm_cannot_override_explicit_l_bracket(monkeypatch):
    monkeypatch.setattr(
        app,
        "_llm_json",
        lambda prompt, process, baseline: {
            "schema_version": "0.1",
            "kind": "organizer",
            "width": 20,
            "depth": 20,
            "height": 20,
            "wall": 3,
            "bottom": 3,
            "compartments": 3,
            "chamfer": 0,
        },
    )
    title, params, used, assumptions, _ = app.interpret_prompt(
        "20x20 是L形的外轮廓，板厚是3，细折条",
        "fdm",
        "advanced",
    )
    assert used is True
    assert title == "Parametric L bracket"
    assert params.kind == "angle"
    assert params.compartments == 1
    assert any("conflicted" in item for item in assumptions)


def test_l_bracket_prompt_preserves_angle_family_and_pair_dimensions():
    title, params, provenance = app.parse_prompt_detailed(
        "20x20 是L形的外轮廓，板厚是3，细折条",
    )
    assert title == "Parametric L bracket"
    assert params.kind == "angle"
    assert (params.width, params.depth) == (20.0, 20.0)
    assert params.wall == 3.0
    assert params.chamfer == 0.0
    assert provenance["units"]["dimension_pair"] == [20.0, 20.0]


def test_unknown_model_family_uses_solid_block_fallback():
    title, params, _ = app.parse_prompt_detailed(
        "a custom bird feeder 120 mm wide, 80 mm deep, 42 mm tall",
    )
    assert params.kind == "block"
    assert title == "Parametric solid"


def test_ordinary_cube_stays_sharp_and_cubic():
    title, params, _ = app.parse_prompt_detailed("a cube 50 mm")
    assert title == "Parametric solid"
    assert params.kind == "block"
    assert (params.width, params.depth, params.height) == (50.0, 50.0, 50.0)
    assert params.chamfer == 0.0
    assert params.edge_style == "chamfer"


def test_rounded_cube_requires_explicit_rounding_language():
    title, params, _ = app.parse_prompt_detailed("a cube with no sharp edges, 50 mm side")
    assert title == "Parametric rounded cube"
    assert params.kind == "rounded_cube"
    assert (params.width, params.depth, params.height) == (50.0, 50.0, 50.0)
    assert params.chamfer == 4.0
    assert params.edge_style == "fillet"


def test_cup_keyword_maps_to_open_cup_geometry():
    title, params, _ = app.parse_prompt_detailed("一个杯子，直径 80 mm，高 100 mm")
    assert title == "Parametric cup"
    assert params.kind == "cup"
    assert (params.width, params.depth, params.height) == (80.0, 80.0, 100.0)
    assert params.chamfer == 0.0


def test_airplane_keyword_maps_to_airframe_dimensions():
    title, params, _ = app.parse_prompt_detailed("一个飞机模型，机身长 160 mm，翼展 140 mm，高 40 mm")
    assert title == "Parametric airplane model"
    assert params.kind == "airplane"
    assert (params.width, params.depth, params.height) == (160.0, 140.0, 40.0)


def test_generation_recorder_tracks_real_milestones_in_order():
    recorder = app.GenerationRecorder()
    recorder.emit("parsing", "interpretation", "running")
    recorder.emit("parsing", "interpretation", "succeeded", llm_used=False)
    recorder.emit("building", "base_solid", "succeeded", operation="box")
    assert [event["id"] for event in recorder.events] == ["interpretation", "base_solid"]
    assert recorder.events[0]["status"] == "succeeded"
    assert recorder.events[0]["duration_ms"] >= 0
    assert recorder.events[1]["details"]["operation"] == "box"


def test_generation_request_can_request_step_previews():
    request = app.GenerateRequest(prompt="a 40 mm block", include_steps=True, material="petg")
    assert request.include_steps is True
    assert request.material == "petg"


def test_nominal_analysis_never_reports_manufacturing_ready():
    _, params, _ = app.parse_prompt_detailed("a 120 mm organizer")
    analysis = app.analyze_manufacturability(params)
    assert analysis["nominal"] is True
    assert analysis["review_required"] is True
    assert analysis["manufacturing_ready"] is False


def test_strict_dimensions_reject_ambiguous_input():
    _, _, provenance = app.parse_prompt_detailed("a block 120 80", units="mm")
    assert provenance["units"]["ambiguous_dimensions"] is True


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
@pytest.mark.parametrize(
    "prompt",
    [
        "tray 160 mm footprint, 12 mm wall",
        "organizer 120 mm wide, 80 mm deep, 42 mm high with 3 compartments",
        "plant pot 90 mm diameter and 82 mm tall with drainage holes",
        "pen cup 72 mm diameter and 95 mm tall",
        "lamp base 110 mm wide with cable channel",
        "cable clip for a 6 mm cable",
        "solid block 40 mm x 30 mm x 20 mm",
        "cube with no sharp edges, 50 mm side",
        "一个杯子，直径 80 mm，高 100 mm",
        "一个飞机模型，160 x 140 x 40 mm",
        "L bracket 20x20, plate thickness 3",
    ],
)
def test_supported_model_families_produce_valid_brep(prompt):
    _, params, _ = app.parse_prompt_detailed(prompt)
    analysis = app.analyze_manufacturability(params)
    shape = app.build_geometry(params)
    checks = app._validate_shape(shape, params, analysis)
    assert checks["valid_brep"] is True
    assert checks["occt_valid"] is True
    assert checks["nonzero_faces"] is True
    assert checks["single_solid"] is True
    assert checks["positive_volume"] is True



def test_legacy_design_ir_is_upgraded_to_v02():
    _, params, provenance = app.parse_prompt_detailed("a 120 mm organizer with 3 compartments")
    legacy_ir = app.build_design_ir(
        "a 120 mm organizer with 3 compartments",
        params,
        "standard",
        False,
        provenance["assumptions"],
        provenance,
    )
    assert legacy_ir["schema_version"] == "0.2"
    assert legacy_ir["nodes"]
    assert legacy_ir["features"]
    assert legacy_ir["outputs"][0]["node"] == legacy_ir["nodes"][-1]["id"]
    assert app.validate_ir(legacy_ir)["schema_version"] == "0.2"


def test_generic_primitive_ir_is_family_independent():
    ir = {
        "schema_version": "0.2",
        "document": {"id": "cup", "intent": "hollow body"},
        "parameters": {
            "radius": {"value": 40, "unit": "mm", "source": "user", "role": "dimension"},
            "wall": {"value": 2, "unit": "mm", "source": "derived", "role": "manufacturing"},
        },
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {"id": "outer", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": "radius", "height": 100}, "frame": "xy"},
            {"id": "inner", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": "radius - wall", "height": 98}, "frame": "xy"},
            {"id": "body", "kind": "feature", "operation": "cut", "inputs": ["outer", "inner"]},
        ],
        "constraints": [],
        "outputs": [{"id": "main", "node": "body", "format": ["step"]}],
    }
    normalized = app.validate_ir(ir)
    assert normalized["nodes"][-1]["operation"] == "cut"
    assert normalized["outputs"][0]["node"] == "body"


def test_ir_validation_rejects_dependency_cycles():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {"id": "a", "kind": "feature", "operation": "union", "inputs": ["b"]},
            {"id": "b", "kind": "feature", "operation": "union", "inputs": ["a"]},
        ],
        "outputs": [{"id": "main", "node": "a"}],
    }
    with pytest.raises(app.IRValidationError) as error:
        app.validate_ir(ir)
    assert any(issue["code"] == "cycle" for issue in error.value.issues)


def test_ir_validation_rejects_unregistered_operations():
    ir = {
        "schema_version": "0.2",
        "nodes": [{"id": "body", "kind": "feature", "operation": "run_python"}],
        "outputs": [{"id": "main", "node": "body"}],
    }
    with pytest.raises(app.IRValidationError) as error:
        app.validate_ir(ir)
    assert any(issue["code"] == "operation_not_allowed" for issue in error.value.issues)



@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_generic_ir_executor_builds_boolean_geometry():
    ir = {
        "schema_version": "0.2",
        "document": {"id": "boolean-demo"},
        "parameters": {
            "width": {"value": 40, "unit": "mm", "source": "user"},
            "depth": {"value": 40, "unit": "mm", "source": "user"},
            "height": {"value": 20, "unit": "mm", "source": "user"},
            "radius": {"value": 8, "unit": "mm", "source": "user"},
        },
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {"id": "outer", "kind": "primitive", "operation": "box",
             "parameters": {"size": ["width", "depth", "height"]}, "frame": "xy"},
            {"id": "tool", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": "radius", "height": "height + 2"}, "frame": "xy"},
            {"id": "body", "kind": "feature", "operation": "cut",
             "inputs": ["outer", "tool"]},
        ],
        "outputs": [{"id": "main", "node": "body", "format": ["step"]}],
    }
    normalized = app.validate_ir(ir)
    execution = app.execute_ir(normalized)
    metrics = app.shape_metrics(execution["shape"])
    assert execution["output_node"] == "body"
    assert metrics["valid_brep"] is True
    assert metrics["volume_mm3"] > 0
    assert metrics["bbox_mm"]["x"] == 40.0



@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_generic_ir_executor_builds_sketch_extrusion():
    ir = {
        "schema_version": "0.2",
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {"id": "profile", "kind": "sketch", "operation": "sketch",
             "parameters": {"geometry": [{"type": "rectangle", "width": 24, "height": 12}]},
             "frame": "xy"},
            {"id": "solid", "kind": "feature", "operation": "extrude",
             "inputs": ["profile"], "parameters": {"length": 6}},
        ],
        "outputs": [{"id": "main", "node": "solid"}],
    }
    execution = app.execute_ir(app.validate_ir(ir))
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["valid_brep"] is True
    assert metrics["bbox_mm"] == {"x": 24.0, "y": 12.0, "z": 6.0}



def test_ir_constraints_report_hard_and_soft_violations():
    ir = {
        "schema_version": "0.2",
        "parameters": {"wall": {"value": 0.8, "unit": "mm", "source": "user"}},
        "constraints": [
            {"id": "wall-hard", "type": "range", "parameter": "wall",
             "minimum_mm": 1.2, "hard": True},
            {"id": "wall-soft", "type": "process_rule", "parameter": "wall",
             "minimum_mm": 2.0, "hard": False},
        ],
    }
    report = app.solve_constraints(app.validate_ir(ir))
    assert report["valid"] is False
    assert report["hard_violation_count"] == 1
    assert {item["id"] for item in report["violations"]} == {"wall-hard", "wall-soft"}



def test_ir_selector_is_checked_against_registered_entities():
    ir = {
        "schema_version": "0.2",
        "nodes": [{
            "id": "body", "kind": "primitive", "operation": "box",
            "parameters": {"size": [20, 20, 20]},
        }, {
            "id": "edge", "kind": "feature", "operation": "chamfer",
            "inputs": ["body"],
            "parameters": {"radius": 1, "selector": {
                "entity": "missing", "topology": "face",
                "where": [{"normal": [0, 0, 1]}],
            }},
        }],
        "outputs": [{"id": "main", "node": "edge"}],
    }
    with pytest.raises(app.IRValidationError) as error:
        app.validate_ir(ir)
    assert any(issue["code"] == "selector_entity" for issue in error.value.issues)
