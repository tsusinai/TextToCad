"""Auditable, restricted IR repair patches.

Repairs are suggestions by default. Applying them is explicit and every patch
is validated again before it can reach the executor.
"""
from __future__ import annotations

import copy
from typing import Any

try:
    from .ir_validate import validate_ir
except ImportError:  # pragma: no cover
    from ir_validate import validate_ir


def suggest_repairs(ir: dict[str, Any], constraint_report: dict[str, Any]) -> list[dict[str, Any]]:
    parameters = ir.get("parameters") or {}
    patches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for violation in constraint_report.get("violations", []):
        if violation.get("status") != "violated":
            continue
        parameter = None
        for constraint in ir.get("constraints") or []:
            if constraint.get("id") == violation.get("id"):
                parameter = constraint.get("parameter")
                if not parameter and isinstance(constraint.get("target"), str):
                    parameter = constraint["target"]
                break
        if not isinstance(parameter, str) or parameter not in parameters or parameter in seen:
            continue
        limit = violation.get("limit")
        if not isinstance(limit, (int, float)):
            continue
        seen.add(parameter)
        patches.append({
            "op": "set_parameter",
            "parameter": parameter,
            "value": limit,
            "reason": violation.get("message"),
            "source": "deterministic_repair",
        })
    return patches


def apply_patches(ir: dict[str, Any], patches: list[dict[str, Any]]) -> dict[str, Any]:
    candidate = copy.deepcopy(ir)
    parameters = candidate.setdefault("parameters", {})
    nodes = candidate.setdefault("nodes", [])
    node_by_id = {node.get("id"): node for node in nodes if isinstance(node, dict)}
    for index, patch in enumerate(patches):
        if not isinstance(patch, dict):
            raise ValueError(f"patch[{index}] must be an object")
        operation = patch.get("op")
        if operation == "set_parameter":
            name = patch.get("parameter")
            if not isinstance(name, str) or name not in parameters:
                raise ValueError(f"patch[{index}] references an unknown parameter")
            current = parameters[name]
            if not isinstance(current, dict):
                current = {"value": current, "unit": "mm"}
            current["value"] = patch.get("value")
            current["source"] = "derived"
            current["status"] = "repaired"
            parameters[name] = current
        elif operation == "replace_node_parameter":
            node = node_by_id.get(patch.get("node"))
            name = patch.get("parameter")
            if node is None or not isinstance(name, str):
                raise ValueError(f"patch[{index}] references an unknown node")
            node.setdefault("parameters", {})[name] = patch.get("value")
        elif operation == "add_node":
            node = patch.get("node")
            if not isinstance(node, dict) or not node.get("id"):
                raise ValueError(f"patch[{index}] has an invalid node")
            if node["id"] in node_by_id:
                raise ValueError(f"patch[{index}] would duplicate node id")
            nodes.append(copy.deepcopy(node))
            node_by_id[node["id"]] = nodes[-1]
        elif operation == "remove_node":
            node_id = patch.get("node")
            if node_id not in node_by_id:
                raise ValueError(f"patch[{index}] references an unknown node")
            if any(node_id in (node.get("inputs") or []) for node in nodes if isinstance(node, dict)):
                raise ValueError(f"patch[{index}] cannot remove a referenced node")
            if any(output.get("node") == node_id for output in candidate.get("outputs", [])):
                raise ValueError(f"patch[{index}] cannot remove an output node")
            nodes[:] = [node for node in nodes if node.get("id") != node_id]
            node_by_id.pop(node_id, None)
        else:
            raise ValueError(f"patch[{index}] operation '{operation}' is not allowed")
    return validate_ir(candidate)
