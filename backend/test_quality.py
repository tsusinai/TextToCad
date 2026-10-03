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
    request = app.GenerateRequest(prompt="a 40 mm block", include_steps=True)
    assert request.include_steps is True


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
