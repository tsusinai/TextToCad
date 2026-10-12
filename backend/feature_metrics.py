"""OCCT-backed measurements for functional CAD features.

The visual critic and IR graph can suggest that a feature exists, but neither
proves that the final B-Rep contains it.  This module reads the exported
CadQuery shape through OCCT adaptors and returns conservative, JSON-safe
measurements.  A measurement is only used as a hard gate when the kernel can
identify it with sufficient confidence.
"""
from __future__ import annotations

import math
from typing import Any

try:
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    OCCT_FEATURE_API = True
    OCCT_FEATURE_ERROR = ""
except ImportError as exc:  # pragma: no cover - optional when CadQuery is absent
    BRepAdaptor_Curve = BRepAdaptor_Surface = None
    OCCT_FEATURE_API = False
    OCCT_FEATURE_ERROR = str(exc)


def _vector_tuple(vector: Any) -> tuple[float, float, float]:
    def component(lower: str, upper: str) -> float:
        value = getattr(vector, lower, None)
        if value is None:
            value = getattr(vector, upper, 0.0)
        if callable(value):
            value = value()
        return float(value)

    return (
        round(component("x", "X"), 6),
        round(component("y", "Y"), 6),
        round(component("z", "Z"), 6),
    )


def _norm(vector: tuple[float, float, float]) -> float:
    return math.sqrt(sum(item * item for item in vector))


def _unit(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = _norm(vector)
    if length <= 1e-12:
        return (0.0, 0.0, 0.0)
    return tuple(round(item / length, 6) for item in vector)


def _bbox(shape: Any) -> dict[str, float]:
    if isinstance(shape, dict):
        xmin = float(shape.get("xmin", 0.0))
        xmax = float(shape.get("xmax", 0.0))
        ymin = float(shape.get("ymin", 0.0))
        ymax = float(shape.get("ymax", 0.0))
        zmin = float(shape.get("zmin", 0.0))
        zmax = float(shape.get("zmax", 0.0))
        return {
            "xmin": xmin, "xmax": xmax,
            "ymin": ymin, "ymax": ymax,
            "zmin": zmin, "zmax": zmax,
            "xlen": float(shape.get("xlen", xmax - xmin)),
            "ylen": float(shape.get("ylen", ymax - ymin)),
            "zlen": float(shape.get("zlen", zmax - zmin)),
        }
    if hasattr(shape, "BoundingBox") and callable(shape.BoundingBox):
        box = shape.BoundingBox()
    elif hasattr(shape, "val") and callable(shape.val):
        val = shape.val()
        if hasattr(val, "BoundingBox") and callable(val.BoundingBox):
            box = val.BoundingBox()
        else:
            box = val
    else:
        box = shape
    xmin = float(getattr(box, "xmin", 0.0))
    xmax = float(getattr(box, "xmax", 0.0))
    ymin = float(getattr(box, "ymin", 0.0))
    ymax = float(getattr(box, "ymax", 0.0))
    zmin = float(getattr(box, "zmin", 0.0))
    zmax = float(getattr(box, "zmax", 0.0))
    return {
        "xmin": xmin, "xmax": xmax,
        "ymin": ymin, "ymax": ymax,
        "zmin": zmin, "zmax": zmax,
        "xlen": float(getattr(box, "xlen", xmax - xmin)),
        "ylen": float(getattr(box, "ylen", ymax - ymin)),
        "zlen": float(getattr(box, "zlen", zmax - zmin)),
    }


def _extract_solids(shape: Any) -> list[Any]:
    if shape is None:
        return []
    if isinstance(shape, (list, tuple)):
        solids: list[Any] = []
        for item in shape:
            solids.extend(_extract_solids(item))
        return solids
    if hasattr(shape, "Solids") and callable(shape.Solids):
        try:
            items = list(shape.Solids())
            if items:
                return items
        except Exception:
            pass
    if hasattr(shape, "val") and callable(shape.val):
        try:
            val = shape.val()
            if hasattr(val, "Solids") and callable(val.Solids):
                items = list(val.Solids())
                if items:
                    return items
            if val is not None and val is not shape:
                return [val]
        except Exception:
            pass
    return [shape]


def _orientation_name(face: Any) -> str:
    try:
        value = str(face.wrapped.Orientation()).upper()
        if value.endswith("FORWARD"):
            return "FORWARD"
        if value.endswith("REVERSED"):
            return "REVERSED"
        return value.split(".")[-1]
    except Exception:
        return "UNKNOWN"


def _axis_extent(bbox: dict[str, float], axis: tuple[float, float, float]) -> float:
    components = (bbox["xlen"], bbox["ylen"], bbox["zlen"])
    return round(sum(abs(axis[index]) * components[index] for index in range(3)), 6)


def _safe_surface(face: Any) -> tuple[Any, str] | None:
    if not OCCT_FEATURE_API:
        return None
    try:
        adaptor = BRepAdaptor_Surface(face.wrapped, True)
        surface_type = str(adaptor.GetType()).split(".")[-1].upper()
        return adaptor, surface_type
    except Exception:
        return None


def _safe_curve(edge: Any) -> str | None:
    if not OCCT_FEATURE_API:
        return None
    try:
        adaptor = BRepAdaptor_Curve(edge.wrapped)
        return str(adaptor.GetType()).split(".")[-1].upper()
    except Exception:
        return None


def _cluster_positions(values: list[float], tolerance: float = 0.5) -> list[list[float]]:
    clusters: list[list[float]] = []
    for value in sorted(values):
        if not clusters or abs(value - sum(clusters[-1]) / len(clusters[-1])) > tolerance:
            clusters.append([value])
        else:
            clusters[-1].append(value)
    return clusters


def _measure_fin_candidates(planar_faces: list[dict[str, Any]], bounds: dict[str, float]) -> dict[str, Any]:
    """Infer repeated thin ribs from paired OCCT side faces.

    A normal rectangular solid has at most one pair per principal axis.  A
    repeated fin array creates many paired side faces along one axis, which is
    a useful conservative discriminator without relying on feature names.
    """
    result: dict[str, Any] = {
        "candidate_count": 0,
        "axis": None,
        "pitch_mm": None,
        "confidence": "none",
    }
    height = max(bounds["zlen"], 1e-6)
    vertical = [
        face for face in planar_faces
        if abs(face["normal"][2]) < 0.15
        and face["center"][2] > bounds["zmin"] + height * 0.40
    ]
    for axis_index, axis_name in ((0, "x"), (1, "y")):
        faces = [face for face in vertical if abs(face["normal"][axis_index]) > 0.90]
        if len(faces) < 4:
            continue
        # A pair of opposing side faces defines one thin fin.  Repeated fins
        # produce at least two distinct pairs along the same axis.
        positions = [face["center"][axis_index] for face in faces]
        clusters = _cluster_positions(positions, tolerance=max(0.05, (bounds["xlen"] + bounds["ylen"]) * 0.002))
        if len(clusters) < 4:
            continue
        centers = [sum(cluster) / len(cluster) for cluster in clusters]
        pairs: list[float] = []
        index = 0
        while index + 1 < len(centers):
            gap = abs(centers[index + 1] - centers[index])
            if gap <= max(5.0, (bounds["xlen"] + bounds["ylen"]) * 0.08):
                pairs.append((centers[index] + centers[index + 1]) / 2.0)
                index += 2
            else:
                index += 1
        if len(pairs) < 2:
            continue
        pitches = [pairs[i + 1] - pairs[i] for i in range(len(pairs) - 1)]
        result = {
            "candidate_count": len(pairs),
            "axis": axis_name,
            "pitch_mm": round(sum(pitches) / len(pitches), 6),
            "pitch_values_mm": [round(value, 6) for value in pitches],
            "confidence": "high" if len(pairs) >= 3 else "medium",
        }
        break
    return result


def detect_vertical_stacking(
    shape: Any = None,
    *,
    solids: list[Any] | None = None,
    planar_faces: list[dict[str, Any]] | None = None,
    cylindrical_faces: list[dict[str, Any]] | None = None,
    bounds: dict[str, float] | None = None,
    tolerance: float = 0.5,
) -> dict[str, Any]:
    """Detect vertical stacking consistency in composite assemblies.

    Checks if sub-solids or upward faces extend vertically above the base
    component with proper horizontal alignment and non-zero elevation difference.
    """
    empty_result: dict[str, Any] = {
        "detected": False,
        "confidence": "none",
        "stage_count": 0,
        "base_zmin": 0.0,
        "base_zmax": 0.0,
        "stacked_height_mm": 0.0,
        "details": [],
    }

    # 1. Multi-solid analysis (explicit solids list or extracted from shape)
    raw_solids = solids if solids is not None else (_extract_solids(shape) if shape is not None else [])
    if len(raw_solids) >= 2:
        solid_boxes = [_bbox(s) for s in raw_solids]
        # Sort by zmin ascending; secondary sort by largest footprint
        sorted_indices = sorted(
            range(len(solid_boxes)),
            key=lambda i: (solid_boxes[i]["zmin"], -(solid_boxes[i]["xlen"] * solid_boxes[i]["ylen"]))
        )
        base_idx = sorted_indices[0]
        base_box = solid_boxes[base_idx]

        stacked_components: list[dict[str, Any]] = []
        for idx in sorted_indices[1:]:
            box = solid_boxes[idx]
            extends_above = box["zmax"] > base_box["zmax"] - tolerance
            rests_above_base = box["zmin"] >= base_box["zmin"] - tolerance

            overlap_x = max(0.0, min(base_box["xmax"], box["xmax"]) - max(base_box["xmin"], box["xmin"]))
            overlap_y = max(0.0, min(base_box["ymax"], box["ymax"]) - max(base_box["ymin"], box["ymin"]))
            has_xy_overlap = (overlap_x > tolerance) and (overlap_y > tolerance)

            center_x = (box["xmin"] + box["xmax"]) / 2.0
            center_y = (box["ymin"] + box["ymax"]) / 2.0
            center_in_base = (
                (base_box["xmin"] - tolerance <= center_x <= base_box["xmax"] + tolerance)
                and (base_box["ymin"] - tolerance <= center_y <= base_box["ymax"] + tolerance)
            )

            if extends_above and rests_above_base and (has_xy_overlap or center_in_base):
                stacked_components.append({
                    "index": idx,
                    "zmin": box["zmin"],
                    "zmax": box["zmax"],
                    "elevation_step_mm": round(box["zmin"] - base_box["zmin"], 6),
                })

        if stacked_components:
            overall_zmax = max(b["zmax"] for b in solid_boxes)
            return {
                "detected": True,
                "confidence": "high" if len(stacked_components) >= 1 else "medium",
                "stage_count": 1 + len(stacked_components),
                "base_zmin": round(base_box["zmin"], 6),
                "base_zmax": round(base_box["zmax"], 6),
                "stacked_height_mm": round(overall_zmax - base_box["zmin"], 6),
                "details": [
                    f"Detected {len(stacked_components)} component(s) stacked vertically above base "
                    f"([zmin={base_box['zmin']}, zmax={base_box['zmax']}] mm)"
                ],
            }

    # 2. Single B-Rep solid analysis using planar and cylindrical faces
    shape_bounds = bounds if bounds is not None else (_bbox(shape) if shape is not None else None)
    if shape_bounds is None or shape_bounds.get("zlen", 0.0) <= tolerance:
        return empty_result

    details: list[str] = []
    upward_faces = [
        f for f in (planar_faces or [])
        if f.get("normal", (0, 0, 0))[2] > 0.85
    ]
    distinct_z_levels: list[float] = []
    if upward_faces:
        z_positions = [f["center"][2] for f in upward_faces]
        clusters = _cluster_positions(z_positions, tolerance=max(tolerance, shape_bounds["zlen"] * 0.05))
        if len(clusters) >= 2:
            distinct_z_levels = [round(sum(c) / len(c), 6) for c in clusters]
            details.append(f"Found {len(distinct_z_levels)} distinct upward horizontal tiers at Z={distinct_z_levels} mm")

    vertical_cylinders = [
        c for c in (cylindrical_faces or [])
        if abs(c.get("axis", (0, 0, 0))[2]) > 0.85
        and c.get("center", (0, 0, 0))[2] > shape_bounds["zmin"] + shape_bounds["zlen"] * 0.20
    ]
    if vertical_cylinders:
        details.append(f"Found {len(vertical_cylinders)} vertical cylindrical stage(s) elevated above base")

    if distinct_z_levels or vertical_cylinders:
        base_zmin = shape_bounds["zmin"]
        base_zmax = distinct_z_levels[0] if distinct_z_levels else shape_bounds["zmin"] + shape_bounds["zlen"] * 0.5
        stage_count = max(len(distinct_z_levels), 2 if vertical_cylinders else 1)
        confidence = "high" if (distinct_z_levels and vertical_cylinders) or len(distinct_z_levels) >= 2 else "medium"
        return {
            "detected": True,
            "confidence": confidence,
            "stage_count": stage_count,
            "base_zmin": round(base_zmin, 6),
            "base_zmax": round(base_zmax, 6),
            "stacked_height_mm": round(shape_bounds["zlen"], 6),
            "details": details,
        }

    return empty_result


def detect_horizontal_protrusion(
    shape: Any = None,
    *,
    solids: list[Any] | None = None,
    cylindrical_faces: list[dict[str, Any]] | None = None,
    planar_faces: list[dict[str, Any]] | None = None,
    bounds: dict[str, float] | None = None,
    tolerance: float = 0.5,
) -> dict[str, Any]:
    """Detect horizontal protrusion in composite assemblies.

    Checks if features (such as a forward barrel, side-mounted wheels, or through-shafts)
    extend horizontally beyond the primary base body's bounding box.
    """
    empty_result: dict[str, Any] = {
        "detected": False,
        "confidence": "none",
        "axis": None,
        "direction": None,
        "protrusion_mm": 0.0,
        "base_extent_mm": 0.0,
        "total_extent_mm": 0.0,
        "feature_type": "none",
        "all_protrusions": [],
        "details": [],
    }

    # 1. Multi-solid analysis
    raw_solids = solids if solids is not None else (_extract_solids(shape) if shape is not None else [])
    if len(raw_solids) >= 2:
        solid_boxes = [_bbox(s) for s in raw_solids]
        main_idx = max(
            range(len(solid_boxes)),
            key=lambda i: solid_boxes[i]["xlen"] * solid_boxes[i]["ylen"] * solid_boxes[i]["zlen"]
        )
        base_box = solid_boxes[main_idx]
        base_vol = max(1e-6, base_box["xlen"] * base_box["ylen"] * base_box["zlen"])

        protrusions: list[dict[str, Any]] = []
        for idx, box in enumerate(solid_boxes):
            if idx == main_idx:
                continue
            vol = box["xlen"] * box["ylen"] * box["zlen"]
            is_slender = vol < base_vol * 0.5
            # Forward +Y
            if box["ymax"] > base_box["ymax"] + tolerance:
                protrusions.append({
                    "axis": "y",
                    "direction": "+y",
                    "protrusion_mm": round(box["ymax"] - base_box["ymax"], 6),
                    "base_extent_mm": round(base_box["ymax"], 6),
                    "total_extent_mm": round(box["ymax"], 6),
                    "feature_type": "sub_solid",
                    "solid_index": idx,
                    "is_slender": is_slender,
                })
            # Backward -Y
            if box["ymin"] < base_box["ymin"] - tolerance:
                protrusions.append({
                    "axis": "y",
                    "direction": "-y",
                    "protrusion_mm": round(base_box["ymin"] - box["ymin"], 6),
                    "base_extent_mm": round(base_box["ymin"], 6),
                    "total_extent_mm": round(box["ymin"], 6),
                    "feature_type": "sub_solid",
                    "solid_index": idx,
                    "is_slender": is_slender,
                })
            # Right +X
            if box["xmax"] > base_box["xmax"] + tolerance:
                protrusions.append({
                    "axis": "x",
                    "direction": "+x",
                    "protrusion_mm": round(box["xmax"] - base_box["xmax"], 6),
                    "base_extent_mm": round(base_box["xmax"], 6),
                    "total_extent_mm": round(box["xmax"], 6),
                    "feature_type": "sub_solid",
                    "solid_index": idx,
                    "is_slender": is_slender,
                })
            # Left -X
            if box["xmin"] < base_box["xmin"] - tolerance:
                protrusions.append({
                    "axis": "x",
                    "direction": "-x",
                    "protrusion_mm": round(base_box["xmin"] - box["xmin"], 6),
                    "base_extent_mm": round(base_box["xmin"], 6),
                    "total_extent_mm": round(box["xmin"], 6),
                    "feature_type": "sub_solid",
                    "solid_index": idx,
                    "is_slender": is_slender,
                })

        if protrusions:
            protrusions.sort(key=lambda p: (p["is_slender"], p["protrusion_mm"]), reverse=True)
            primary = protrusions[0]
            confidence = "high" if primary["is_slender"] or primary["protrusion_mm"] > 5.0 else "medium"
            return {
                "detected": True,
                "confidence": confidence,
                "axis": primary["axis"],
                "direction": primary["direction"],
                "protrusion_mm": primary["protrusion_mm"],
                "base_extent_mm": primary["base_extent_mm"],
                "total_extent_mm": primary["total_extent_mm"],
                "feature_type": primary["feature_type"],
                "all_protrusions": protrusions,
                "details": [
                    f"Solid #{primary['solid_index']} extends {primary['protrusion_mm']} mm in {primary['direction']} "
                    f"beyond main body (boundary at {primary['base_extent_mm']} mm)"
                ],
            }

    # 2. Single B-Rep solid analysis using cylindrical and planar faces
    shape_bounds = bounds if bounds is not None else (_bbox(shape) if shape is not None else None)
    if shape_bounds is None:
        return empty_result

    details: list[str] = []
    protrusions: list[dict[str, Any]] = []

    for cyl in cylindrical_faces or []:
        axis = cyl.get("axis", (0, 0, 0))
        center = cyl.get("center", (0, 0, 0))
        extent = cyl.get("extent_mm", 0.0)
        radius = cyl.get("radius_mm", 0.0)

        # Cylinder oriented along Y (e.g. forward-pointing barrel)
        if abs(axis[1]) > 0.85:
            cyl_max_y = center[1] + extent / 2.0
            if abs(cyl_max_y - shape_bounds["ymax"]) <= max(tolerance, 1.0):
                y_faces = [
                    f for f in (planar_faces or [])
                    if f.get("normal", (0, 0, 0))[1] > 0.85
                    and f.get("center", (0, 0, 0))[1] < shape_bounds["ymax"] - tolerance
                ]
                if y_faces:
                    main_face = max(y_faces, key=lambda f: f.get("area_mm2", 0.0))
                    main_y = main_face["center"][1]
                    protrusion = shape_bounds["ymax"] - main_y
                    if protrusion > tolerance:
                        protrusions.append({
                            "axis": "y",
                            "direction": "+y",
                            "protrusion_mm": round(protrusion, 6),
                            "base_extent_mm": round(main_y, 6),
                            "total_extent_mm": round(shape_bounds["ymax"], 6),
                            "feature_type": "cylinder",
                            "radius_mm": radius,
                        })
                elif extent > shape_bounds["ylen"] * 0.3:
                    base_y = shape_bounds["ymin"] + (shape_bounds["ymax"] - shape_bounds["ymin"]) * 0.6
                    protrusions.append({
                        "axis": "y",
                        "direction": "+y",
                        "protrusion_mm": round(shape_bounds["ymax"] - base_y, 6),
                        "base_extent_mm": round(base_y, 6),
                        "total_extent_mm": round(shape_bounds["ymax"], 6),
                        "feature_type": "cylinder",
                        "radius_mm": radius,
                    })

        # Cylinder oriented along X (e.g. transverse shaft or axle)
        elif abs(axis[0]) > 0.85:
            cyl_max_x = center[0] + extent / 2.0
            if abs(cyl_max_x - shape_bounds["xmax"]) <= max(tolerance, 1.0):
                x_faces = [
                    f for f in (planar_faces or [])
                    if f.get("normal", (0, 0, 0))[0] > 0.85
                    and f.get("center", (0, 0, 0))[0] < shape_bounds["xmax"] - tolerance
                ]
                if x_faces:
                    main_face = max(x_faces, key=lambda f: f.get("area_mm2", 0.0))
                    main_x = main_face["center"][0]
                    protrusion = shape_bounds["xmax"] - main_x
                    if protrusion > tolerance:
                        protrusions.append({
                            "axis": "x",
                            "direction": "+x",
                            "protrusion_mm": round(protrusion, 6),
                            "base_extent_mm": round(main_x, 6),
                            "total_extent_mm": round(shape_bounds["xmax"], 6),
                            "feature_type": "cylinder",
                            "radius_mm": radius,
                        })

    if not protrusions and planar_faces:
        for axis_idx, axis_name in ((1, "y"), (0, "x")):
            pos_faces = [f for f in planar_faces if f.get("normal", (0, 0, 0))[axis_idx] > 0.85]
            if len(pos_faces) >= 2:
                coords = [f["center"][axis_idx] for f in pos_faces]
                clusters = _cluster_positions(coords, tolerance=tolerance)
                if len(clusters) >= 2:
                    c_means = [sum(c) / len(c) for c in clusters]
                    high_faces = [f for f in pos_faces if abs(f["center"][axis_idx] - c_means[-1]) <= tolerance]
                    low_faces = [f for f in pos_faces if abs(f["center"][axis_idx] - c_means[-2]) <= tolerance]
                    high_area = sum(f.get("area_mm2", 0.0) for f in high_faces)
                    low_area = sum(f.get("area_mm2", 0.0) for f in low_faces)
                    if high_area < low_area * 0.6:
                        protrusions.append({
                            "axis": axis_name,
                            "direction": f"+{axis_name}",
                            "protrusion_mm": round(c_means[-1] - c_means[-2], 6),
                            "base_extent_mm": round(c_means[-2], 6),
                            "total_extent_mm": round(c_means[-1], 6),
                            "feature_type": "planar_step",
                        })

    if protrusions:
        protrusions.sort(key=lambda p: p["protrusion_mm"], reverse=True)
        primary = protrusions[0]
        details.append(
            f"Detected {primary['direction']} horizontal protrusion of {primary['protrusion_mm']} mm "
            f"via {primary['feature_type']}"
        )
        return {
            "detected": True,
            "confidence": "high" if primary["protrusion_mm"] > 5.0 else "medium",
            "axis": primary["axis"],
            "direction": primary["direction"],
            "protrusion_mm": primary["protrusion_mm"],
            "base_extent_mm": primary["base_extent_mm"],
            "total_extent_mm": primary["total_extent_mm"],
            "feature_type": primary["feature_type"],
            "all_protrusions": protrusions,
            "details": details,
        }

    return empty_result


def measure_occt_features(shape: Any) -> dict[str, Any]:
    """Measure feature evidence directly from a CadQuery/OCCT solid."""
    empty = {
        "occt_available": bool(OCCT_FEATURE_API),
        "error": None if OCCT_FEATURE_API else OCCT_FEATURE_ERROR,
        "cylindrical_faces": [],
        "hole_faces": [],
        "hole_count": 0,
        "hole_diameters_mm": [],
        "fin_candidates": {"candidate_count": 0, "confidence": "none"},
        "dovetail": {"sloped_face_count": 0, "angles_deg": [], "confidence": "none"},
        "gear": {"teeth_estimate": 0, "top_profile_circle_edges": 0, "confidence": "none"},
        "assembly": {
            "detected": False,
            "vertical_stacking": {
                "detected": False,
                "confidence": "none",
                "stage_count": 0,
                "base_zmin": 0.0,
                "base_zmax": 0.0,
                "stacked_height_mm": 0.0,
                "details": [],
            },
            "horizontal_protrusion": {
                "detected": False,
                "confidence": "none",
                "axis": None,
                "direction": None,
                "protrusion_mm": 0.0,
                "base_extent_mm": 0.0,
                "total_extent_mm": 0.0,
                "feature_type": "none",
                "all_protrusions": [],
                "details": [],
            },
            "confidence": "none",
        },
        "edge_curve_counts": {},
    }
    if shape is None or not OCCT_FEATURE_API:
        return empty
    try:
        solid = shape.val() if hasattr(shape, "val") and callable(shape.val) else shape
        bounds = _bbox(solid)
        cylindrical_faces: list[dict[str, Any]] = []
        planar_faces: list[dict[str, Any]] = []
        sloped_angles: list[float] = []
        edge_curve_counts: dict[str, int] = {}

        for edge in solid.Edges():
            curve_type = _safe_curve(edge)
            if curve_type:
                edge_curve_counts[curve_type] = edge_curve_counts.get(curve_type, 0) + 1

        for face in solid.Faces():
            center = _vector_tuple(face.Center())
            normal = _unit(_vector_tuple(face.normalAt()))
            surface = _safe_surface(face)
            if surface is None:
                continue
            adaptor, surface_type = surface
            area = round(float(face.Area()), 6)
            if surface_type.endswith("CYLINDER"):
                cylinder = adaptor.Cylinder()
                axis = _unit(_vector_tuple(cylinder.Axis().Direction()))
                face_bbox = _bbox(face)
                record = {
                    "radius_mm": round(float(cylinder.Radius()), 6),
                    "diameter_mm": round(float(cylinder.Radius()) * 2.0, 6),
                    "axis": axis,
                    "center": center,
                    "extent_mm": _axis_extent(face_bbox, axis),
                    "area_mm2": area,
                    "orientation": _orientation_name(face),
                    "likely_internal": _orientation_name(face) == "FORWARD",
                }
                cylindrical_faces.append(record)
            elif surface_type.endswith("PLANE"):
                planar_faces.append({
                    "center": center,
                    "normal": normal,
                    "area_mm2": area,
                    "edge_count": len(face.Edges()),
                    "face": face,
                })
                cardinality = max(abs(normal[0]), abs(normal[1]), abs(normal[2]))
                if cardinality < 0.985:
                    angle = math.degrees(math.acos(max(-1.0, min(1.0, cardinality))))
                    if angle > 1.0:
                        sloped_angles.append(round(angle, 6))

        hole_faces = [face for face in cylindrical_faces if face["likely_internal"]]
        top_faces = [
            face for face in planar_faces
            if face["normal"][2] > 0.95 and abs(face["center"][2] - bounds["zmax"]) <= max(1e-4, bounds["zlen"] * 1e-5)
        ]
        circle_counts = []
        for face in top_faces:
            count = sum(1 for edge in face["face"].Edges() if _safe_curve(edge) and _safe_curve(edge).endswith("CIRCLE"))
            if count:
                circle_counts.append(count)
        top_circle_count = max(circle_counts or [0])
        # A through hole contributes one circular boundary to the top face;
        # subtract measured internal cylinders before interpreting remaining
        # circular arcs as repeated gear teeth.
        teeth_estimate = max(0, top_circle_count - len(hole_faces))
        if teeth_estimate < 4:
            teeth_estimate = 0

        fin_candidates = _measure_fin_candidates(planar_faces, bounds)
        vertical_stacking = detect_vertical_stacking(
            solid,
            planar_faces=planar_faces,
            cylindrical_faces=cylindrical_faces,
            bounds=bounds,
        )
        horizontal_protrusion = detect_horizontal_protrusion(
            solid,
            cylindrical_faces=cylindrical_faces,
            planar_faces=planar_faces,
            bounds=bounds,
        )
        assembly_detected = vertical_stacking["detected"] or horizontal_protrusion["detected"]
        assembly_confidence = (
            "high" if (vertical_stacking["confidence"] == "high" or horizontal_protrusion["confidence"] == "high")
            else ("medium" if assembly_detected else "none")
        )

        return {
            "occt_available": True,
            "error": None,
            "cylindrical_faces": [{key: value for key, value in face.items()} for face in cylindrical_faces],
            "hole_faces": hole_faces,
            "hole_count": len(hole_faces),
            "hole_diameters_mm": sorted(round(float(face["diameter_mm"]), 6) for face in hole_faces),
            "fin_candidates": fin_candidates,
            "dovetail": {
                "sloped_face_count": len(sloped_angles),
                "angles_deg": sorted(sloped_angles),
                "confidence": "high" if len(sloped_angles) >= 2 else ("low" if sloped_angles else "none"),
            },
            "gear": {
                "teeth_estimate": teeth_estimate,
                "top_profile_circle_edges": top_circle_count,
                "confidence": "medium" if teeth_estimate else "none",
            },
            "assembly": {
                "detected": assembly_detected,
                "vertical_stacking": vertical_stacking,
                "horizontal_protrusion": horizontal_protrusion,
                "confidence": assembly_confidence,
            },
            "edge_curve_counts": edge_curve_counts,
            "bounds_mm": {key: round(value, 6) for key, value in bounds.items()},
        }
    except Exception as exc:
        empty["error"] = str(exc)[:300]
        return empty


__all__ = [
    "OCCT_FEATURE_API",
    "measure_occt_features",
    "detect_vertical_stacking",
    "detect_horizontal_protrusion",
]
