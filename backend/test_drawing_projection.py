"""Tests for the true-projection engineering drawing (iteration 3, Task 2)."""
from pathlib import Path
import json
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app

requires_kernel = pytest.mark.skipif(app.cq is None, reason="CadQuery required for STL generation")


def _make_box_artifact(model_id: str) -> Path:
    ir = {
        "schema_version": "0.2",
        "document": {"id": "box", "intent": "box 20x20x20", "units": "mm"},
        "units": "mm", "process": "fdm", "parameters": {},
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [{"id": "body", "kind": "primitive", "operation": "box",
                   "parameters": {"size": [20, 20, 20]}, "frame": "xy"}],
        "constraints": [],
        "outputs": [{"id": "main", "node": "body"}],
    }
    execution = app.execute_ir(app.validate_ir(ir))
    from ir_executor import shape_metrics

    metrics = shape_metrics(execution["shape"])
    model_dir = app.ARTIFACT_ROOT / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    app.cq.exporters.export(execution["shape"], str(model_dir / "model.stl"))
    (model_dir / "manifest.json").write_text(json.dumps({
        "title": "Projection Test <Box>",
        "units": "mm",
        "geometry_metrics": metrics,
    }), encoding="utf-8")
    return model_dir


@requires_kernel
def test_drawing_embeds_real_projection_views():
    model_id = "a" * 31 + "1"
    model_dir = _make_box_artifact(model_id)
    try:
        response = app.get_model_drawing(model_id)
        body = response.body.decode("utf-8")
        assert response.media_type == "image/svg+xml"
        assert "data:image/png;base64" in body, "drawing must embed real projected PNG views"
        assert body.count("data:image/png;base64") >= 3, "ISO/TOP/FRONT/RIGHT views expected"
        assert "20.0" in body, "real ENVELOPE numbers must stay in the title block"
        assert "&lt;Box&gt;" in body, "title must stay html-escaped"
        assert (model_dir / "drawing.svg").exists(), "rendered drawing must be cached"
    finally:
        shutil.rmtree(model_dir, ignore_errors=True)


@requires_kernel
def test_drawing_second_call_served_from_cache():
    model_id = "b" * 31 + "2"
    model_dir = _make_box_artifact(model_id)
    try:
        first = app.get_model_drawing(model_id)
        first_body = first.body

        import multiview_renderer

        def _explode(*args, **kwargs):
            raise AssertionError("renderer must not be called when cache exists")

        original = multiview_renderer.HeadlessCADRenderer
        multiview_renderer.HeadlessCADRenderer = _explode  # type: ignore[assignment]
        try:
            second = app.get_model_drawing(model_id)
        finally:
            multiview_renderer.HeadlessCADRenderer = original  # type: ignore[assignment]

        assert second.status_code == 200
        assert second.body == first_body, "cached drawing must be byte-identical"
    finally:
        shutil.rmtree(model_dir, ignore_errors=True)


@requires_kernel
def test_drawing_falls_back_without_stl():
    model_id = "c" * 31 + "3"
    model_dir = app.ARTIFACT_ROOT / model_id
    model_dir.mkdir(parents=True, exist_ok=True)
    (model_dir / "manifest.json").write_text(json.dumps({
        "title": "No STL Part",
        "units": "mm",
        "geometry_metrics": {"bbox_mm": {"x": 10.0, "y": 10.0, "z": 10.0}, "volume_mm3": 1000.0},
    }), encoding="utf-8")
    try:
        response = app.get_model_drawing(model_id)
        body = response.body.decode("utf-8")
        assert response.media_type == "image/svg+xml"
        assert "data:image/png;base64" not in body, "schematic fallback has no embedded views"
        assert "10.0 × 10.0" in body
        assert not (model_dir / "drawing.svg").exists(), "fallback must not poison the cache"
    finally:
        shutil.rmtree(model_dir, ignore_errors=True)


@requires_kernel
def test_drawing_render_failure_falls_back_and_does_not_500():
    model_id = "d" * 31 + "4"
    model_dir = _make_box_artifact(model_id)
    try:
        import multiview_renderer

        original = multiview_renderer.HeadlessCADRenderer

        class _BrokenRenderer:
            def render_stl_multiview(self, *args, **kwargs):
                raise RuntimeError("simulated renderer crash")

        multiview_renderer.HeadlessCADRenderer = _BrokenRenderer
        try:
            response = app.get_model_drawing(model_id)
        finally:
            multiview_renderer.HeadlessCADRenderer = original
        body = response.body.decode("utf-8")
        assert response.media_type == "image/svg+xml"
        assert "data:image/png;base64" not in body, "renderer crash must fall back to the schematic"
    finally:
        shutil.rmtree(model_dir, ignore_errors=True)
