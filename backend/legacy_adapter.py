"""Compatibility adapter from the v0.1 planner to Semantic CAD IR v0.2.

The adapter is intentionally one-way. Legacy parameters and feature records can
be upgraded for auditing and validation, while the new executor can eventually
consume the canonical nodes without knowing a model family.
"""
from __future__ import annotations

import copy
from typing import Any

try:
    from .ir_validate import validate_ir
except ImportError:  # pragma: no cover
    from ir_validate import validate_ir


_TYPE_TO_KIND = {
    "primitive": "primitive",
    "profile": "feature",
    "shell": "feature",
    "divider": "feature",
    "union": "feature",
    "cut": "feature",
    "pattern": "feature",
    "edge": "feature",
    "inspection": "inspection",
}


def _source_inputs(feature: dict[str, Any]) -> list[str]:
    references: list[str] = []
    for key in ("source", "input", "target"):
        value = feature.get(key)
        if isinstance(value, str) and value and value not in references:
            references.append(value)
    for key in ("sources", "inputs"):
        values = feature.get(key)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value and value not in references:
                    references.append(value)
    return references


def _parameter_values(feature: dict[str, Any]) -> dict[str, Any]:
    metadata = {
        "id", "type", "operation", "source", "input", "target", "sources",
        "inputs", "status", "actual_operation", "fallback", "selection",
    }
    return {key: copy.deepcopy(value) for key, value in feature.items() if key not in metadata}


def _convert_feature(feature: dict[str, Any]) -> dict[str, Any]:
    node = {
        "id": str(feature.get("id", "")),
        "kind": _TYPE_TO_KIND.get(str(feature.get("type", "feature")), "feature"),
        "operation": str(feature.get("actual_operation") or feature.get("operation") or "union"),
        "inputs": _source_inputs(feature),
        "parameters": _parameter_values(feature),
        "status": str(feature.get("status", "planned")),
    }
    if feature.get("selection") is not None:
        node["parameters"]["selection"] = feature["selection"]
    if feature.get("fallback") is not None:
        node["parameters"]["fallback"] = feature["fallback"]
    return node


def legacy_design_ir_to_v2(
    legacy: dict[str, Any],
    *,
    prompt: str | None = None,
    process: str | None = None,
    mode: str | None = None,
    llm_used: bool | None = None,
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Upgrade a v0.1 design_ir without changing its legacy feature list."""
    if not isinstance(legacy, dict):
        raise TypeError("legacy design IR must be a JSON object")
    if legacy.get("schema_version") == "0.2" and legacy.get("nodes"):
        return validate_ir(legacy)

    legacy_features = [
        copy.deepcopy(item)
        for item in legacy.get("features", [])
        if isinstance(item, dict)
    ]
    nodes = [_convert_feature(feature) for feature in legacy_features]
    node_ids = {node["id"] for node in nodes}
    for node in nodes:
        node["inputs"] = [reference for reference in node["inputs"] if reference in node_ids]

    legacy_parameters = legacy.get("parameters", {})
    parameters: dict[str, dict[str, Any]] = {}
    if isinstance(legacy_parameters, dict):
        for name, raw in legacy_parameters.items():
            if isinstance(raw, dict):
                parameter = copy.deepcopy(raw)
                parameter.setdefault("unit", "mm")
                parameter.setdefault("source", "legacy")
                parameter.setdefault("role", "dimension")
                parameter.setdefault("status", "resolved")
            else:
                parameter = {"value": raw, "unit": "mm", "source": "legacy", "role": "dimension"}
            parameters[str(name)] = parameter

    raw_datums = legacy.get("datums", {})
    datums: list[dict[str, Any]] = []
    if isinstance(raw_datums, dict):
        for datum_id, description in raw_datums.items():
            datums.append({
                "id": str(datum_id),
                "type": "plane",
                "description": str(description),
            })
    elif isinstance(raw_datums, list):
        datums = [copy.deepcopy(item) for item in raw_datums if isinstance(item, dict)]

    output_node = nodes[-1]["id"] if nodes else None
    outputs = [{
        "id": "main_solid",
        "node": output_node,
        "format": ["step", "stl", "glb"],
    }] if output_node else []

    design = copy.deepcopy(legacy.get("design", {}))
    if not isinstance(design, dict):
        design = {}
    design.setdefault("intent", (prompt or "")[:400])
    design["legacy_family_hint"] = design.get("id")
    design["ir_strategy"] = "legacy_adapter"

    upgraded = {
        "schema_version": "0.2",
        "document": {
            "id": str(design.get("id") or "revision"),
            "intent": str(design.get("intent") or "")[:400],
            "language": "und",
            "units": str(legacy.get("units") or "mm"),
        },
        "design": design,
        "units": str(legacy.get("units") or "mm"),
        "process": process or legacy.get("process") or "fdm",
        "parameters": parameters,
        "datums": datums,
        "nodes": nodes,
        "constraints": copy.deepcopy(legacy.get("constraints", [])),
        "outputs": outputs,
        "provenance": copy.deepcopy(provenance or legacy.get("provenance") or {}),
        "builder": str(legacy.get("builder") or "CadQuery/OCCT"),
        # Keep v0.1 clients working while nodes is canonical for v0.2.
        "features": legacy_features,
    }
    upgraded["provenance"].setdefault("mode", mode)
    upgraded["provenance"].setdefault("llm_used", llm_used)
    return validate_ir(upgraded)
