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
    box = shape.BoundingBox()
    return {
        "xmin": float(box.xmin), "xmax": float(box.xmax),
        "ymin": float(box.ymin), "ymax": float(box.ymax),
        "zmin": float(box.zmin), "zmax": float(box.zmax),
        "xlen": float(box.xlen), "ylen": float(box.ylen), "zlen": float(box.zlen),
    }


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
            "edge_curve_counts": edge_curve_counts,
            "bounds_mm": {key: round(value, 6) for key, value in bounds.items()},
        }
    except Exception as exc:
        empty["error"] = str(exc)[:300]
        return empty


__all__ = ["OCCT_FEATURE_API", "measure_occt_features"]
