"""Unit tests for Assembly Repair Operators in ir_repair.py and agent_loop.py."""
import copy
import inspect
import pytest
from ir_repair import apply_patches
from agent_loop import (
    _ALLOWED_CRITIQUE_PATCHES,
    _normalize_critique,
    _heuristic_fallback_critique,
    call_vlm_critic,
)


def _sample_tank_ir():
    return {
        "schema_version": "0.2",
        "parameters": {},
        "nodes": [
            {
                "id": "hull",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [100.0, 60.0, 25.0], "position": [0.0, 0.0, 0.0]},
            },
            {
                "id": "turret",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 20.0, "height": 15.0, "position": [0.0, 0.0, 0.0]},
            },
            {
                "id": "barrel",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 3.0, "height": 40.0, "position": [0.0, 0.0, 0.0]},
            },
            {
                "id": "tank_model",
                "kind": "feature",
                "operation": "union",
                "inputs": ["hull", "turret", "barrel"],
                "parameters": {},
            },
        ],
        "outputs": [{"id": "primary", "node": "tank_model", "format": ["step", "stl", "glb"]}],
    }


# =====================================================================
# 1. Tests for apply_patches: mount_component
# =====================================================================

def test_apply_patches_mount_component_basic():
    base_ir = _sample_tank_ir()
    patch = [
        {
            "op": "mount_component",
            "node": "turret",
            "target": "hull",
            "face": ">Z",
            "align": "center",
            "offset": [0.0, 0.0, 0.0],
        }
    ]
    repaired = apply_patches(base_ir, patch)
    turret_node = next(n for n in repaired["nodes"] if n["id"] == "turret")
    assert "mount" in turret_node
    assert turret_node["mount"]["target"] == "hull"
    assert turret_node["mount"]["face"] == ">Z"
    assert turret_node["mount"]["align"] == "center"
    assert turret_node["mount"]["offset"] == [0.0, 0.0, 0.0]
    # Also verify parameters copy
    assert turret_node["parameters"]["mount"]["face"] == ">Z"


def test_apply_patches_mount_component_update_existing():
    base_ir = _sample_tank_ir()
    # Add initial mount
    base_ir["nodes"][1]["mount"] = {
        "target": "hull",
        "face": "<Z",
        "align": "flush",
        "offset": [1.0, 2.0, 3.0],
    }
    # Update mount face and offset
    patch = [
        {
            "op": "mount_component",
            "node": "turret",
            "target": "hull",
            "face": ">Z",
            "offset": [0.0, 0.0, 5.0],
        }
    ]
    repaired = apply_patches(base_ir, patch)
    turret_node = next(n for n in repaired["nodes"] if n["id"] == "turret")
    assert turret_node["mount"]["face"] == ">Z"
    assert turret_node["mount"]["offset"] == [0.0, 0.0, 5.0]


def test_apply_patches_mount_component_faces_and_cleaning():
    base_ir = _sample_tank_ir()
    for face in (">Z", ">Y", "<Y", ">X", "<X"):
        patch = [
            {
                "op": "mount_component",
                "node": "barrel:cylinder",
                "target": "turret",
                "face": face,
                "align": "center",
            }
        ]
        repaired = apply_patches(base_ir, patch)
        barrel_node = next(n for n in repaired["nodes"] if n["id"] == "barrel")
        assert barrel_node["mount"]["face"] == face
        assert barrel_node["mount"]["target"] == "turret"


def test_apply_patches_mount_component_errors():
    base_ir = _sample_tank_ir()

    # Unknown child node
    with pytest.raises(ValueError, match="unknown node"):
        apply_patches(base_ir, [{"op": "mount_component", "node": "nonexistent", "target": "hull"}])

    # Unknown host target
    with pytest.raises(ValueError, match="unknown target"):
        apply_patches(base_ir, [{"op": "mount_component", "node": "turret", "target": "nonexistent"}])

    # Self-mount
    with pytest.raises(ValueError, match="cannot mount onto itself"):
        apply_patches(base_ir, [{"op": "mount_component", "node": "turret", "target": "turret"}])


# =====================================================================
# 2. Tests for apply_patches: orient_component
# =====================================================================

def test_apply_patches_orient_component_basic():
    base_ir = _sample_tank_ir()
    patch = [
        {
            "op": "orient_component",
            "node": "barrel",
            "axis": "x",
            "degrees": 90,
        }
    ]
    repaired = apply_patches(base_ir, patch)
    barrel_node = next(n for n in repaired["nodes"] if n["id"] == "barrel")
    assert "rotation" in barrel_node
    assert barrel_node["rotation"]["axis"] == "x"
    assert barrel_node["rotation"]["degrees"] == 90.0
    assert "orientation" in barrel_node
    assert barrel_node["orientation"]["axis"] == "x"
    assert barrel_node["orientation"]["degrees"] == 90.0
    # Also in parameters
    assert barrel_node["parameters"]["rotation"]["axis"] == "x"


def test_apply_patches_orient_component_update_existing():
    base_ir = _sample_tank_ir()
    base_ir["nodes"][2]["rotation"] = {"axis": "z", "degrees": 45.0}

    patch = [
        {
            "op": "orient_component",
            "node": "barrel",
            "axis": "y",
            "degrees": -90.0,
        }
    ]
    repaired = apply_patches(base_ir, patch)
    barrel_node = next(n for n in repaired["nodes"] if n["id"] == "barrel")
    assert barrel_node["rotation"]["axis"] == "y"
    assert barrel_node["rotation"]["degrees"] == -90.0


def test_apply_patches_orient_component_errors():
    base_ir = _sample_tank_ir()

    # Unknown node
    with pytest.raises(ValueError, match="unknown node"):
        apply_patches(base_ir, [{"op": "orient_component", "node": "ghost", "axis": "x", "degrees": 90}])

    # Invalid degrees
    with pytest.raises(ValueError, match="degrees must be numeric"):
        apply_patches(base_ir, [{"op": "orient_component", "node": "barrel", "axis": "x", "degrees": "not_a_number"}])


# =====================================================================
# 3. Tests for apply_patches: scale_component
# =====================================================================

def test_apply_patches_scale_component_cylinder():
    base_ir = _sample_tank_ir()
    patch = [
        {
            "op": "scale_component",
            "node": "barrel",
            "factor": 0.5,
        }
    ]
    repaired = apply_patches(base_ir, patch)
    barrel_node = next(n for n in repaired["nodes"] if n["id"] == "barrel")
    assert barrel_node["parameters"]["radius"] == 1.5
    assert barrel_node["parameters"]["height"] == 20.0
    assert barrel_node["scale"] == 0.5


def test_apply_patches_scale_component_box_size():
    base_ir = _sample_tank_ir()
    patch = [
        {
            "op": "scale_component",
            "node": "hull",
            "factor": 0.5,
        }
    ]
    repaired = apply_patches(base_ir, patch)
    hull_node = next(n for n in repaired["nodes"] if n["id"] == "hull")
    assert hull_node["parameters"]["size"] == [50.0, 30.0, 12.5]
    assert hull_node["scale"] == 0.5


def test_apply_patches_subcomponent_feature_preserves_assembly_outputs():
    base_ir = _sample_tank_ir()
    patch = [{"op": "add_chamfer", "target_node": "hull", "distance": 2.0}]
    repaired = apply_patches(base_ir, patch)
    # The output should STILL be tank_model, NOT chamfer_1
    assert repaired["outputs"][0]["node"] == "tank_model"
    # And tank_model's inputs should be updated to use chamfer_1 instead of hull
    tank_node = next(n for n in repaired["nodes"] if n["id"] == "tank_model")
    assert "chamfer_1" in tank_node["inputs"]
    assert "hull" not in tank_node["inputs"]


def test_apply_patches_subcomponent_feature_rewires_mount_target():
    base_ir = _sample_tank_ir()
    turret_node = next(n for n in base_ir["nodes"] if n["id"] == "turret")
    turret_node["mount"] = {"target": "hull", "face": ">Z"}
    patch = [{"op": "add_chamfer", "target_node": "hull", "distance": 2.0}]
    repaired = apply_patches(base_ir, patch)
    repaired_turret = next(n for n in repaired["nodes"] if n["id"] == "turret")
    assert repaired_turret["mount"]["target"] == "chamfer_1"




def test_apply_patches_scale_component_separate_dimensions():
    ir = {
        "schema_version": "0.2",
        "parameters": {},
        "nodes": [
            {
                "id": "block",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"width": 80.0, "depth": 40.0, "height": 20.0},
            }
        ],
        "outputs": [{"id": "primary", "node": "block", "format": ["step", "stl", "glb"]}],
    }
    patch = [{"op": "scale_component", "node": "block", "factor": 2.0}]
    repaired = apply_patches(ir, patch)
    node = repaired["nodes"][0]
    assert node["parameters"]["width"] == 160.0
    assert node["parameters"]["depth"] == 80.0
    assert node["parameters"]["height"] == 40.0
    assert node["scale"] == 2.0


def test_apply_patches_scale_component_points():
    ir = {
        "schema_version": "0.2",
        "parameters": {},
        "nodes": [
            {
                "id": "prism",
                "kind": "primitive",
                "operation": "polygon_prism",
                "parameters": {
                    "points": [[-10.0, -10.0], [10.0, -10.0], [0.0, 10.0]],
                    "height": 30.0,
                },
            }
        ],
        "outputs": [{"id": "primary", "node": "prism", "format": ["step", "stl", "glb"]}],
    }
    patch = [{"op": "scale_component", "node": "prism", "factor": 0.5}]
    repaired = apply_patches(ir, patch)
    node = repaired["nodes"][0]
    assert node["parameters"]["points"] == [[-5.0, -5.0], [5.0, -5.0], [0.0, 5.0]]
    assert node["parameters"]["height"] == 15.0
    assert node["scale"] == 0.5


def test_apply_patches_scale_component_errors():
    base_ir = _sample_tank_ir()

    # Unknown node
    with pytest.raises(ValueError, match="unknown node"):
        apply_patches(base_ir, [{"op": "scale_component", "node": "ghost", "factor": 0.5}])

    # Negative / zero / non-numeric factor
    with pytest.raises(ValueError, match="factor must be a positive number"):
        apply_patches(base_ir, [{"op": "scale_component", "node": "barrel", "factor": -0.5}])
    with pytest.raises(ValueError, match="factor must be a positive number"):
        apply_patches(base_ir, [{"op": "scale_component", "node": "barrel", "factor": 0.0}])
    with pytest.raises(ValueError, match="factor must be a positive number"):
        apply_patches(base_ir, [{"op": "scale_component", "node": "barrel", "factor": "invalid"}])


# =====================================================================
# 4. Tests for agent_loop critique and contract
# =====================================================================

def test_allowed_critique_patches():
    assert "mount_component" in _ALLOWED_CRITIQUE_PATCHES
    assert "orient_component" in _ALLOWED_CRITIQUE_PATCHES
    assert "scale_component" in _ALLOWED_CRITIQUE_PATCHES

    critique_payload = {
        "score": 8.0,
        "verdict": "REVISE",
        "summary": "Assembly needs alignment.",
        "discrepancies": [],
        "proposed_patches": [
            {"op": "mount_component", "node": "turret", "target": "hull", "face": ">Z"},
            {"op": "orient_component", "node": "barrel", "axis": "x", "degrees": 90},
            {"op": "scale_component", "node": "barrel", "factor": 0.5},
        ],
    }
    normalized = _normalize_critique(critique_payload)
    assert len(normalized["proposed_patches"]) == 3
    ops = [p["op"] for p in normalized["proposed_patches"]]
    assert ops == ["mount_component", "orient_component", "scale_component"]


def test_heuristic_fallback_critique_assembly_tank():
    tank_ir = _sample_tank_ir()
    # Initial IR: barrel is vertical (no rotation), turret is buried at z=0 (hull height=25)
    critique = _heuristic_fallback_critique("a military tank model with turret and barrel", tank_ir, 0)
    assert critique["verdict"] == "REVISE"
    patches = critique["proposed_patches"]

    # Verify orient_component was proposed for vertical barrel
    orient_patch = next((p for p in patches if p["op"] == "orient_component"), None)
    assert orient_patch is not None
    assert orient_patch["node"] == "barrel"
    assert orient_patch["axis"] == "x"
    assert orient_patch["degrees"] == 90

    # Verify mount_component was proposed for buried turret
    mount_patch = next((p for p in patches if p["op"] == "mount_component"), None)
    assert mount_patch is not None
    assert mount_patch["node"] == "turret"
    assert mount_patch["target"] == "hull"
    assert mount_patch["face"] == ">Z"

    # Now apply the proposed patches to tank_ir
    repaired_ir = apply_patches(tank_ir, patches)

    # Re-run heuristic critique with repaired IR and patch history: should be clean
    critique2 = _heuristic_fallback_critique(
        "a military tank model with turret and barrel",
        repaired_ir,
        1,
        patch_history=patches,
    )
    # Neither orient_component nor mount_component should be proposed again
    assert not any(p["op"] in ("orient_component", "mount_component") for p in critique2["proposed_patches"])


def test_call_vlm_critic_system_prompt_documentation():
    # Verify by reading the implementation of call_vlm_critic
    src = inspect.getsource(call_vlm_critic)
    assert "- 'mount_component': mounts a buried, floating, or misplaced component directly onto a face of a host component (e.g. mount turret onto hull face '>Z', mount barrel onto turret face '>Y')." in src
    assert "- 'orient_component': rotates a misaligned component (e.g. rotating a vertical barrel around X by 90 degrees to point forward horizontally)." in src


def test_full_assembly_repair_chain():
    initial_ir = _sample_tank_ir()
    patches = [
        {
            "op": "mount_component",
            "node": "turret",
            "target": "hull",
            "face": ">Z",
            "align": "center",
            "offset": [0.0, 0.0, 0.0],
        },
        {
            "op": "orient_component",
            "node": "barrel",
            "axis": "x",
            "degrees": 90,
        },
        {
            "op": "scale_component",
            "node": "barrel",
            "factor": 0.5,
        },
    ]
    repaired = apply_patches(initial_ir, patches)
    turret = next(n for n in repaired["nodes"] if n["id"] == "turret")
    barrel = next(n for n in repaired["nodes"] if n["id"] == "barrel")

    assert turret["mount"]["face"] == ">Z"
    assert barrel["rotation"]["axis"] == "x"
    assert barrel["rotation"]["degrees"] == 90.0
    assert barrel["parameters"]["radius"] == 1.5
    assert barrel["parameters"]["height"] == 20.0
