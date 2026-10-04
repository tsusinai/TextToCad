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
            {
                "id": "triangle",
                "kind": "primitive",
                "operation": "polygon_prism",
                "parameters": {
                    "points": [[-30, -20], [30, -20], [0, 20]],
                    "height": 30,
                },
            },
            {
                "id": "regular_heptagon",
                "kind": "primitive",
                "operation": "regular_polygon",
                "parameters": {"sides": 7, "width": 60, "depth": 40, "height": 12},
            },
            {
                "id": "octagon",
                "kind": "primitive",
                "operation": "polygon_prism",
                "parameters": {
                    "points": [
                        [-55.432, -55.432, 0], [-22.989, -78.457, 0],
                        [22.989, -78.457, 0], [55.432, -55.432, 0],
                        [55.432, 55.432, 0], [22.989, 78.457, 0],
                        [-22.989, 78.457, 0], [-55.432, 55.432, 0]
                    ],
                    "height": 42,
                },
            },
        ],
        "constraints": [],
        "outputs": [
            {"id": "base_output", "node": "base", "format": ["step"]},
            {"id": "cavity_output", "node": "cavity", "format": ["step"]},
            {"id": "triangle_output", "node": "triangle", "format": ["step"]},
            {"id": "octagon_output", "node": "octagon", "format": ["step"]},
            {"id": "heptagon_output", "node": "regular_heptagon", "format": ["step"]},
        ],
    }
    execution = execute_ir(app.validate_ir(ir))
    assert execution["output_nodes"] == ["base", "cavity", "triangle", "octagon", "regular_heptagon"]
    triangle_metrics = app.shape_metrics(execution["output_shapes"]["triangle"])
    assert triangle_metrics["valid_brep"] is True
    assert triangle_metrics["bbox_mm"]["x"] == 60.0
    assert triangle_metrics["bbox_mm"]["y"] == 40.0
    assert triangle_metrics["bbox_mm"]["z"] == 30.0
    heptagon_metrics = app.shape_metrics(execution["output_shapes"]["regular_heptagon"])
    assert heptagon_metrics["valid_brep"] is True
    assert heptagon_metrics["bbox_mm"] == {"x": 60.0, "y": 40.0, "z": 12.0}
    octagon_metrics = app.shape_metrics(execution["output_shapes"]["octagon"])
    assert octagon_metrics["valid_brep"] is True
    assert octagon_metrics["bbox_mm"]["x"] == 110.864
    assert octagon_metrics["bbox_mm"]["y"] == 156.914
    assert octagon_metrics["bbox_mm"]["z"] == 42.0
    quality = app._output_quality(execution["output_shapes"])
    assert quality["valid"] is True
    assert quality["entity_count"] == 5

    print("kernel smoke passed", {
        "face_count": dfm["face_count"],
        "thickness_status": dfm["wall_thickness_analysis"]["status"],
        "ray_sampling": dfm["wall_thickness_analysis"]["normal_ray_sampling"],
        "outputs": execution["output_nodes"],
    })


if __name__ == "__main__":
    main()
