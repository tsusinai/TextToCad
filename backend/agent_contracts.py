"""Structured intent and repair contracts shared by CAD Agent components.

The visual critic is useful for appearance, but it should not be the only
source of truth for functional features.  This module extracts a small,
auditable requirement specification and checks it against the IR graph before
the visual score can be accepted.
"""
from __future__ import annotations

import re
from typing import Any


_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twelve": 12, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _count_before(text: str, pattern: str) -> int | None:
    match = re.search(
        rf"(\d+|{'|'.join(map(re.escape, _NUMBER_WORDS))})\s*(?:x\s*)?(?:{pattern})",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    token = match.group(1).lower()
    return int(token) if token.isdigit() else _NUMBER_WORDS.get(token)


def extract_requirement_spec(prompt: str) -> dict[str, Any]:
    """Extract explicit functional requirements without inventing geometry."""
    text = " ".join(str(prompt).strip().lower().split())
    features: list[dict[str, Any]] = []

    def add(kind: str, label: str, pattern: str, **details: Any) -> None:
        if re.search(pattern, text, flags=re.IGNORECASE):
            item = {"kind": kind, "label": label, "required": True}
            item.update(details)
            features.append(item)

    hole_count = _count_before(text, r"(?:mounting\s+holes?|bolt\s+holes?|holes?|个?孔|个?安装孔|个?螺栓孔)")
    add(
        "hole_pattern" if hole_count or re.search(r"pattern|均布|圆周", text) else "hole",
        "hole pattern" if hole_count or re.search(r"pattern|均布|圆周", text) else "hole",
        r"hole|bore|through[- ]?hole|孔|通孔|内孔|穿孔|螺栓孔|安装孔",
        count=max(1, min(hole_count, 64)) if hole_count else None,
    )
    add("edge_treatment", "edge treatment", r"chamfer|fillet|rounded|round\s+edge|倒角|圆角|圆润")
    add("shell", "hollow shell", r"hollow|shell|pocket|掏空|抽壳|空心")
    add("slot", "slot or recess", r"slot|groove|keyway|recess|槽|凹槽|键槽")
    fin_count = _count_before(text, r"(?:fins?|ribs?|个?鳍片|个?加强筋)")
    add("fins", "fins or ribs", r"fin(?:ned)?|ribs?|web|heat\s*sink|鳍片|散热片|加强筋", count=fin_count)
    add("boss", "boss", r"boss|凸台|台座")
    add("dovetail", "dovetail profile", r"dovetail|燕尾")
    tooth_count = _count_before(text, r"(?:teeth|tooth|个?齿|个?轮齿)")
    add("gear", "gear teeth", r"gear|tooth|teeth|齿轮|轮齿", count=tooth_count)

    dimensions: list[dict[str, Any]] = []
    triplet = re.search(
        r"(\d+(?:\.\d+)?)\s*(mm|cm|m|in)?\s*[x×]\s*"
        r"(\d+(?:\.\d+)?)\s*(mm|cm|m|in)?\s*[x×]\s*"
        r"(\d+(?:\.\d+)?)\s*(mm|cm|m|in)?",
        text,
        flags=re.IGNORECASE,
    )
    if triplet:
        default_unit = next((triplet.group(i) for i in (2, 4, 6) if triplet.group(i)), "mm").lower()
        values = []
        for value, unit in ((triplet.group(1), triplet.group(2)), (triplet.group(3), triplet.group(4)), (triplet.group(5), triplet.group(6))):
            unit_name = (unit or default_unit).lower()
            values.append(round(float(value) * _UNIT_TO_MM.get(unit_name, 1.0), 6))
        dimensions.append({"kind": "bbox", "values_mm": values, "source": "dimension_triplet"})

    recognized = bool(features or dimensions or re.search(
        r"box|block|cube|cylinder|sphere|cone|torus|flange|disc|shaft|方块|立方|圆柱|球|圆锥|法兰|圆盘|轴",
        text,
        flags=re.IGNORECASE,
    ))
    return {
        "prompt": str(prompt)[:400],
        "features": features,
        "dimensions": dimensions,
        "recognized": recognized,
        "confidence": "explicit" if features or dimensions else ("low" if not recognized else "medium"),
    }


def verify_requirement_spec(
    spec: dict[str, Any],
    current_ir: dict[str, Any],
    metrics: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return hard feature gaps backed by the current graph and measurements."""
    nodes = [node for node in current_ir.get("nodes", []) if isinstance(node, dict)]
    operations = [str(node.get("operation", "")).lower() for node in nodes]
    graph_text = " ".join(
        f"{node.get('id', '')} {node.get('operation', '')} {node.get('parameters', {})}"
        for node in nodes
    ).lower()
    feature_metrics = (metrics or {}).get("feature_metrics", {}) if isinstance(metrics, dict) else {}
    occt_available = bool(feature_metrics.get("occt_available"))
    measured_hole_count = int(feature_metrics.get("hole_count", 0) or 0)
    measured_fin_count = int((feature_metrics.get("fin_candidates") or {}).get("candidate_count", 0) or 0)
    measured_dovetail_faces = int((feature_metrics.get("dovetail") or {}).get("sloped_face_count", 0) or 0)
    measured_gear_teeth = int((feature_metrics.get("gear") or {}).get("teeth_estimate", 0) or 0)
    measurement_summary = {
        "occt_available": occt_available,
        "hole_count": measured_hole_count,
        "fin_candidates": feature_metrics.get("fin_candidates", {}),
        "dovetail": feature_metrics.get("dovetail", {}),
        "gear": feature_metrics.get("gear", {}),
    }
    issues: list[dict[str, Any]] = []

    for feature in spec.get("features", []):
        kind = feature.get("kind")
        label = feature.get("label", kind)
        present = False
        if kind in {"hole", "hole_pattern"}:
            present = measured_hole_count > 0 if occt_available else any(op in {"cut", "cut_cylinders", "polar_pattern", "linear_pattern"} for op in operations)
            present = present or (not occt_available and ("hole" in graph_text or "bore" in graph_text or "cutter" in graph_text))
        elif kind == "edge_treatment":
            present = any(op in {"fillet", "chamfer"} for op in operations)
        elif kind == "shell":
            present = any(op in {"shell", "cut_inner_volume", "cut_inner_cylinder", "cut_recess"} for op in operations)
        elif kind == "slot":
            present = any(op == "cut_recess" for op in operations) or any(word in graph_text for word in ("slot", "groove", "keyway", "recess", "槽"))
        elif kind == "fins":
            present = measured_fin_count > 0 if occt_available else (
                any(op in {"linear_pattern", "polar_pattern"} for op in operations)
                or any(word in graph_text for word in ("fin", "rib", "heat_sink", "鳍", "散热"))
            )
        elif kind == "dovetail":
            present = measured_dovetail_faces >= 2 if occt_available else any(word in graph_text for word in ("dovetail", "燕尾"))
        elif kind == "gear":
            present = measured_gear_teeth > 0 if occt_available else (
                any(op == "polar_pattern" for op in operations)
                or "gear" in graph_text
                or "齿轮" in graph_text
            )
        else:
            present = kind in graph_text or str(label).lower() in graph_text
        if not present:
            issues.append({
                "code": "FEATURE_MISSING",
                "severity": "high",
                "feature": label,
                "issue": f"Prompt requests {label}, but the feature graph has no corresponding verifiable operation.",
                "repair_hint": f"Add or retrieve a typed '{kind}' feature before visual acceptance.",
            })

        expected_count = feature.get("count")
        if present and isinstance(expected_count, int) and expected_count > 1:
            actual_counts = [
                int(float((node.get("parameters") or {}).get("count")))
                for node in nodes
                if isinstance((node.get("parameters") or {}).get("count"), (int, float))
                and str(node.get("operation", "")).lower() in {"linear_pattern", "polar_pattern", "cut_cylinders"}
            ]
            cutter_count = sum(
                1 for node in nodes
                if str(node.get("id", "")).lower().startswith("cutter_")
            )
            actual = max(actual_counts or [0])
            if cutter_count:
                actual = max(actual, cutter_count)
            if occt_available and kind in {"hole", "hole_pattern"}:
                actual = max(actual, measured_hole_count)
            if occt_available and kind == "fins":
                actual = max(actual, measured_fin_count)
            if occt_available and kind == "gear":
                actual = max(actual, measured_gear_teeth)
            # A prompt may contain an additional central bore besides the
            # requested pattern, so B-Rep evidence is a lower-bound check.
            if actual < expected_count:
                issues.append({
                    "code": "FEATURE_COUNT_MISMATCH",
                    "severity": "high",
                    "feature": label,
                    "issue": f"Expected {expected_count} {label}, but the IR exposes {actual}.",
                    "evidence": {
                        "expected": expected_count,
                        "actual": actual,
                        "occt_measurement": measurement_summary if occt_available else None,
                    },
                    "repair_hint": "Use a typed pattern operation or regenerate the feature fragment with the requested count.",
                })

    for dimension in spec.get("dimensions", []):
        bbox = (metrics or {}).get("bbox_mm", {}) if isinstance(metrics, dict) else {}
        if dimension.get("kind") != "bbox" or not all(axis in bbox for axis in ("x", "y", "z")):
            continue
        expected = [float(item) for item in dimension.get("values_mm", [])]
        actual = [float(bbox[axis]) for axis in ("x", "y", "z")]
        if len(expected) == 3 and any(abs(a - e) > max(0.5, e * 0.08) for a, e in zip(actual, expected)):
            issues.append({
                "code": "DIMENSION_MISMATCH",
                "severity": "high",
                "feature": "overall dimensions",
                "issue": f"Measured bounding box {actual} mm does not match requested {expected} mm.",
                "evidence": {"expected_mm": expected, "actual_mm": actual},
                "repair_hint": "Correct the driving parameters or select another candidate plan.",
            })
    return issues


def make_repair_report(
    *,
    phase: str,
    code: str,
    message: str,
    severity: str = "high",
    node_id: str | None = None,
    evidence: dict[str, Any] | None = None,
    repair_hint: str | None = None,
    retryable: bool = True,
) -> dict[str, Any]:
    """Create the compact failure contract sent to the next repair attempt."""
    return {
        "phase": str(phase),
        "code": str(code),
        "severity": str(severity),
        "message": str(message)[:800],
        "node_id": node_id,
        "evidence": evidence or {},
        "repair_hint": repair_hint or "Regenerate only the failing feature fragment and re-run validation.",
        "retryable": bool(retryable),
    }


__all__ = ["extract_requirement_spec", "make_repair_report", "verify_requirement_spec"]
