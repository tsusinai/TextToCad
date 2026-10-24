"""Standalone Simulation and Regression Test for Visual CAD Agent Modeling Loop.

Performs an end-to-end simulation of the Agent CAD Modeling pipeline:
1. Realistic engineering prompt setup ("Industrial flange disc with 4 mounting holes and central bore").
2. Multi-turn visual auto-rework cycle execution (CadQuery B-Rep -> Multi-view renders -> Heuristic Critique -> Patching).
3. Verification of:
   a) Round 0 B-Rep geometry, STL/GLB export, 4-view and annotated composite renders.
   b) Heuristic fallback critique discrepancy detection and `add_hole_pattern` patch proposal.
   c) Clean application of patches into Round 1 B-Rep geometry.
   d) Loop convergence with valid final IR and round history.
   e) Non-zero existence of all generated CAD and rendering artifacts.
4. Automatic sandbox cleanup using tempfile.TemporaryDirectory.
5. Reporting execution timing, generated artifact tree, and test verdict.
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
import sys
import tempfile
import time
from typing import Any

# Ensure backend and project root are importable
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
for search_path in (str(BACKEND_DIR), str(PROJECT_ROOT)):
    if search_path not in sys.path:
        sys.path.insert(0, search_path)

import pytest

try:
    import cadquery as cq
except ImportError:
    cq = None

try:
    import agent_loop
    from agent_loop import _select_patch_candidate, run_agent_modeling_loop
    from ir_executor import IRExecutionError
    from ir_validate import validate_ir
    from PIL import Image
except ImportError as err:
    raise ImportError(f"Required dependency missing for agent simulation: {err}") from err

logger = logging.getLogger("test_agent_simulation")

# Minimal valid box IR shared by the error-path unit tests.
_BOX_IR: dict[str, Any] = {
    "schema_version": "0.2",
    "parameters": {},
    "nodes": [
        {
            "id": "base_box",
            "kind": "primitive",
            "operation": "box",
            "inputs": [],
            "parameters": {"width": 20.0, "depth": 20.0, "height": 20.0},
        },
    ],
    "outputs": [{"id": "primary", "node": "base_box", "format": ["step", "stl", "glb"]}],
}


def run_simulation() -> dict[str, Any]:
    """Execute the end-to-end agent CAD modeling simulation and assert pipeline contracts."""
    prompt = "Industrial flange disc with 4 mounting holes and central bore"
    process = "cnc"

    # Initial IR represents the flange disc with central bore, but missing mounting hole pattern
    initial_ir: dict[str, Any] = {
        "schema_version": "0.2",
        "parameters": {
            "flange_radius": {"value": 50.0, "unit": "mm"},
            "flange_thickness": {"value": 12.0, "unit": "mm"},
            "bore_radius": {"value": 15.0, "unit": "mm"},
        },
        "nodes": [
            {
                "id": "flange_disc",
                "kind": "primitive",
                "operation": "cylinder",
                "inputs": [],
                "parameters": {"radius": 50.0, "height": 12.0},
            },
            {
                "id": "bore_cylinder",
                "kind": "primitive",
                "operation": "cylinder",
                "inputs": [],
                "parameters": {"radius": 15.0, "height": 24.0, "position": [0.0, 0.0, -6.0]},
            },
            {
                "id": "flange_with_bore",
                "kind": "feature",
                "operation": "cut",
                "inputs": ["flange_disc", "bore_cylinder"],
                "parameters": {},
            },
        ],
        "outputs": [{"id": "primary", "node": "flange_with_bore", "format": ["step", "stl", "glb"]}],
    }

    # Verify initial IR validity before simulation
    validate_ir(initial_ir)

    # Track progress events emitted by run_agent_modeling_loop
    progress_events: list[dict[str, Any]] = []

    def mock_progress_callback(ev: dict[str, Any]) -> None:
        progress_events.append(dict(ev))

    total_start_time = time.perf_counter()
    artifacts_snapshot: dict[int, list[dict[str, Any]]] = {}
    temp_dir_path: Path | None = None

    with tempfile.TemporaryDirectory(prefix="agent_sim_") as tmpdir:
        temp_dir_path = Path(tmpdir)
        artifacts_root = temp_dir_path / "artifacts"
        artifacts_root.mkdir(parents=True, exist_ok=True)

        loop_start_time = time.perf_counter()
        agent_result = run_agent_modeling_loop(
            initial_ir=initial_ir,
            prompt=prompt,
            process=process,
            artifacts_dir=artifacts_root,
            llm_api_url=None,  # Force heuristic fallback critique
            llm_api_key=None,
            llm_model=None,
            max_rounds=3,
            target_score=9.0,
            progress_callback=mock_progress_callback,
        )
        loop_duration = time.perf_counter() - loop_start_time

        # Snapshot file artifacts before exiting temp context
        rounds_dir = artifacts_root / "rounds"
        assert rounds_dir.exists(), "rounds directory must be created"

        total_rounds = agent_result.get("total_rounds", 0)
        for r in range(total_rounds):
            round_dir = rounds_dir / str(r)
            assert round_dir.exists(), f"Round {r} directory must exist on disk"
            round_files: list[dict[str, Any]] = []
            for file_path in sorted(round_dir.rglob("*")):
                if file_path.is_file():
                    rel_name = str(file_path.relative_to(round_dir))
                    size_bytes = file_path.stat().st_size
                    round_files.append({"relative_path": rel_name, "size_bytes": size_bytes})
            artifacts_snapshot[r] = round_files

        # -------------------------------------------------------------
        # Verification a: Round 0 B-Rep, STL/GLB, 4-view & annotated renders
        # -------------------------------------------------------------
        history = agent_result.get("history", [])
        assert len(history) >= 2, f"Expected at least 2 rounds in history, got {len(history)}"

        r0_record = history[0]
        assert r0_record["round"] == 0
        assert r0_record["glb_available"] is True, "Round 0 GLB should be available"

        r0_dir = rounds_dir / "0"
        r0_stl = r0_dir / "model.stl"
        r0_glb = r0_dir / "model.glb"
        r0_composite = r0_dir / "views" / "composite.png"
        r0_annotated = r0_dir / "annotated_composite.png"
        r0_views_dir = r0_dir / "views"

        assert r0_stl.is_file() and r0_stl.stat().st_size > 0, "Round 0 STL must exist and be non-empty"
        assert r0_glb.is_file() and r0_glb.stat().st_size > 0, "Round 0 GLB must exist and be non-empty"
        assert r0_composite.is_file() and r0_composite.stat().st_size > 0, "Round 0 composite.png must exist"
        assert r0_annotated.is_file() and r0_annotated.stat().st_size > 0, "Round 0 annotated_composite.png must exist"

        for view_name in ("top", "front", "right", "iso"):
            view_file = r0_views_dir / f"{view_name}.png"
            assert view_file.is_file() and view_file.stat().st_size > 0, f"Round 0 {view_name}.png must exist and be non-empty"

        with Image.open(r0_composite) as img:
            assert img.size == (1024, 1024), f"Composite image expected (1024, 1024), got {img.size}"

        with Image.open(r0_annotated) as img:
            assert img.size == (1024, 1024), f"Annotated composite expected (1024, 1024), got {img.size}"

        # -------------------------------------------------------------
        # Verification b: Heuristic fallback critique detects discrepancies
        # -------------------------------------------------------------
        r0_discrepancies = r0_record.get("discrepancies", [])
        assert len(r0_discrepancies) > 0, "Round 0 critique must detect discrepancies"
        assert any(d.get("feature") == "hole_pattern" for d in r0_discrepancies), (
            "Discrepancies must identify missing hole_pattern"
        )
        assert r0_record["verdict"] == "REVISE", f"Round 0 verdict should be REVISE, got {r0_record['verdict']}"
        assert r0_record["score"] < 9.0, f"Round 0 score should be < 9.0, got {r0_record['score']}"

        r0_patches = r0_record.get("proposed_patches", [])
        assert len(r0_patches) > 0, "Round 0 must propose repair patches"
        hole_patch = next((p for p in r0_patches if p.get("op") == "add_hole_pattern"), None)
        assert hole_patch is not None, "Proposed patches must contain 'add_hole_pattern'"
        assert hole_patch.get("count") == 4, f"Hole pattern count should be 4, got {hole_patch.get('count')}"
        assert hole_patch.get("target_node") == "flange_with_bore"

        # -------------------------------------------------------------
        # Verification c: Patches applied cleanly to generate Round 1
        # -------------------------------------------------------------
        r1_record = history[1]
        assert r1_record["round"] == 1
        assert r1_record["glb_available"] is True, "Round 1 GLB should be available"

        r1_dir = rounds_dir / "1"
        r1_stl = r1_dir / "model.stl"
        r1_glb = r1_dir / "model.glb"
        r1_composite = r1_dir / "views" / "composite.png"
        r1_annotated = r1_dir / "annotated_composite.png"

        assert r1_stl.is_file() and r1_stl.stat().st_size > 0, "Round 1 STL must exist and be non-empty"
        assert r1_glb.is_file() and r1_glb.stat().st_size > 0, "Round 1 GLB must exist and be non-empty"
        assert r1_composite.is_file() and r1_composite.stat().st_size > 0, "Round 1 composite.png must exist"
        assert r1_annotated.is_file() and r1_annotated.stat().st_size > 0, "Round 1 annotated_composite.png must exist"

        # The mesh with 4 cut holes should have more faces/vertices (larger STL size)
        assert r1_stl.stat().st_size > r0_stl.stat().st_size, (
            f"Round 1 STL ({r1_stl.stat().st_size} B) should be larger than Round 0 ({r0_stl.stat().st_size} B)"
        )

        # -------------------------------------------------------------
        # Verification d: Loop converges with valid final IR and history
        # -------------------------------------------------------------
        assert agent_result.get("converged") is True, "Agent loop should converge"
        assert agent_result.get("total_rounds") == 2, f"Expected 2 rounds to convergence, got {total_rounds}"
        assert agent_result.get("final_score", 0.0) >= 9.0, f"Final score must be >= 9.0, got {agent_result.get('final_score')}"
        assert r1_record.get("verdict") == "ACCEPT", f"Round 1 verdict must be ACCEPT, got {r1_record.get('verdict')}"
        assert len(r1_record.get("discrepancies", [])) == 0, "Round 1 should have 0 discrepancies"

        final_ir = agent_result.get("final_ir", {})
        validated_final_ir = validate_ir(final_ir)
        assert validated_final_ir is not None, "Final IR must pass schema and DAG validation"

        final_node_ids = [n["id"] for n in final_ir.get("nodes", [])]
        assert "cut_hole_pattern_1" in final_node_ids, "Final IR must contain cut_hole_pattern_1"
        for i in range(4):
            assert f"cutter_1_{i}" in final_node_ids, f"Final IR must contain cutter_1_{i}"

        # Check progress events
        stages_emitted = [ev.get("stage") for ev in progress_events]
        assert "agent_compilation" in stages_emitted
        assert "agent_rendering" in stages_emitted
        assert "agent_critique" in stages_emitted
        assert "agent_patching" in stages_emitted

        # -------------------------------------------------------------
        # Verification e: All artifact files exist and have non-zero size
        # -------------------------------------------------------------
        for r_idx, files in artifacts_snapshot.items():
            for f_info in files:
                assert f_info["size_bytes"] > 0, f"Artifact {f_info['relative_path']} in round {r_idx} is empty"

    # Verification 2: Clean up temporary files
    assert temp_dir_path is not None
    assert not temp_dir_path.exists(), f"Temporary directory {temp_dir_path} must be cleaned up"

    total_duration = time.perf_counter() - total_start_time

    return {
        "verdict": "PASSED",
        "total_duration": total_duration,
        "loop_duration": loop_duration,
        "total_rounds": agent_result.get("total_rounds"),
        "final_score": agent_result.get("final_score"),
        "converged": agent_result.get("converged"),
        "progress_event_count": len(progress_events),
        "artifacts_snapshot": artifacts_snapshot,
        "final_ir_node_count": len(final_ir.get("nodes", [])),
    }


@pytest.mark.skipif(cq is None, reason="CadQuery is required for B-Rep simulation")
def test_agent_modeling_simulation() -> None:
    """Pytest test case entrypoint."""
    result = run_simulation()
    assert result["verdict"] == "PASSED"
    assert result["converged"] is True


@pytest.mark.skipif(cq is None, reason="CadQuery is required for B-Rep simulation")
def test_rollback_failure_raises_original_error(monkeypatch, tmp_path) -> None:
    """A first-round kernel failure whose rollback also fails must surface the original
    IRExecutionError, not a downstream FileNotFoundError from the renderer."""
    original_error = IRExecutionError("kernel rejected node 'base_box': unregistered input")

    def always_fail(ir):  # noqa: ANN001 - matches execute_ir signature loosely
        raise original_error

    monkeypatch.setattr(agent_loop, "execute_ir", always_fail)

    with pytest.raises(IRExecutionError) as excinfo:
        run_agent_modeling_loop(
            initial_ir=copy.deepcopy(_BOX_IR),
            prompt="a 20mm box",
            process="cnc",
            artifacts_dir=tmp_path / "artifacts",
            llm_api_url=None,
            llm_api_key=None,
            llm_model=None,
            max_rounds=2,
        )
    assert "unregistered input" in str(excinfo.value), (
        "The raised error must carry the original kernel failure reason"
    )
    assert not isinstance(excinfo.value, FileNotFoundError)


@pytest.mark.skipif(cq is None, reason="CadQuery is required for B-Rep simulation")
def test_tie_break_prefers_fewer_patches(monkeypatch) -> None:
    """When candidate branches score identically, the branch with fewer patches must win
    (minimal-repair-first philosophy protects already-verified primitives)."""

    def make_noop_patch(parameter: str) -> dict[str, Any]:
        return {
            "op": "replace_node_parameter",
            "node": "base_box",
            "parameter": parameter,
            "value": 20.0,  # identical to the current value -> both branches stay equivalent
        }

    fewer = [make_noop_patch("width")]
    more = [make_noop_patch("width"), make_noop_patch("depth"), make_noop_patch("height")]

    # Force the candidate beam to exactly two functionally equivalent branches.
    monkeypatch.setattr(agent_loop, "_patch_variants", lambda patches: [more, fewer])

    best, evaluations = _select_patch_candidate(
        current_ir=copy.deepcopy(_BOX_IR),
        patches=fewer + more[1:],
        prompt="a simple box",
        process_profile=None,
    )
    assert best is not None, "At least one candidate branch must be executable"
    assert len(evaluations) == 2
    assert [ev["status"] for ev in evaluations] == ["valid", "valid"]
    assert len(best["patches"]) == 1, "Tied ranks must prefer the branch with fewer patches"


def test_time_budget_exits_early_with_best_candidate(monkeypatch, tmp_path) -> None:
    """AGENT_TIME_BUDGET_SECONDS=0 must exit the loop before any round runs, keep the
    return structure intact, adopt the current best candidate (the initial IR), and flag
    budget_exhausted."""
    monkeypatch.setenv("AGENT_TIME_BUDGET_SECONDS", "0")

    result = run_agent_modeling_loop(
        initial_ir=copy.deepcopy(_BOX_IR),
        prompt="a 20mm box",
        process="cnc",
        artifacts_dir=tmp_path / "artifacts",
        llm_api_url=None,
        llm_api_key=None,
        llm_model=None,
        max_rounds=3,
    )

    assert result["budget_exhausted"] is True
    assert result["total_rounds"] == 0, "No repair round should start once the budget is gone"
    assert result["history"] == []
    assert result["final_ir"] == _BOX_IR, "Initial IR is the best available candidate"
    assert result["converged"] is False
    # Return structure stays intact for downstream consumers.
    for key in ("final_ir", "best_round", "total_rounds", "converged", "final_score", "final_certificate", "history"):
        assert key in result
    assert not (tmp_path / "artifacts" / "rounds").exists(), "No round artifacts should be created"


def test_collect_degraded_operations_flattens_trace() -> None:
    execution = {
        "trace": [
            {"id": "body", "operation": "box", "status": "succeeded"},
            {
                "id": "edge_treatment",
                "operation": "fillet",
                "status": "succeeded",
                "degraded_operations": [{"op": "fillet", "reason": "radius 999 exceeded edge limits"}],
            },
            {
                "id": "shell_1",
                "operation": "shell",
                "status": "succeeded",
                "degraded_operations": [
                    {"op": "shell", "reason": "thickness out of range"},
                    {"op": "shell", "reason": "fallback to input solid"},
                ],
            },
        ]
    }
    degraded = agent_loop._collect_degraded_operations(execution)
    assert [(d["node"], d["op"]) for d in degraded] == [
        ("edge_treatment", "fillet"),
        ("shell_1", "shell"),
        ("shell_1", "shell"),
    ]
    assert "radius 999" in degraded[0]["reason"]
    assert agent_loop._collect_degraded_operations({"trace": []}) == []


def _inspect_with_degraded(degraded):
    inspector = agent_loop.MultiGateInspector(target_score=9.0)
    metrics = {
        "valid_brep": True, "solid_count": 1, "volume_mm3": 8000.0,
        "face_count": 6, "bbox_mm": {"x": 20.0, "y": 20.0, "z": 20.0},
    }
    critique = {"score": 9.5, "verdict": "ACCEPT", "discrepancies": []}
    dfm_report = {"valid": True, "violations": []}
    current_ir = {
        "schema_version": "0.2",
        "nodes": [{"id": "body", "kind": "primitive", "operation": "box",
                   "parameters": {"size": [20, 20, 20]}}],
        "outputs": [{"id": "main", "node": "body"}],
    }
    return inspector.inspect_round(
        round_idx=0,
        prompt="a 20mm cube",
        current_ir=current_ir,
        metrics=metrics,
        dfm_report=dfm_report,
        critique=critique,
        model_id="abc123",
        degraded_operations=degraded,
    )


def test_inspect_round_surfaces_degraded_warning() -> None:
    certificate = _inspect_with_degraded(
        [{"node": "edge_treatment", "op": "fillet", "reason": "radius too large"}]
    )
    assert certificate["degraded_operations"] == [
        {"node": "edge_treatment", "op": "fillet", "reason": "radius too large"}
    ]
    topology_gate = next(g for g in certificate["gates"] if g["id"] == "gate_topology")
    assert "degraded op(s)" in topology_gate["evidence"]
    # Warning-level only: a clean-elsewhere round must still certify.
    assert certificate["passed"] is True

    clean = _inspect_with_degraded(None)
    assert clean["degraded_operations"] == []
    clean_gate = next(g for g in clean["gates"] if g["id"] == "gate_topology")
    assert "degraded op(s)" not in clean_gate["evidence"]


@pytest.mark.skipif(cq is None, reason="CadQuery required for kernel degradation path")
def test_kernel_degraded_fillet_is_collected() -> None:
    from ir_executor import execute_ir
    import app as backend_app

    ir = {
        "schema_version": "0.2",
        "document": {"id": "degraded-fillet", "intent": "box with impossible fillet", "units": "mm"},
        "units": "mm", "process": "fdm", "parameters": {},
        "datums": [{"id": "xy", "type": "plane"}],
        "nodes": [
            {"id": "body", "kind": "primitive", "operation": "box",
             "parameters": {"size": [20, 20, 20]}, "frame": "xy"},
            {"id": "edge_treatment", "kind": "feature", "operation": "fillet",
             "inputs": ["body"], "parameters": {"radius": 999}},
        ],
        "constraints": [],
        "outputs": [{"id": "main", "node": "edge_treatment"}],
    }
    execution = execute_ir(backend_app.validate_ir(ir))
    degraded = agent_loop._collect_degraded_operations(execution)
    assert degraded, "impossible fillet radius must be collected as a degraded operation"
    assert degraded[0]["op"] == "fillet"


def main() -> None:
    """Standalone CLI execution with formatted reporting."""
    print("=" * 80)
    print("AGENT CAD MODELING PIPELINE - END-TO-END SIMULATION")
    print("=" * 80)
    print("Prompt: 'Industrial flange disc with 4 mounting holes and central bore'")
    print("Starting agent multi-turn visual self-correction cycle...\n")

    result = run_simulation()

    print("\n" + "=" * 80)
    print("GENERATED FILE ARTIFACT STRUCTURE")
    print("=" * 80)
    for r_idx, files in sorted(result["artifacts_snapshot"].items()):
        print(f"Round {r_idx}:")
        for f in files:
            print(f"  +-- {f['relative_path']:<35} ({f['size_bytes']:>7} bytes)")

    print("\n" + "=" * 80)
    print("EXECUTION TIMING & PIPELINE METRICS")
    print("=" * 80)
    print(f"Loop Execution Duration   : {result['loop_duration']:.3f} s")
    print(f"Total Test Wall Time      : {result['total_duration']:.3f} s")
    print(f"Total Iteration Rounds    : {result['total_rounds']}")
    print(f"Final Inspection Score    : {result['final_score']} / 10.0")
    print(f"Convergence Status        : {'Converged' if result['converged'] else 'Failed'}")
    print(f"Progress Callbacks Fired  : {result['progress_event_count']}")
    print(f"Final IR Node Count       : {result['final_ir_node_count']}")

    print("\n" + "=" * 80)
    print("VERIFICATION CHECKPOINTS")
    print("=" * 80)
    print("[PASS] Checkpoint (a): Round 0 B-Rep geometry, STL/GLB & 4-view + annotated renders")
    print("[PASS] Checkpoint (b): Fallback heuristic critique detected missing 4-hole pattern")
    print("[PASS] Checkpoint (c): Visual repair patches cleanly applied to produce Round 1")
    print("[PASS] Checkpoint (d): Convergence achieved (score >= 9.0) with validated final IR DAG")
    print("[PASS] Checkpoint (e): 100% of artifact files have non-zero size")
    print("[PASS] Checkpoint (f): Temporary directory cleanly purged")

    print("\n" + "=" * 80)
    print(f"TEST VERDICT: {result['verdict']}")
    print("=" * 80)


if __name__ == "__main__":
    main()
