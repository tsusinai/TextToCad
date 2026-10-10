"""Unit tests for MultiGateInspector in agent_loop.py."""
import pytest
from agent_loop import MultiGateInspector

def test_multigate_inspector_pass_all_gates():
    inspector = MultiGateInspector(target_score=9.0)
    prompt = "An industrial flange with 4 mounting holes and a central bore"
    current_ir = {
        "nodes": [
            {"id": "base", "operation": "cylinder"},
            {"id": "bore", "operation": "cylinder"},
            {"id": "cutter_0", "operation": "cylinder"},
            {"id": "cutter_1", "operation": "cylinder"},
            {"id": "cutter_2", "operation": "cylinder"},
            {"id": "cutter_3", "operation": "cylinder"},
            {"id": "cut_holes", "operation": "cut", "inputs": ["base", "bore", "cutter_0", "cutter_1", "cutter_2", "cutter_3"]}
        ],
        "outputs": [{"id": "primary", "node": "cut_holes"}]
    }
    metrics = {
        "valid_brep": True,
        "solid_count": 1,
        "volume_mm3": 24500.0,
        "face_count": 8,
        "bbox_mm": {"x": 60.0, "y": 60.0, "z": 10.0}
    }
    dfm_report = {"valid": True, "violations": []}
    critique = {
        "score": 9.5,
        "verdict": "ACCEPT",
        "summary": "All features pass inspection.",
        "discrepancies": []
    }

    cert = inspector.inspect_round(
        round_idx=1,
        prompt=prompt,
        current_ir=current_ir,
        metrics=metrics,
        dfm_report=dfm_report,
        critique=critique,
        model_id="abc12345"
    )

    assert cert["status"] == "PASSED"
    assert cert["passed"] is True
    assert cert["passed_gates_count"] == 5
    assert cert["certificate_id"].startswith("AC-ABC123-R1")
    assert len(cert["gates"]) == 5
    assert all(g["passed"] for g in cert["gates"])


def test_multigate_inspector_reject_missing_features():
    inspector = MultiGateInspector(target_score=9.0)
    prompt = "An industrial flange with 4 mounting holes and a central bore"
    current_ir = {
        "nodes": [
            {"id": "base", "operation": "cylinder"}  # Missing cut operation
        ],
        "outputs": [{"id": "primary", "node": "base"}]
    }
    metrics = {
        "valid_brep": True,
        "solid_count": 1,
        "volume_mm3": 28000.0,
        "face_count": 3,
        "bbox_mm": {"x": 60.0, "y": 60.0, "z": 10.0}
    }
    dfm_report = {"valid": True, "violations": []}
    critique = {
        "score": 4.0,
        "verdict": "REVISE",
        "summary": "Mounting holes are completely missing.",
        "discrepancies": [
            {"severity": "high", "feature": "holes", "issue": "Missing 4 mounting holes."}
        ]
    }

    cert = inspector.inspect_round(
        round_idx=0,
        prompt=prompt,
        current_ir=current_ir,
        metrics=metrics,
        dfm_report=dfm_report,
        critique=critique,
        model_id="abc12345"
    )

    assert cert["status"] == "REJECTED"
    assert cert["passed"] is False
    assert cert["passed_gates_count"] < 5

    # Check Gate 2 failed
    gate2 = next(g for g in cert["gates"] if g["id"] == "gate_features")
    assert gate2["passed"] is False

    # Check Gate 3 failed
    gate3 = next(g for g in cert["gates"] if g["id"] == "gate_visual")
    assert gate3["passed"] is False


def test_multigate_inspector_reject_non_manifold():
    inspector = MultiGateInspector(target_score=9.0)
    prompt = "A simple block"
    current_ir = {"nodes": [{"id": "box", "operation": "box"}]}
    metrics = {
        "valid_brep": False,  # Non-manifold
        "solid_count": 2,     # Disjoint solids
        "volume_mm3": 1000.0,
        "face_count": 12,
    }
    dfm_report = {"valid": True, "violations": []}
    critique = {"score": 9.0, "verdict": "ACCEPT", "discrepancies": []}

    cert = inspector.inspect_round(
        round_idx=0,
        prompt=prompt,
        current_ir=current_ir,
        metrics=metrics,
        dfm_report=dfm_report,
        critique=critique,
        model_id="mod123"
    )

    assert cert["status"] == "REJECTED"
    gate1 = next(g for g in cert["gates"] if g["id"] == "gate_topology")
    assert gate1["passed"] is False
