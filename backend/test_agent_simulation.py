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
    from agent_loop import run_agent_modeling_loop
    from ir_validate import validate_ir
    from PIL import Image
except ImportError as err:
    raise ImportError(f"Required dependency missing for agent simulation: {err}") from err

logger = logging.getLogger("test_agent_simulation")


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
