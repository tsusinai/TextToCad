"""Tests for the persist option of POST /v1/ir/compile (parametric re-compile)."""
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app

requires_kernel = pytest.mark.skipif(app.cq is None, reason="CadQuery required for compile persist")


def _flange_ir() -> dict:
    return {
        "schema_version": "0.2",
        "document": {"id": "flange", "intent": "flange with four mounting holes", "units": "mm"},
        "units": "mm", "process": "fdm", "parameters": {}, "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {"id": "body", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": 30, "height": 10}, "frame": "xy"},
            {"id": "h1", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": 4, "height": 14, "position": [16, 0, -2]}},
            {"id": "h2", "kind": "primitive", "operation": "cylinder",
             "parameters": {"radius": 4, "height": 14, "position": [-16, 0, -2]}},
            {"id": "drilled", "kind": "feature", "operation": "cut",
             "inputs": ["body", "h1", "h2"], "parameters": {}},
        ],
        "constraints": [],
        "outputs": [{"id": "main", "node": "drilled"}],
    }


@requires_kernel
def test_compile_persist_writes_glb_and_manifest():
    request = app.IRCompileRequest(ir=_flange_ir(), persist=True)
    response = app.compile_ir_endpoint(request)
    model_id = response["model_id"]
    assert model_id and len(model_id) == 32
    assert response["artifacts"]["glb"].startswith(f"/v1/models/{model_id}/download?format=glb")

    target_dir = app.ARTIFACT_ROOT / model_id
    try:
        glb_path = target_dir / "model.glb"
        assert glb_path.exists() and glb_path.stat().st_size > 0
        assert glb_path.read_bytes()[:4] == b"glTF"
        assert (target_dir / "model.stl").exists(), "persist must export STL for true-projection drawings"
        manifest_path = target_dir / "manifest.json"
        assert manifest_path.exists()
        # The persisted manifest must keep /v1/models/{id}/measure working.
        measured = app.measure_model(model_id)
        assert measured["solid_count"] == 1
        assert measured["dimensions"]["width"] == pytest.approx(60.0, abs=0.05)
        # The drawing endpoint must produce true projections from the STL.
        drawing = app.get_model_drawing(model_id)
        assert b"data:image/png;base64" in drawing.body
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)


@requires_kernel
def test_compile_without_persist_leaves_no_artifacts():
    response = app.compile_ir_endpoint(app.IRCompileRequest(ir=_flange_ir()))
    assert response["model_id"] is None
    assert response["artifacts"] is None
    assert response["valid"] is True


@requires_kernel
def test_compile_persist_glb_is_downloadable():
    from fastapi.testclient import TestClient

    request = app.IRCompileRequest(ir=_flange_ir(), persist=True)
    response = app.compile_ir_endpoint(request)
    model_id = response["model_id"]
    target_dir = app.ARTIFACT_ROOT / model_id
    client = TestClient(app.app)
    try:
        download = client.get(f"/v1/models/{model_id}/download?format=glb")
        assert download.status_code == 200
        assert download.content[:4] == b"glTF"
    finally:
        shutil.rmtree(target_dir, ignore_errors=True)
