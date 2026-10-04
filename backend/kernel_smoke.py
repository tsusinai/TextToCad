"""CadQuery/OCCT smoke checks for the geometry backend image.

This script intentionally avoids pytest so it can run inside the production-like
backend image. It validates thin-wall, cavity, ray-analysis metadata, and
family-independent multi-output execution.
"""
from __future__ import annotations

import app
from ir_executor import execute_ir


def main() -> None:
    if app.cq is None:
        detail = getattr(app, "CADQUERY_ERROR", "") or "unknown import error"
        raise SystemExit(f"CadQuery is unavailable in the kernel image: {detail}")

    outer = app.cq.Workplane("XY").box(40, 30, 20)
    inner = app.cq.Workplane("XY").box(36, 26, 18).translate((0, 0, 1))
    thin_wall = outer.cut(inner)
    assert thin_wall.val().isValid()
    assert thin_wall.val().Volume() > 0

    dfm = app._face_level_dfm(thin_wall, "fdm")
    assert dfm["face_count"] > 0
    assert dfm["wall_thickness_analysis"]["status"] in {"ray_sampled", "measured", "unavailable"}
    assert dfm["wall_thickness_analysis"]["normal_ray_sampling"] in {"available", "unavailable", "no_hit"}

    ir = {
        "schema_version": "0.2",
        "document": {"id": "kernel-smoke"},
        "nodes": [
            {
                "id": "base",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [20, 20, 10]},
            },
            {
                "id": "cavity",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [14, 14, 8]},
            },
        ],
        "constraints": [],
        "outputs": [
            {"id": "base_output", "node": "base", "format": ["step"]},
            {"id": "cavity_output", "node": "cavity", "format": ["step"]},
        ],
    }
    execution = execute_ir(app.validate_ir(ir))
    assert execution["output_nodes"] == ["base", "cavity"]
    quality = app._output_quality(execution["output_shapes"])
    assert quality["valid"] is True
    assert quality["entity_count"] == 2

    print("kernel smoke passed", {
        "face_count": dfm["face_count"],
        "thickness_status": dfm["wall_thickness_analysis"]["status"],
        "ray_sampling": dfm["wall_thickness_analysis"]["normal_ray_sampling"],
        "outputs": execution["output_nodes"],
    })


if __name__ == "__main__":
    main()
