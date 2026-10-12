"""Unit tests for feature_catalog, agent_contracts, and ir_registry."""
import pytest
from feature_catalog import retrieve_feature_recipes, FEATURE_RECIPES
from agent_contracts import extract_requirement_spec, verify_requirement_spec
from ir_registry import OPERATION_SPECS, ALLOWED_OPERATIONS, get_operation_spec, validate_operation_node


def test_feature_catalog_retrieves_relevant_recipes():
    # Hole pattern prompt
    r_holes = retrieve_feature_recipes("A circular flange with 4 mounting holes and a central bore")
    assert len(r_holes) > 0
    assert any(item["id"] == "mounting_hole_pattern" for item in r_holes)

    # Finned heat sink prompt
    r_fins = retrieve_feature_recipes("A heat sink base with 5 cooling fins and a chip pocket")
    assert len(r_fins) > 0
    assert any(item["id"] == "linear_fins" for item in r_fins)

    # Stepped shaft prompt
    r_shaft = retrieve_feature_recipes("A 3-tier stepped shaft with large, mid, and output diameters")
    assert len(r_shaft) > 0
    assert any(item["id"] == "stepped_shaft" for item in r_shaft)

    # Dovetail prompt
    r_dove = retrieve_feature_recipes("A linear slide base with a dovetail slot profile")
    assert len(r_dove) > 0
    assert any(item["id"] == "dovetail_base" for item in r_dove)

    # Gear prompt
    r_gear = retrieve_feature_recipes("A spur gear with 16 teeth and pitch diameter 48 mm")
    assert len(r_gear) > 0
    assert any(item["id"] == "gear_like_pattern" for item in r_gear)


def test_agent_contracts_extracts_structured_requirements():
    spec1 = extract_requirement_spec("A flange with 4 mounting holes and 2mm chamfer")
    features = {f["kind"]: f for f in spec1.get("features", [])}
    assert "hole_pattern" in features
    assert features["hole_pattern"].get("count") == 4
    assert "edge_treatment" in features

    spec2 = extract_requirement_spec("Heat sink with 5 fins and hollow pocket")
    features2 = {f["kind"]: f for f in spec2.get("features", [])}
    assert "fins" in features2
    assert features2["fins"].get("count") == 5
    assert "shell" in features2


def test_agent_contracts_verifies_requirement_spec():
    spec = extract_requirement_spec("A flange with 4 mounting holes")
    # IR missing holes
    empty_ir = {"nodes": [{"id": "base", "operation": "cylinder"}], "outputs": [{"node": "base"}]}
    issues = verify_requirement_spec(spec, empty_ir)
    assert len(issues) > 0
    assert any("hole" in i.get("issue", "").lower() for i in issues)

    # IR with 4 cutters
    complete_ir = {
        "nodes": [
            {"id": "base", "operation": "cylinder"},
            {"id": "cutter_0", "operation": "cylinder"},
            {"id": "cutter_1", "operation": "cylinder"},
            {"id": "cutter_2", "operation": "cylinder"},
            {"id": "cutter_3", "operation": "cylinder"},
            {"id": "cut_node", "operation": "cut", "inputs": ["base", "cutter_0", "cutter_1", "cutter_2", "cutter_3"]}
        ],
        "outputs": [{"node": "cut_node"}]
    }
    issues_ok = verify_requirement_spec(spec, complete_ir)
    assert len(issues_ok) == 0


def test_ir_registry_operation_contracts():
    assert "box" in ALLOWED_OPERATIONS
    assert "cylinder" in ALLOWED_OPERATIONS
    assert "cut" in ALLOWED_OPERATIONS
    assert "union" in ALLOWED_OPERATIONS
    assert "linear_pattern" in ALLOWED_OPERATIONS
    assert "polar_pattern" in ALLOWED_OPERATIONS
    assert "unregistered_magic_op" not in ALLOWED_OPERATIONS

    cut_contract = get_operation_spec("cut")
    assert cut_contract is not None
    assert cut_contract.min_inputs == 1

    box_contract = get_operation_spec("box")
    assert box_contract is not None
    # Validate node
    valid_box = {"id": "my_box", "operation": "box", "parameters": {"width": 10, "depth": 10, "height": 10}}
    issues = validate_operation_node(valid_box, "nodes[0]")
    assert len(issues) == 0
