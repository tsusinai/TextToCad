"""Auditable, restricted IR repair patches.

Repairs are suggestions by default. Applying them is explicit and every patch
is validated again before it can reach the executor.
"""
from __future__ import annotations

import copy
import math
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


def _clean_target_id(raw_id: Any, node_by_id: dict[str, Any], candidate: dict[str, Any], nodes: list[dict[str, Any]]) -> str | None:
    fallback_id = None
    if candidate.get("outputs"):
        fallback_id = candidate["outputs"][0].get("node")
    elif nodes:
        fallback_id = nodes[-1].get("id")
    # An omitted target can safely mean the current output. An explicitly
    # unknown target must fail closed; silently falling back to another node
    # lets a critic patch the wrong feature.
    if not raw_id:
        return fallback_id or "base"
    sid = str(raw_id).strip()
    if ":" in sid:
        sid = sid.split(":")[0].strip()
    if sid in node_by_id:
        return sid
    sid_lower = sid.lower()
    for nid in node_by_id:
        if nid.lower() == sid_lower:
            return nid
    return None


def apply_patches(ir: dict[str, Any], patches: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not patches:
        return validate_ir(copy.deepcopy(ir))
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
        elif operation in {"add_node", "replace_node"}:
            node = patch.get("node")
            if not isinstance(node, dict) or not node.get("id"):
                raise ValueError(f"patch[{index}] has an invalid node")
            node_id = node["id"]
            if node_id in node_by_id:
                old_node = node_by_id[node_id]
                # Protect against destructive replacement of base primitive by a feature
                if old_node.get("kind") == "primitive" and (node.get("kind") == "feature" or node.get("inputs")):
                    node_id = f"{node_id}_feature"
                    node["id"] = node_id
                    nodes.append(copy.deepcopy(node))
                    node_by_id[node_id] = nodes[-1]
                else:
                    existing_idx = next(i for i, n in enumerate(nodes) if n.get("id") == node_id)
                    nodes[existing_idx] = copy.deepcopy(node)
                    node_by_id[node_id] = nodes[existing_idx]
            else:
                nodes.append(copy.deepcopy(node))
                node_by_id[node_id] = nodes[-1]

            current_output = candidate.get("outputs", [{}])[0].get("node")
            node_inputs = node.get("inputs") or []
            if current_output == node_id or current_output in node_inputs:
                if candidate.get("outputs"):
                    candidate["outputs"][0]["node"] = node_id
                else:
                    candidate["outputs"] = [{"id": "primary", "node": node_id, "format": ["step", "stl", "glb"]}]
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
        elif operation == "scale_parameter":
            name = patch.get("parameter")
            if not isinstance(name, str) or name not in parameters:
                raise ValueError(f"patch[{index}] references an unknown parameter '{name}'")
            factor = patch.get("factor")
            if not isinstance(factor, (int, float)) or not math.isfinite(float(factor)) or float(factor) <= 0 or float(factor) > 100:
                raise ValueError(f"patch[{index}] factor must be numeric")
            current = parameters[name]
            if not isinstance(current, dict):
                current = {"value": current, "unit": "mm"}
            val = current.get("value")
            if not isinstance(val, (int, float)):
                raise ValueError(f"patch[{index}] parameter '{name}' value must be numeric to scale")
            current["value"] = float(val) * float(factor)
            current["source"] = "derived"
            current["status"] = "repaired"
            parameters[name] = current
        elif operation == "add_hole_pattern":
            target_id = _clean_target_id(patch.get("target_node") or patch.get("node"), node_by_id, candidate, nodes)
            if not target_id or target_id not in node_by_id:
                raise ValueError(f"patch[{index}] references an unknown target_node '{target_id}'")

            try:
                raw_count = patch.get("count", 4)
                count = int(float(raw_count))
            except (ValueError, TypeError):
                count = 4
            if count < 1:
                raise ValueError(f"patch[{index}] count must be at least 1")
            count = max(1, min(count, 64))

            try:
                circle_radius = abs(float(patch.get("circle_radius", patch.get("pitch_radius", patch.get("radius", 20.0)))))
            except (ValueError, TypeError):
                circle_radius = 20.0
            if not math.isfinite(circle_radius):
                raise ValueError(f"patch[{index}] circle_radius must be finite")
            circle_radius = max(0.1, min(circle_radius, 1_000_000.0))

            if "hole_radius" in patch:
                try:
                    hole_radius = abs(float(patch["hole_radius"]))
                except (ValueError, TypeError):
                    hole_radius = 2.0
            elif "hole_diameter" in patch:
                try:
                    hole_radius = abs(float(patch["hole_diameter"])) / 2.0
                except (ValueError, TypeError):
                    hole_radius = 2.0
            elif "diameter" in patch:
                try:
                    hole_radius = abs(float(patch["diameter"])) / 2.0
                except (ValueError, TypeError):
                    hole_radius = 2.0
            else:
                hole_radius = 2.0
            if not math.isfinite(hole_radius):
                raise ValueError(f"patch[{index}] hole radius must be finite")
            hole_radius = max(0.1, min(hole_radius, 1_000_000.0))

            try:
                depth = abs(float(patch.get("depth", 50.0)))
            except (ValueError, TypeError):
                depth = 50.0
            if not math.isfinite(depth):
                raise ValueError(f"patch[{index}] depth must be finite")
            depth = max(0.5, min(depth, 1_000_000.0))

            pat_idx = 1
            while any(f"cutter_{pat_idx}_{i}" in node_by_id for i in range(count)) or f"cut_hole_pattern_{pat_idx}" in node_by_id:
                pat_idx += 1

            cutter_ids = []
            for i in range(count):
                theta = 2.0 * math.pi * i / count
                cx = round(circle_radius * math.cos(theta), 4)
                cy = round(circle_radius * math.sin(theta), 4)
                cutter_id = f"cutter_{pat_idx}_{i}"
                cutter_node = {
                    "id": cutter_id,
                    "kind": "primitive",
                    "operation": "cylinder",
                    "inputs": [],
                    "parameters": {
                        "radius": hole_radius,
                        "height": depth * 2.0,
                        "position": [cx, cy, -depth * 0.5],
                    },
                }
                nodes.append(cutter_node)
                node_by_id[cutter_id] = cutter_node
                cutter_ids.append(cutter_id)

            cut_id = f"cut_hole_pattern_{pat_idx}"
            cut_node = {
                "id": cut_id,
                "kind": "feature",
                "operation": "cut",
                "inputs": [target_id] + cutter_ids,
                "parameters": {},
            }
            nodes.append(cut_node)
            node_by_id[cut_id] = cut_node

            updated_output = False
            if candidate.get("outputs"):
                for output in candidate["outputs"]:
                    if output.get("node") == target_id:
                        output["node"] = cut_id
                        updated_output = True
                if not updated_output:
                    candidate["outputs"][0]["node"] = cut_id
            else:
                candidate["outputs"] = [{"id": "primary", "node": cut_id, "format": ["step", "stl", "glb"]}]
        elif operation in {"add_chamfer", "add_fillet"}:
            actual_op = "chamfer" if operation == "add_chamfer" else "fillet"
            target_id = _clean_target_id(patch.get("target_node") or patch.get("node"), node_by_id, candidate, nodes)
            if not target_id or target_id not in node_by_id:
                raise ValueError(f"patch[{index}] references an unknown target_node '{target_id}'")

            raw_rad = patch.get("radius", patch.get("distance", 2.0))
            try:
                rad_val = float(raw_rad)
                if rad_val <= 0 or math.isnan(rad_val):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError(f"patch[{index}] radius/distance must be a positive number")

            edge_params: dict[str, Any] = {}
            if actual_op == "chamfer":
                edge_params["distance"] = float(rad_val)
                if "radius" in patch:
                    try:
                        edge_params["radius"] = float(patch["radius"])
                    except (ValueError, TypeError):
                        pass
            else:
                edge_params["radius"] = float(rad_val)

            if "selection" in patch:
                edge_params["selection"] = patch["selection"]
            if "edge_selector" in patch:
                edge_params["edge_selector"] = patch["edge_selector"]

            edge_idx = 1
            while f"{actual_op}_{edge_idx}" in node_by_id:
                edge_idx += 1
            edge_id = f"{actual_op}_{edge_idx}"

            edge_node = {
                "id": edge_id,
                "kind": "feature",
                "operation": actual_op,
                "inputs": [target_id],
                "parameters": edge_params,
            }
            nodes.append(edge_node)
            node_by_id[edge_id] = edge_node

            updated_output = False
            if candidate.get("outputs"):
                for output in candidate["outputs"]:
                    if output.get("node") == target_id:
                        output["node"] = edge_id
                        updated_output = True
                if not updated_output:
                    candidate["outputs"][0]["node"] = edge_id
            else:
                candidate["outputs"] = [{"id": "primary", "node": edge_id, "format": ["step", "stl", "glb"]}]
        elif operation == "shell_hollow":
            target_id = _clean_target_id(patch.get("target_node") or patch.get("node"), node_by_id, candidate, nodes)
            if not target_id or target_id not in node_by_id:
                raise ValueError(f"patch[{index}] references an unknown target_node '{target_id}'")

            raw_thick = patch.get("thickness", patch.get("wall_thickness", 2.0))
            try:
                thickness = float(raw_thick)
                if thickness <= 0 or math.isnan(thickness):
                    raise ValueError()
            except (ValueError, TypeError):
                raise ValueError(f"patch[{index}] thickness must be a positive number")

            open_face = str(patch.get("open_face") or ">Z")
            shell_idx = 1
            while f"shell_{shell_idx}" in node_by_id:
                shell_idx += 1
            shell_id = f"shell_{shell_idx}"

            shell_params: dict[str, Any] = {
                "thickness": float(thickness),
                "open_face": open_face,
            }
            if "selector" in patch:
                shell_params["selector"] = patch["selector"]

            shell_node = {
                "id": shell_id,
                "kind": "feature",
                "operation": "shell",
                "inputs": [target_id],
                "parameters": shell_params,
            }
            nodes.append(shell_node)
            node_by_id[shell_id] = shell_node

            updated_output = False
            if candidate.get("outputs"):
                for output in candidate["outputs"]:
                    if output.get("node") == target_id:
                        output["node"] = shell_id
                        updated_output = True
                if not updated_output:
                    candidate["outputs"][0]["node"] = shell_id
            else:
                candidate["outputs"] = [{"id": "primary", "node": shell_id, "format": ["step", "stl", "glb"]}]
        else:
            raise ValueError(f"patch[{index}] operation '{operation}' is not allowed")
    return validate_ir(candidate)
