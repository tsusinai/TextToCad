import logging
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import app
from ir_validate import validate_ir


def test_system_prompt_hierarchical_assembly_decomposition_and_scale():
    """Verify that _llm_ir_json defines the Hierarchical Assembly Decomposition CoT and Canonical Desktop Scale Normalization."""
    # Temporarily set an API key to inspect system prompt construction
    old_key = app.LLM_API_KEY
    try:
        app.LLM_API_KEY = "test-key"
        # We can extract the schema and system prompt from _llm_ir_json by inspecting how they are built
        # or by checking retrieve_feature_recipes & the prompt text patterns.
        # Let's inspect the system prompt in _llm_ir_json by mocking urllib.request.urlopen.
        captured_body = {}

        class DummyResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            @property
            def headers(self):
                return {}
            def read(self, *args):
                return b'{"choices": [{"message": {"content": "{\\"schema_version\\": \\"0.2\\"}"}}]}'

        def dummy_urlopen(req, timeout=None):
            import json
            captured_body.update(json.loads(req.data.decode("utf-8")))
            return DummyResponse()

        import urllib.request
        orig_urlopen = urllib.request.urlopen
        urllib.request.urlopen = dummy_urlopen
        try:
            app._llm_ir_json("一个简易坦克模型", "fdm", "mm")
        finally:
            urllib.request.urlopen = orig_urlopen

        messages = captured_body.get("messages", [])
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")

        # Check Hierarchical Assembly Decomposition (CoT)
        assert "Hierarchical Assembly Decomposition" in system_msg
        assert "Base/Chassis/Hull" in system_msg
        assert "turret" in system_msg
        assert "barrel" in system_msg
        assert '"mount": {"target": "hull", "face": ">Z"}' in system_msg
        assert '"mount": {"target": "turret", "face": ">Y", "orientation": "forward"}' in system_msg
        assert '"mount": {"target": "hull", "face": "<X"}' in system_msg
        assert '"mount": {"target": "hull", "face": ">X"}' in system_msg

        # Check Canonical Desktop Scale Normalization
        assert "Canonical Desktop Scale Normalization" in system_msg
        assert "80 to 140 mm" in system_msg
        assert "50 to 80 mm" in system_msg
        assert "30 to 60 mm" in system_msg
        assert "FORBID 10x dimension blowups" in system_msg
        assert "10 mm to 200 mm" in system_msg

    finally:
        app.LLM_API_KEY = old_key


def test_canonical_desktop_scale_normalization_hallucinated_tank(caplog):
    """When user prompt has no explicit large dimension, but LLM emitted 1200 mm, scale down by 0.1 to canonical 120 mm."""
    raw_tank_ir = {
        "schema_version": "0.2",
        "document": {"id": "tank-model", "units": "mm"},
        "parameters": {
            "hull_length": {"value": 1200.0, "unit": "mm", "role": "dimension"},
            "hull_width": {"value": 600.0, "unit": "mm", "role": "dimension"},
            "hull_height": {"value": 400.0, "unit": "mm", "role": "dimension"},
            "turret_radius": {"value": 200.0, "unit": "mm", "role": "dimension"},
            "turret_height": {"value": 150.0, "unit": "mm", "role": "dimension"},
            "barrel_radius": {"value": 30.0, "unit": "mm", "role": "dimension"},
            "barrel_length": {"value": 400.0, "unit": "mm", "role": "dimension"},
            "track_width": {"value": 150.0, "unit": "mm", "role": "dimension"},
            "track_length": {"value": 1100.0, "unit": "mm", "role": "dimension"},
            "track_height": {"value": 300.0, "unit": "mm", "role": "dimension"},
        },
        "nodes": [
            {
                "id": "hull",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": ["hull_length", "hull_width", "hull_height"]},
            },
            {
                "id": "turret",
                "kind": "primitive",
                "operation": "cylinder",
                "mount": {"target": "hull", "face": ">Z"},
                "parameters": {"radius": "turret_radius", "height": "turret_height"},
            },
            {
                "id": "barrel",
                "kind": "primitive",
                "operation": "cylinder",
                "mount": {"target": "turret", "face": ">Y", "orientation": "forward"},
                "parameters": {"radius": "barrel_radius", "height": "barrel_length"},
            },
            {
                "id": "left_tracks",
                "kind": "primitive",
                "operation": "box",
                "mount": {"target": "hull", "face": "<X"},
                "parameters": {"size": ["track_width", "track_length", "track_height"]},
            },
            {
                "id": "right_tracks",
                "kind": "primitive",
                "operation": "box",
                "mount": {"target": "hull", "face": ">X"},
                "parameters": {"size": ["track_width", "track_length", "track_height"]},
            },
            {
                "id": "tank_assembly",
                "kind": "feature",
                "operation": "union",
                "inputs": ["hull", "turret", "barrel", "left_tracks", "right_tracks"],
            },
        ],
        "outputs": [{"id": "main", "node": "tank_assembly"}],
    }

    with caplog.at_level(logging.WARNING):
        normalized = app._normalize_ir_draft(raw_tank_ir, "一个简易坦克模型", "fdm", "mm")

    # Verify warning log
    assert any("Normalizing hallucinated 10x scale to canonical desktop scale (120mm)" in record.message for record in caplog.records)

    # Verify parameters scaled by 0.1
    params = normalized["parameters"]
    assert params["hull_length"]["value"] == 120.0
    assert params["hull_width"]["value"] == 60.0
    assert params["hull_height"]["value"] == 40.0
    assert params["turret_radius"]["value"] == 20.0
    assert params["turret_height"]["value"] == 15.0
    assert params["barrel_radius"]["value"] == 3.0
    assert params["barrel_length"]["value"] == 40.0
    assert params["track_width"]["value"] == 15.0
    assert params["track_length"]["value"] == 110.0
    assert params["track_height"]["value"] == 30.0

    # Verify provenance
    prov = normalized["provenance"]
    assert prov.get("canonical_desktop_scale_normalized") is True
    assert prov["scale_normalization"]["scale_factor"] == 0.1
    assert prov["scale_normalization"]["original_max_dimension"] == 1200.0

    # Verify mount properties are preserved
    nodes = {n["id"]: n for n in normalized["nodes"]}
    assert nodes["turret"]["mount"] == {"target": "hull", "face": ">Z"}
    assert nodes["barrel"]["mount"] == {"target": "turret", "face": ">Y", "orientation": "forward"}
    assert nodes["left_tracks"]["mount"] == {"target": "hull", "face": "<X"}
    assert nodes["right_tracks"]["mount"] == {"target": "hull", "face": ">X"}

    # Verify it passes IR validation
    validated = validate_ir(normalized)
    assert validated["schema_version"] == "0.2"


def test_scale_normalization_with_direct_node_dimensions(caplog):
    """When node parameters directly contain numbers > 300 without explicit prompt numbers."""
    raw = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "chassis",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"width": 1000.0, "depth": 500.0, "height": 300.0},
            }
        ],
        "outputs": [{"id": "main", "node": "chassis"}],
    }

    with caplog.at_level(logging.WARNING):
        normalized = app._normalize_ir_draft(raw, "a simple vehicle", "fdm", "mm")

    assert any("Normalizing hallucinated 10x scale to canonical desktop scale (120mm)" in record.message for record in caplog.records)
    node = normalized["nodes"][0]
    assert node["parameters"]["width"] == 100.0
    assert node["parameters"]["depth"] == 50.0
    assert node["parameters"]["height"] == 30.0


def test_scale_normalization_preserves_explicit_meter_prompts(caplog):
    """Prompts specifying meters or cm must NOT be downscaled."""
    raw = {
        "schema_version": "0.2",
        "parameters": {
            "length": {"value": 2000.0, "unit": "mm", "role": "dimension"},
        },
        "nodes": [
            {
                "id": "beam",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [2000.0, 100.0, 100.0]},
            }
        ],
        "outputs": [{"id": "main", "node": "beam"}],
    }

    # 1. Chinese '米'
    caplog.clear()
    n1 = app._normalize_ir_draft(raw, "2米长桌子", "fdm", "mm")
    assert not any("Normalizing hallucinated 10x scale" in record.message for record in caplog.records)
    assert n1["nodes"][0]["parameters"]["size"][0] == 2000.0

    # 2. English 'm'
    caplog.clear()
    n2 = app._normalize_ir_draft(raw, "a 2 m beam", "fdm", "mm")
    assert not any("Normalizing hallucinated 10x scale" in record.message for record in caplog.records)
    assert n2["nodes"][0]["parameters"]["size"][0] == 2000.0

    # 3. Units 'm'
    caplog.clear()
    n3 = app._normalize_ir_draft(raw, "large beam", "fdm", "m")
    assert not any("Normalizing hallucinated 10x scale" in record.message for record in caplog.records)


def test_scale_normalization_preserves_explicit_large_number_prompts(caplog):
    """Prompts with explicit large numbers (> 300) must NOT be downscaled."""
    raw = {
        "schema_version": "0.2",
        "parameters": {
            "length": {"value": 1200.0, "unit": "mm", "role": "dimension"},
        },
        "nodes": [
            {
                "id": "panel",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [1200.0, 600.0, 20.0]},
            }
        ],
        "outputs": [{"id": "main", "node": "panel"}],
    }

    caplog.clear()
    n = app._normalize_ir_draft(raw, "坦克模型，长1200mm", "fdm", "mm")
    assert not any("Normalizing hallucinated 10x scale" in record.message for record in caplog.records)
    assert n["nodes"][0]["parameters"]["size"][0] == 1200.0


def test_scale_normalization_preserves_desktop_scale_prompts(caplog):
    """Prompts with dimensions <= 300 mm must NOT be scaled down."""
    raw = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "box1",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [120.0, 60.0, 40.0]},
            }
        ],
        "outputs": [{"id": "main", "node": "box1"}],
    }

    caplog.clear()
    n = app._normalize_ir_draft(raw, "a small desktop model", "fdm", "mm")
    assert not any("Normalizing hallucinated 10x scale" in record.message for record in caplog.records)
    assert n["nodes"][0]["parameters"]["size"] == [120.0, 60.0, 40.0]


def test_scale_normalization_extreme_dimension(caplog):
    """Extreme dimension > 2400 mm normalizes envelope to ~120 mm."""
    raw = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "crane_arm",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [3000.0, 200.0, 200.0]},
            }
        ],
        "outputs": [{"id": "main", "node": "crane_arm"}],
    }

    with caplog.at_level(logging.WARNING):
        normalized = app._normalize_ir_draft(raw, "a robot arm", "fdm", "mm")

    assert any("Normalizing hallucinated 10x scale to canonical desktop scale (120mm)" in record.message for record in caplog.records)
    # 3000 * (120.0 / 3000.0) = 120.0
    assert normalized["nodes"][0]["parameters"]["size"][0] == 120.0
