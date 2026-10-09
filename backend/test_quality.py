"""Regression tests for the text-to-CAD interpretation and quality contract.

These tests deliberately avoid starting CadQuery. Geometry/export smoke tests run in
the Docker image where the CAD kernel is available.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app
import ir_executor


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



def test_geometry_repair_bounds_edge_features():
    ir = {
        "schema_version": "0.2",
        "parameters": {
            "width": {"value": 40, "unit": "mm"},
            "depth": {"value": 30, "unit": "mm"},
            "height": {"value": 20, "unit": "mm"},
        },
        "nodes": [{
            "id": "body", "kind": "primitive", "operation": "box",
            "parameters": {"size": ["width", "depth", "height"]},
        }, {
            "id": "edge", "kind": "feature", "operation": "fillet",
            "inputs": ["body"], "parameters": {"radius": 25},
        }],
        "outputs": [{"id": "main", "node": "edge"}],
    }
    patches = app._geometry_repair_patches(ir, "fillet radius is too large")
    assert patches[0]["op"] == "replace_node_parameter"
    assert patches[0]["value"] == 2.5


def test_ir_repair_returns_and_applies_explicit_patch():
    ir = {
        "schema_version": "0.2",
        "parameters": {"wall": {"value": 0.8, "unit": "mm", "source": "user"}},
        "constraints": [{
            "id": "wall-hard", "type": "range", "parameter": "wall",
            "minimum_mm": 1.2, "hard": True,
        }],
    }
    normalized = app.validate_ir(ir)
    report = app.solve_constraints(normalized)
    patches = app.suggest_repairs(normalized, report)
    assert patches[0]["op"] == "set_parameter"
    repaired = app.apply_patches(normalized, patches)
    assert repaired["parameters"]["wall"]["value"] == 1.2
    assert app.solve_constraints(repaired)["valid"] is True


def test_generation_strategy_defaults_to_ir_and_accepts_compatibility_modes():
    default_request = app.GenerateRequest(prompt="a 20 mm block")
    ir_request = app.GenerateRequest(
        prompt="a 20 mm block",
        mode="advanced",
        generation_strategy="auto",
    )
    assert default_request.generation_strategy == "ir"
    assert ir_request.generation_strategy == "auto"


def test_llm_ir_normalizer_fills_generic_contract():
    raw = {
        "schema_version": "0.1",
        "parameters": {"width": 20, "height": 8},
        "nodes": [{
            "id": "body",
            "operation": "rectangular_prism",
            "parameters": {"size": [20, 12, 8]},
            "frame": "xy",
        }],
    }
    normalized = app._normalize_ir_draft(raw, "a rectangular part", "fdm", "mm")
    assert normalized["schema_version"] == "0.2"
    assert normalized["nodes"][0]["operation"] == "box"
    assert normalized["datums"][0]["id"] == "xy"
    assert normalized["outputs"][0]["node"] == "body"
    assert app.validate_ir(normalized)["schema_version"] == "0.2"


def test_deterministic_primitive_planner_is_family_independent(monkeypatch):
    params_title, params, _ = app.parse_prompt_detailed("a regular octagon 80 mm wide and 20 mm tall")
    ir = app._deterministic_ir_plan("a regular octagon 80 mm wide and 20 mm tall", "fdm", "mm", params)
    assert ir["nodes"][0]["operation"] == "regular_polygon"
    assert ir["nodes"][0]["parameters"]["sides"] == 8
    assert app.validate_ir(ir)["outputs"][0]["node"] == "body"


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_generic_ir_executor_builds_regular_polygon():
    ir = {
        "schema_version": "0.2",
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [{
            "id": "body", "kind": "primitive", "operation": "regular_polygon",
            "parameters": {"sides": 7, "width": 60, "depth": 40, "height": 12},
            "frame": "xy",
        }],
        "outputs": [{"id": "main", "node": "body"}],
    }
    execution = app.execute_ir(app.validate_ir(ir))
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["valid_brep"] is True
    assert metrics["bbox_mm"] == {"x": 60.0, "y": 40.0, "z": 12.0}


def test_frontend_requests_ir_without_family_prompt_injection():
    index_source = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")
    assert "generation_strategy: 'ir'" in index_source
    assert "Parsed CAD parameters: " not in index_source
    assert "Baseline CAD parameters: " not in index_source


def test_cache_key_separates_generation_strategies():
    legacy = app.GenerateRequest(prompt="a 20 mm block", generation_strategy="legacy")
    ir = app.GenerateRequest(prompt="a 20 mm block", generation_strategy="ir")
    assert app._cache_key(legacy) != app._cache_key(ir)


def test_cache_key_separates_mold_pull_direction():
    plus_z = app.GenerateRequest(prompt="a mold insert", process="injection", mold_pull_direction=[0, 0, 1])
    plus_x = app.GenerateRequest(prompt="a mold insert", process="injection", mold_pull_direction=[1, 0, 0])
    assert app._cache_key(plus_z) != app._cache_key(plus_x)


def test_ir_validator_accepts_path_and_pattern_features():
    ir = {
        "schema_version": "0.2",
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {"id": "profile", "kind": "sketch", "operation": "sketch",
             "parameters": {"geometry": [{"type": "circle", "radius": 2}]}, "frame": "xy"},
            {"id": "path", "kind": "sketch", "operation": "sketch",
             "parameters": {"geometry": [{"type": "polyline", "points": [[0, 0], [20, 0], [20, 20]]}]}, "frame": "xy"},
            {"id": "swept", "kind": "feature", "operation": "sweep",
             "inputs": ["profile", "path"]},
            {"id": "repeated", "kind": "feature", "operation": "linear_pattern",
             "inputs": ["swept"], "parameters": {"count": 2, "spacing": [30, 0, 0]}},
        ],
        "outputs": [{"id": "main", "node": "repeated"}],
    }
    normalized = app.validate_ir(ir)
    assert [node["operation"] for node in normalized["nodes"]][-2:] == ["sweep", "linear_pattern"]


def test_ir_fallback_error_codes_are_stable():
    assert app._ir_error_code(RuntimeError("operation 'sweep' is not implemented")) == "unsupported_operation"
    assert app._ir_error_code(RuntimeError("CadQuery is not installed")) == "cadquery_unavailable"
    assert app._ir_error_code(ValueError("geometry validation failed")) == "kernel_validation"


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_generic_ir_selector_applies_to_edge_feature():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {"id": "body", "kind": "primitive", "operation": "box",
             "parameters": {"size": [30, 20, 10]}},
            {"id": "edge_treatment", "kind": "feature", "operation": "fillet",
             "inputs": ["body"], "parameters": {
                 "radius": 1,
                 "selector": {"entity": "body", "topology": "edge", "where": [{"index": 0}]},
             }},
        ],
        "outputs": [{"id": "main", "node": "edge_treatment"}],
    }
    execution = app.execute_ir(app.validate_ir(ir))
    assert app.shape_metrics(execution["shape"])["valid_brep"] is True


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_generic_ir_executes_sphere_primitive():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {"id": "ball", "kind": "primitive", "operation": "sphere",
             "parameters": {"radius": 15}},
        ],
        "outputs": [{"id": "main", "node": "ball"}],
    }
    execution = app.execute_ir(app.validate_ir(ir))
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["valid_brep"] is True
    assert metrics["solid_count"] == 1
    assert metrics["volume_mm3"] > 0


def test_face_level_dfm_records_normals_and_areas():
    class Vector:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    class Face:
        def __init__(self, area, normal, center):
            self._area, self._normal, self._center = area, normal, center

        def Area(self):
            return self._area

        def normalAt(self):
            return Vector(*self._normal)

        def Center(self):
            return Vector(*self._center)

    class Solid:
        def Faces(self):
            return [
                Face(100, (0, 0, 1), (0, 0, 10)),
                Face(100, (0, 0, -1), (0, 0, 0)),
            ]

    class Shape:
        def val(self):
            return Solid()

    report = app._face_level_dfm(Shape(), "fdm")
    assert report["face_count"] == 2
    assert report["min_face_area_mm2"] == 100.0
    assert report["downward_face_count"] == 1
    assert report["wall_thickness_proxy_mm"] == 10.0
    assert report["wall_thickness_proxy_status"] == "pass"
    assert report["wall_thickness_measurement"]["method"] == "opposing_face_center_proxy"
    assert report["wall_thickness_analysis"]["normal_ray_sampling"] in {"available", "unavailable", "no_hit"}
    assert report["wall_thickness_analysis"]["normal_ray_sample_count"] >= 0
    assert report["overhang_status"] == "warning"
    assert report["clearance_status"] == "unknown"


def test_injection_draft_measurement_reports_face_level_warning():
    class Vector:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    class Face:
        def Area(self):
            return 25.0

        def normalAt(self):
            return Vector(1, 0, 0)

        def Center(self):
            return Vector(0, 0, 0)

    class Solid:
        def Faces(self):
            return [Face()]

    class Shape:
        def val(self):
            return Solid()

    report = app._face_level_dfm(Shape(), "injection")
    assert report["draft_status"] == "warning"
    assert report["draft_measurements"][0]["status"] == "warning"
    assert report["draft_pull_direction"] == [0.0, 0.0, 1.0]
    assert report["draft_pull_direction_source"] == "default"
    assert report["clearance_status"] == "unknown"

    configured = app._face_level_dfm(Shape(), "injection", [0, 1, 0])
    assert configured["draft_pull_direction"] == [0.0, 1.0, 0.0]
    assert configured["draft_pull_direction_source"] == "request"

    invalid = app._face_level_dfm(Shape(), "injection", [0, 0, 0])
    assert invalid["draft_pull_direction"] == [0.0, 0.0, 1.0]
    assert invalid["draft_pull_direction_source"] == "invalid_defaulted"
    assert invalid["draft_status"] == "warning"


def test_shape_distance_prefers_kernel_method():
    class Shape:
        def __init__(self, distance):
            self.distance_value = distance

        def distToShape(self, other):
            return (self.distance_value, None, None)

    distance, method = app._shape_distance(Shape(4.5), Shape(4.5))
    assert distance == 4.5
    assert method == "brep_shape_distance"


def test_selector_returns_match_metadata_without_kernel():
    class Collection:
        def __init__(self, values):
            self._values = values

        def vals(self):
            return self._values

    class Shape:
        def __init__(self):
            self._edges = [object(), object(), object()]

        def edges(self):
            return Collection(self._edges)

        def newObject(self, selected):
            return selected

    metadata = {}
    result = ir_executor._topology_selection(
        Shape(),
        {"topology": "edge", "where": [{"index": 1}]},
        "edge",
        metadata,
    )
    assert len(result) == 1
    assert metadata["matched_indices"] == [1]
    assert metadata["matched_count"] == 1


def test_selector_mapping_requires_final_topology_identity():
    class Entity:
        def __init__(self, key):
            self.key = key

        def hashCode(self):
            return self.key

    class Collection:
        def __init__(self, values):
            self._values = values

        def vals(self):
            return self._values

    class Shape:
        def __init__(self, faces):
            self._faces = faces

        def faces(self):
            return Collection(self._faces)

    selected = Entity(11)
    metadata = {
        "target_topology": "face",
        "_selected_entities": [selected],
    }
    ir_executor._finalize_selector_metadata(metadata, Shape([Entity(10), selected]))
    assert metadata["mapping_status"] == "final_output"
    assert metadata["output_indices"] == [1]

    missing = {"target_topology": "face", "_selected_entities": [selected]}
    ir_executor._finalize_selector_metadata(missing, Shape([Entity(10)]))
    assert missing["mapping_status"] == "unmapped"
    assert missing["output_indices"] == []



def test_clearance_classification_distinguishes_interference_contact_and_gap():
    interference = app._classify_clearance(0.0, 0.3, 0.1)
    assert interference["status"] == "interference"
    assert interference["interference"] is True

    contact = app._classify_clearance(0.05, 0.3, 0.1)
    assert contact["status"] == "contact"
    assert contact["state"] == "contact"

    insufficient = app._classify_clearance(0.2, 0.3, 0.1)
    assert insufficient["status"] == "warning"
    assert insufficient["state"] == "insufficient_clearance"

    clear = app._classify_clearance(0.4, 0.3, 0.1)
    assert clear["status"] == "pass"
    assert clear["state"] == "clear"

    touching = app._classify_clearance(0.0, 0.3, 0.1, intersection_volume_mm3=0.0)
    assert touching["status"] == "contact"
    overlapping = app._classify_clearance(0.0, 0.3, 0.1, intersection_volume_mm3=12.0)
    assert overlapping["status"] == "interference"


def test_ir_validation_accepts_multiple_semantic_outputs():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {"id": "left", "kind": "primitive", "operation": "box",
             "parameters": {"size": [10, 10, 10]}},
            {"id": "right", "kind": "primitive", "operation": "box",
             "parameters": {"size": [8, 8, 8]}},
        ],
        "outputs": [
            {"id": "left_output", "node": "left", "format": ["step"]},
            {"id": "right_output", "node": "right", "format": ["step"]},
        ],
    }
    normalized = app.validate_ir(ir)
    assert [item["node"] for item in normalized["outputs"]] == ["left", "right"]


def test_triangle_prompt_compiles_to_generic_polygon_prism():
    title, params, provenance = app.parse_prompt_detailed(
        "三角形方块，底面 60 x 40 mm，厚度 30 mm",
    )
    assert title == "Parametric polygon prism"
    assert params.kind == "polygon_prism"
    assert (params.width, params.depth, params.height) == (60.0, 40.0, 30.0)
    assert params.profile_points == [[-30.0, -20.0], [30.0, -20.0], [0.0, 20.0]]
    assert provenance["fields"]["profile_points"]["status"] == "derived"
    ir = app.build_design_ir(
        "三角形方块，底面 60 x 40 mm，厚度 30 mm",
        params,
        "standard",
        False,
        provenance["assumptions"],
        provenance,
    )
    assert ir["nodes"][0]["operation"] == "polygon_prism"
    assert len(ir["nodes"][0]["parameters"]["points"]) == 3
    assert app.validate_ir(ir)["nodes"][0]["operation"] == "polygon_prism"


def test_regular_octagon_prompt_uses_eight_sided_profile():
    title, params, provenance = app.parse_prompt_detailed("正八边形")
    assert title == "Parametric polygon prism"
    assert params.kind == "polygon_prism"
    assert (params.width, params.depth, params.height) == (120.0, 120.0, 42.0)
    assert len(params.profile_points) == 8
    assert all(len(point) == 2 for point in params.profile_points)
    assert max(point[0] for point in params.profile_points) - min(point[0] for point in params.profile_points) == 120.0
    assert max(point[1] for point in params.profile_points) - min(point[1] for point in params.profile_points) == 120.0
    assert params.chamfer == 0.0
    ir = app.build_design_ir("正八边形", params, "standard", False, provenance["assumptions"], provenance)
    assert ir["nodes"][0]["operation"] == "polygon_prism"
    assert len(ir["nodes"][0]["parameters"]["points"]) == 8
    assert app.validate_ir(ir)["nodes"][0]["operation"] == "polygon_prism"


def test_triangle_without_dimensions_stays_generic_polygon_prism():
    title, params, provenance = app.parse_prompt_detailed("一个三角形方块")
    assert title == "Parametric polygon prism"
    assert params.kind == "polygon_prism"
    assert params.profile_points == [[-60.0, -40.2], [60.0, -40.2], [0.0, 40.2]]
    assert params.height == 42.0
    assert provenance["fields"]["profile_points"]["status"] == "derived"


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_deterministic_ir_builds_torus():
    _, params, _ = app.parse_prompt_detailed("a torus ring 60 mm")
    ir = app._deterministic_ir_plan("a torus ring 60 mm", "fdm", "mm", params)
    assert ir["nodes"][0]["operation"] == "torus"
    execution = app.execute_ir(ir)
    assert execution["shape"] is not None
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["solid_count"] == 1


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_deterministic_ir_builds_hollow_cylinder():
    _, params, _ = app.parse_prompt_detailed("a hollow cylinder 40 mm and height 50 mm")
    ir = app._deterministic_ir_plan("a hollow cylinder 40 mm and height 50 mm", "fdm", "mm", params)
    ops = [node["operation"] for node in ir["nodes"]]
    assert "cut" in ops
    execution = app.execute_ir(ir)
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["solid_count"] == 1
    assert metrics["face_count"] >= 4


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_ir_executor_supports_inline_position_transform():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "box1",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [20, 20, 10], "position": [10, 0, 5]},
            }
        ],
        "outputs": [{"id": "main", "node": "box1", "format": ["step"]}],
    }
    execution = app.execute_ir(ir)
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["bbox_mm"]["z"] == 10.0


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_ir_executor_supports_single_input_cut_feature():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "plate",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [50, 50, 5]},
            },
            {
                "id": "center_hole",
                "kind": "feature",
                "operation": "cut",
                "inputs": ["plate"],
                "parameters": {"diameter": 22, "depth": 5},
            },
        ],
        "outputs": [{"id": "main", "node": "center_hole", "format": ["step"]}],
    }
    execution = app.execute_ir(ir)
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["solid_count"] == 1
    assert metrics["face_count"] >= 7


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_ir_executor_handles_cut_with_single_input_without_params():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "plate",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [50, 50, 5]},
            },
            {
                "id": "cut_nop",
                "kind": "feature",
                "operation": "cut",
                "inputs": ["plate"],
                "parameters": {},
            },
        ],
        "outputs": [{"id": "main", "node": "cut_nop", "format": ["step"]}],
    }
    execution = app.execute_ir(ir)
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["solid_count"] == 1



@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_ir_executor_supports_xyz_translate_and_named_axis_rotate():
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "arm",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 3, "height": 10},
            },
            {
                "id": "arm_rot",
                "kind": "feature",
                "operation": "rotate",
                "inputs": ["arm"],
                "parameters": {"axis": "x", "angle": 90},
            },
            {
                "id": "arm_placed",
                "kind": "feature",
                "operation": "translate",
                "inputs": ["arm_rot"],
                "parameters": {"x": 5, "y": 10, "z": 15},
            },
        ],
        "outputs": [{"id": "main", "node": "arm_placed", "format": ["step"]}],
    }
    execution = app.execute_ir(ir)
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["solid_count"] == 1
    assert metrics["bbox_mm"]["z"] == 6.0  # diameter of cylinder


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_deterministic_ir_builds_cone():
    _, params, _ = app.parse_prompt_detailed("a cone 30 mm diameter and 40 mm height")
    ir = app._deterministic_ir_plan("a cone 30 mm diameter and 40 mm height", "fdm", "mm", params)
    assert ir["nodes"][0]["operation"] == "cone"
    execution = app.execute_ir(ir)
    assert execution["shape"] is not None
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["solid_count"] == 1
    assert metrics["face_count"] >= 2


def test_ir_expressions_with_numbers_and_parentheses():
    doc = {
        "schema_version": "0.2",
        "parameters": {
            "width": {"value": 50.0},
            "half_width": {"value": 25.0, "expression": "0.5 * width"},
            "padded": {"value": 30.0, "expression": "(width + 10) / 2"},
        },
        "nodes": [
            {
                "id": "box1",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"width": "width", "depth": "half_width", "height": "padded"},
            }
        ],
        "outputs": [{"id": "main", "node": "box1", "format": ["step"]}],
    }
    validated = app.validate_ir(doc)
    assert validated["parameters"]["half_width"]["expression"] == "0.5 * width"
    assert validated["parameters"]["padded"]["expression"] == "(width + 10) / 2"


@pytest.mark.skipif(app.cq is None, reason="CadQuery is available in the Docker quality environment")
def test_agent_modeling_loop_convergence(tmp_path):
    from agent_loop import run_agent_modeling_loop
    initial_ir = {
        "schema_version": "0.2",
        "document": {"id": "test-box", "intent": "box 30x30x10 mm", "units": "mm"},
        "nodes": [
            {"id": "box", "kind": "primitive", "operation": "box", "parameters": {"size": [30, 30, 10]}}
        ],
        "outputs": [{"id": "main", "node": "box", "format": ["step", "stl", "glb"]}],
    }
    result = run_agent_modeling_loop(
        initial_ir,
        "box 30x30x10 mm with a 10 mm through hole",
        "fdm",
        tmp_path,
        max_rounds=2,
    )
    assert result["total_rounds"] >= 1
    assert result["converged"] is True
    assert result["final_score"] >= 8.8
    assert len(result["history"]) >= 1


def test_apply_patches_advanced_primitives():
    from ir_repair import apply_patches

    base_ir = {
        "schema_version": "0.2",
        "parameters": {"width": {"value": 40.0, "unit": "mm"}},
        "nodes": [
            {
                "id": "base_part",
                "kind": "primitive",
                "operation": "cylinder",
                "inputs": [],
                "parameters": {"radius": 30.0, "height": 10.0},
            }
        ],
        "outputs": [{"id": "primary", "node": "base_part", "format": ["step", "stl", "glb"]}],
    }

    # 1. scale_parameter
    p_scale = [{"op": "scale_parameter", "parameter": "width", "factor": 1.5}]
    ir_scaled = apply_patches(base_ir, p_scale)
    assert ir_scaled["parameters"]["width"]["value"] == 60.0

    # 2. add_hole_pattern
    p_pattern = [{
        "op": "add_hole_pattern",
        "target_node": "base_part",
        "count": 4,
        "circle_radius": 20.0,
        "hole_diameter": 4.0,
        "depth": 50.0,
    }]
    ir_pattern = apply_patches(base_ir, p_pattern)
    pattern_cut = next(n for n in ir_pattern["nodes"] if n["id"] == "cut_hole_pattern_1")
    assert pattern_cut["operation"] == "cut"
    assert len(pattern_cut["inputs"]) == 5  # base_part + 4 cutter cylinders
    assert ir_pattern["outputs"][0]["node"] == "cut_hole_pattern_1"

    # 3. add_chamfer
    p_chamfer = [{"op": "add_chamfer", "target_node": "base_part", "distance": 1.5}]
    ir_chamfer = apply_patches(base_ir, p_chamfer)
    chamfer_node = next(n for n in ir_chamfer["nodes"] if n["operation"] == "chamfer")
    assert chamfer_node["parameters"]["distance"] == 1.5
    assert ir_chamfer["outputs"][0]["node"] == chamfer_node["id"]

    # 4. add_fillet
    p_fillet = [{"op": "add_fillet", "target_node": "base_part", "radius": 2.0}]
    ir_fillet = apply_patches(base_ir, p_fillet)
    fillet_node = next(n for n in ir_fillet["nodes"] if n["operation"] == "fillet")
    assert fillet_node["parameters"]["radius"] == 2.0
    assert ir_fillet["outputs"][0]["node"] == fillet_node["id"]

    # 5. shell_hollow
    p_shell = [{"op": "shell_hollow", "target_node": "base_part", "thickness": 2.5}]
    ir_shell = apply_patches(base_ir, p_shell)
    shell_node = next(n for n in ir_shell["nodes"] if n["operation"] == "shell")
    assert shell_node["parameters"]["thickness"] == 2.5
    assert ir_shell["outputs"][0]["node"] == shell_node["id"]


def test_heuristic_fallback_critique_pattern_recognition():
    from agent_loop import _heuristic_fallback_critique

    sample_ir = {
        "schema_version": "0.2",
        "nodes": [
            {"id": "flange", "kind": "primitive", "operation": "cylinder", "parameters": {"radius": 35.0, "height": 10.0}}
        ],
        "outputs": [{"id": "primary", "node": "flange", "format": ["step", "stl", "glb"]}],
    }

    # "4 mounting holes"
    c1 = _heuristic_fallback_critique("round flange with 4 mounting holes", sample_ir, 0)
    assert any(p["op"] == "add_hole_pattern" for p in c1["proposed_patches"])
    patch1 = next(p for p in c1["proposed_patches"] if p["op"] == "add_hole_pattern")
    assert patch1["count"] == 4

    # "6 bolt holes"
    c2 = _heuristic_fallback_critique("flange plate with 6 bolt holes", sample_ir, 0)
    patch2 = next(p for p in c2["proposed_patches"] if p["op"] == "add_hole_pattern")
    assert patch2["count"] == 6

    # "four holes on 40mm circle"
    c3 = _heuristic_fallback_critique("cylinder base with four holes on 40mm circle", sample_ir, 0)
    patch3 = next(p for p in c3["proposed_patches"] if p["op"] == "add_hole_pattern")
    assert patch3["count"] == 4
    assert patch3["circle_radius"] == 20.0

    # "bolt circle"
    c4 = _heuristic_fallback_critique("adapter with bolt circle", sample_ir, 0)
    assert any(p["op"] == "add_hole_pattern" for p in c4["proposed_patches"])

    # Edge treatment: "chamfer 2mm"
    c5 = _heuristic_fallback_critique("block with 2mm chamfer", sample_ir, 0)
    patch5 = next(p for p in c5["proposed_patches"] if p["op"] == "add_chamfer")
    assert patch5["distance"] == 2.0

    # Hollow: "hollow shell with 2mm wall"
    c6 = _heuristic_fallback_critique("hollow shell box with 2mm wall", sample_ir, 0)
    patch6 = next(p for p in c6["proposed_patches"] if p["op"] == "shell_hollow")
    assert patch6["thickness"] == 2.0


def test_render_annotated_composite_output(tmp_path):
    from PIL import Image
    from multiview_renderer import HeadlessCADRenderer

    renderer = HeadlessCADRenderer(resolution=256)
    dummy_view = tmp_path / "top.png"
    Image.new("RGB", (256, 256), color=(220, 220, 220)).save(dummy_view)
    view_paths = {"top": dummy_view, "iso": dummy_view, "front": dummy_view, "right": dummy_view}

    anno_out = tmp_path / "annotated_composite.png"
    discrepancies = [
        {"severity": "high", "feature": "hole_pattern", "issue": "Missing 4-hole pattern on top surface"},
        {"severity": "medium", "feature": "edge_treatment", "issue": "Missing 1mm chamfer on top edge"}
    ]
    res_path = renderer.render_annotated_composite(view_paths, discrepancies, anno_out)
    assert res_path.exists()
    assert res_path.stat().st_size > 1000






