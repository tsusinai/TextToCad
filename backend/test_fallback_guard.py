"""Regression guards for the deterministic planner token matching and
artifact-endpoint robustness (quality hardening iteration 2026-10-24)."""
from pathlib import Path
import json
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app
from fastapi import HTTPException


def _params(prompt="a block 20 mm"):
    _, params, _ = app.parse_prompt_detailed(prompt)
    return params


def test_freeform_text_with_gon_substring_raises():
    # "gon" inside "ergonomic" must not satisfy the primitive guard.
    with pytest.raises(RuntimeError):
        app._deterministic_ir_plan(
            "an ergonomic desk organizer for pens", "fdm", "mm", _params("a desk organizer 120 mm")
        )


def test_ring_in_bring_not_matched():
    with pytest.raises(RuntimeError):
        app._deterministic_ir_plan("bring me a nice chair", "fdm", "mm", _params("a chair 100 mm"))


def test_hexagon_prompt_still_deterministic():
    ir = app._deterministic_ir_plan(
        "a hexagon prism 30 mm wide", "fdm", "mm", _params("a hexagon prism 30 mm wide")
    )
    assert ir["provenance"]["planner"] == "deterministic_primitive"
    assert ir["nodes"][0]["operation"] == "regular_polygon"
    assert ir["nodes"][0]["parameters"]["sides"] == 6


def test_chinese_polygon_prompt_still_deterministic():
    ir = app._deterministic_ir_plan("一个五边形棱柱", "fdm", "mm", _params("一个五边形棱柱"))
    assert ir["provenance"]["planner"] == "deterministic_primitive"
    assert ir["nodes"][0]["operation"] == "regular_polygon"
    assert ir["nodes"][0]["parameters"]["sides"] == 5


def test_plural_primitive_tokens_still_match():
    ir = app._deterministic_ir_plan("two blocks 20 mm", "fdm", "mm", _params("two blocks 20 mm"))
    assert ir["nodes"][0]["operation"] == "box"


def test_balloon_does_not_become_sphere():
    # "ball" inside "balloon" used to win the sphere branch over the explicit box.
    ir = app._deterministic_ir_plan(
        "a balloon shaped box 30 mm", "fdm", "mm", _params("a box 30 mm")
    )
    assert ir["nodes"][0]["operation"] == "box"


def _write_manifest(model_id: str, content: str):
    target_dir = app.ARTIFACT_ROOT / model_id
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "manifest.json").write_text(content, encoding="utf-8")
    return target_dir


def test_drawing_endpoint_bad_manifest_returns_4xx():
    model_id = "c" * 32
    target_dir = _write_manifest(model_id, "{not-valid-json")
    try:
        with pytest.raises(HTTPException) as exc:
            app.get_model_drawing(model_id)
        assert exc.value.status_code in (404, 422)
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_measure_endpoint_bad_manifest_returns_4xx():
    model_id = "d" * 32
    target_dir = _write_manifest(model_id, "{not-valid-json")
    try:
        with pytest.raises(HTTPException) as exc:
            app.measure_model(model_id)
        assert exc.value.status_code in (404, 422)
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_measure_endpoint_null_metric_fields_return_defaults():
    model_id = "e" * 32
    target_dir = _write_manifest(
        model_id,
        json.dumps({"title": "t", "units": "mm", "geometry_metrics": None, "metrics": None}),
    )
    try:
        data = app.measure_model(model_id)
        assert data["dimensions"] == {"width": 0.0, "depth": 0.0, "height": 0.0}
        assert data["bbox_mm"] == {}
        assert data["valid_brep"] is True
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


def test_normalize_ir_draft_preserves_v03_assembly_documents():
    payload = {
        "schema_version": "0.3",
        "document": {"id": "asm", "intent": "assembly", "units": "mm"},
        "units": "mm",
        "components": [{"id": "c1", "nodes": [], "outputs": []}],
        "instances": [{"id": "i1", "component": "c1"}],
    }
    normalized = app._normalize_ir_draft(payload, "assembly", "fdm", "mm")
    assert normalized["schema_version"] == "0.3"


def test_normalize_ir_draft_still_downgrades_bare_v03():
    payload = {
        "schema_version": "0.3",
        "document": {"id": "bare", "intent": "box", "units": "mm"},
        "units": "mm",
        "nodes": [
            {"id": "body", "kind": "primitive", "operation": "box",
             "parameters": {"size": [10, 10, 10]}, "frame": "xy"}
        ],
        "outputs": [{"id": "main", "node": "body"}],
    }
    normalized = app._normalize_ir_draft(payload, "box", "fdm", "mm")
    assert normalized["schema_version"] == "0.2"
