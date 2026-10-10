"""Static validation for Semantic CAD IR v0.2.

Validation is deliberately independent of CadQuery. It checks that an IR
document is bounded, references real objects, forms an acyclic DAG, and only
uses registered operations. Kernel validity is handled later by the executor.
"""
from __future__ import annotations

import re
import math
from typing import Any

from pydantic import ValidationError

try:
    from .ir_schema import CADIRDocument, IR_ID_PATTERN
    from .ir_registry import ALLOWED_OPERATIONS, validate_operation_node
except ImportError:  # pragma: no cover - direct backend module execution
    from ir_schema import CADIRDocument, IR_ID_PATTERN
    from ir_registry import ALLOWED_OPERATIONS, validate_operation_node


class IRValidationError(ValueError):
    def __init__(self, issues: list[dict[str, Any]]):
        self.issues = issues
        message = "; ".join(str(item.get("message", "")) for item in issues)
        super().__init__(message or "invalid Semantic CAD IR")


# The registry is the compatibility superset for the v0.1 planner and v0.2
# executor. New operations must be registered before the planner can emit them.
ALLOWED_KINDS = {
    "primitive", "feature", "sketch", "component", "operation", "inspection",
    "profile", "shell", "cut", "pattern", "edge", "divider", "union",
}
EXPRESSION_RE = re.compile(r"^[A-Za-z0-9_().]+(?:\s*(?:[+\-*/%()]|\*\*)\s*[A-Za-z0-9_().]+)*$")
TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
ID_RE = re.compile(IR_ID_PATTERN)


def _issue(code: str, message: str, path: str | None = None, severity: str = "error") -> dict[str, Any]:
    return {"code": code, "message": message, "path": path, "severity": severity}


def _expression_names(expression: str) -> set[str]:
    return {
        token
        for token in TOKEN_RE.findall(expression)
        if token not in {"mm", "cm", "m", "in"}
    }



def _validate_geometry_parameters(
    node: Any,
    path: str,
    issues: list[dict[str, Any]],
) -> None:
    """Validate cheap, operation-specific geometry contracts before the kernel."""
    operation = str(node.operation)
    values = node.parameters or {}

    def positive_number(value: Any, value_path: str) -> None:
        if isinstance(value, bool):
            issues.append(_issue("geometry_value", "geometry dimensions must be numeric", value_path))
            return
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)) or float(value) <= 0:
                issues.append(_issue("geometry_value", "geometry dimensions must be finite and greater than zero", value_path))

    if operation == "box":
        size = values.get("size")
        if size is not None:
            if not isinstance(size, (list, tuple)) or len(size) != 3:
                issues.append(_issue("box_size", "box.size must contain exactly three values", f"{path}.parameters.size"))
            else:
                for index, item in enumerate(size):
                    positive_number(item, f"{path}.parameters.size[{index}]")
        else:
            for name in ("width", "depth", "height"):
                if name in values:
                    positive_number(values[name], f"{path}.parameters.{name}")

    if operation in {"polygon_prism", "regular_polygon"}:
        sides = values.get("sides")
        if sides is not None and isinstance(sides, (int, float)) and (int(sides) != sides or not 3 <= int(sides) <= 64):
            issues.append(_issue("polygon_sides", "polygon sides must be an integer from 3 to 64", f"{path}.parameters.sides"))
        points = values.get("points")
        if operation == "polygon_prism" and points is None:
            issues.append(_issue("polygon_points", "polygon_prism requires explicit planar points", f"{path}.parameters.points"))
        if points is not None:
            if not isinstance(points, (list, tuple)) or len(points) < 3:
                issues.append(_issue("polygon_points", "polygon points must contain at least three vertices", f"{path}.parameters.points"))
            else:
                for point_index, point in enumerate(points):
                    if not isinstance(point, (list, tuple)) or len(point) not in {2, 3}:
                        issues.append(_issue("polygon_point", "polygon vertices must be [x,y] or [x,y,z]", f"{path}.parameters.points[{point_index}]"))
                        continue
                    try:
                        coordinates = [float(component) for component in point]
                    except (TypeError, ValueError):
                        issues.append(_issue("polygon_point", "polygon vertices must be numeric", f"{path}.parameters.points[{point_index}]"))
                        continue
                    if not all(math.isfinite(component) for component in coordinates):
                        issues.append(_issue("polygon_point", "polygon vertices must be finite", f"{path}.parameters.points[{point_index}]"))
                    if len(coordinates) == 3 and abs(coordinates[2]) > 1e-6:
                        issues.append(_issue("polygon_planarity", "polygon vertices must lie on the XY plane", f"{path}.parameters.points[{point_index}]"))
            if sides is not None and isinstance(sides, (int, float)) and isinstance(points, (list, tuple)) and len(points) != int(sides):
                issues.append(_issue("polygon_point_count", "polygon point count must match sides", f"{path}.parameters.points"))
        if operation == "regular_polygon" and points is None and not any(name in values for name in ("width", "depth", "diameter", "radius", "circumradius")):
            issues.append(_issue("polygon_definition", "regular_polygon needs points, a footprint, diameter, or radius", f"{path}.parameters"))

    if operation in {"extrude", "revolve"}:
        dimension = values.get("length", values.get("angle"))
        if dimension is not None and isinstance(dimension, (int, float)) and not math.isfinite(float(dimension)):
            issues.append(_issue("feature_value", "feature extent must be finite", f"{path}.parameters"))

def validate_ir(payload: dict[str, Any], *, max_nodes: int = 128, max_constraints: int = 256) -> dict[str, Any]:
    """Validate and normalize an IR document, raising IRValidationError on failure."""
    if not isinstance(payload, dict):
        raise IRValidationError([_issue("ir_type", "IR payload must be a JSON object", "$")])
    try:
        document = CADIRDocument.model_validate(payload)
    except ValidationError as exc:
        issues = [
            _issue("schema", error["msg"], ".".join(str(part) for part in error["loc"]))
            for error in exc.errors()
        ]
        raise IRValidationError(issues) from exc

    issues: list[dict[str, Any]] = []
    node_ids = [node.id for node in document.nodes]
    datum_ids = [datum.id for datum in document.datums]
    parameter_ids = list(document.parameters)
    for label, values in (("node", node_ids), ("datum", datum_ids), ("parameter", parameter_ids)):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        invalid = sorted({value for value in values if not ID_RE.fullmatch(value)})
        if duplicates:
            issues.append(_issue("duplicate_id", f"duplicate {label} id(s): {', '.join(duplicates)}", label))
        if invalid:
            issues.append(_issue("invalid_id", f"invalid {label} id(s): {', '.join(invalid)}", label))

    if len(document.nodes) > max_nodes:
        issues.append(_issue("node_limit", f"IR contains {len(document.nodes)} nodes; limit is {max_nodes}", "nodes"))
    if len(document.constraints) > max_constraints:
        issues.append(_issue("constraint_limit", f"IR contains {len(document.constraints)} constraints; limit is {max_constraints}", "constraints"))

    known_nodes = set(node_ids)
    known_datums = set(datum_ids)
    known_parameters = set(parameter_ids)
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}
    def validate_selector(selector: Any, path: str, input_ids: list[str] | None = None) -> None:
        if not isinstance(selector, dict):
            issues.append(_issue("selector_type", "selector must be an object", path))
            return
        entity = selector.get("entity")
        if not isinstance(entity, str) or entity not in known_nodes:
            issues.append(_issue("selector_entity", "selector entity must reference an existing node", f"{path}.entity"))
        elif input_ids is not None and entity not in input_ids:
            issues.append(_issue(
                "selector_input",
                "selector entity must be one of the operation inputs",
                f"{path}.entity",
            ))
        topology = selector.get("topology", "face")
        if topology not in {"solid", "shell", "face", "edge", "vertex"}:
            issues.append(_issue("selector_topology", f"topology '{topology}' is not registered", f"{path}.topology"))
        where = selector.get("where", [])
        if not isinstance(where, list):
            issues.append(_issue("selector_where", "selector where must be a list", f"{path}.where"))
        for where_index, clause in enumerate(where if isinstance(where, list) else []):
            if not isinstance(clause, dict) or len(clause) != 1:
                issues.append(_issue("selector_clause", "selector clauses must contain one property", f"{path}.where[{where_index}]"))
                continue
            property_name = next(iter(clause))
            if property_name not in {"normal", "position", "area", "parallel_to", "perpendicular_to", "axis", "index"}:
                issues.append(_issue("selector_property", f"selector property '{property_name}' is not registered", f"{path}.where[{where_index}]"))

    for index, node in enumerate(document.nodes):
        path = f"nodes[{index}]"
        if node.kind not in ALLOWED_KINDS:
            issues.append(_issue("kind_not_allowed", f"node kind '{node.kind}' is not registered", f"{path}.kind"))
        if node.operation not in ALLOWED_OPERATIONS:
            issues.append(_issue("operation_not_allowed", f"operation '{node.operation}' is not registered", f"{path}.operation"))
        else:
            issues.extend(validate_operation_node(node.model_dump(mode="json"), path))
        _validate_geometry_parameters(node, path, issues)
        for input_index, reference in enumerate(node.inputs):
            if reference not in known_nodes:
                issues.append(_issue("missing_reference", f"node input '{reference}' does not exist", f"{path}.inputs[{input_index}]"))
            else:
                adjacency[node.id].append(reference)
        if node.frame and node.frame not in known_datums:
            issues.append(_issue("missing_datum", f"frame '{node.frame}' does not exist", f"{path}.frame"))
        for name, value in node.parameters.items():
            if name in {"selector", "face_selector", "edge_selector"}:
                validate_selector(value, f"{path}.parameters.{name}", node.inputs)
            if isinstance(value, dict) and "selector" in value:
                validate_selector(value["selector"], f"{path}.parameters.{name}.selector", node.inputs)
            if name == "expression" and isinstance(value, str):
                if not EXPRESSION_RE.fullmatch(value.strip()):
                    issues.append(_issue("unsafe_expression", "parameter expression contains unsupported syntax", f"{path}.parameters.{name}"))
            if isinstance(value, dict) and isinstance(value.get("expression"), str):
                expression = value["expression"].strip()
                if not EXPRESSION_RE.fullmatch(expression):
                    issues.append(_issue("unsafe_expression", "parameter expression contains unsupported syntax", f"{path}.parameters.{name}.expression"))
                else:
                    missing = sorted(_expression_names(expression) - known_parameters - set(node.parameters))
                    if missing:
                        issues.append(_issue("unknown_parameter", f"expression references unknown name(s): {', '.join(missing)}", f"{path}.parameters.{name}.expression"))

    state: dict[str, int] = {}

    def visit(node_id: str) -> None:
        state[node_id] = 1
        for dependency in adjacency.get(node_id, []):
            if state.get(dependency) == 1:
                issues.append(_issue("cycle", f"feature graph contains a cycle at '{dependency}'", "nodes"))
            elif state.get(dependency, 0) == 0:
                visit(dependency)
        state[node_id] = 2

    for node_id in node_ids:
        if state.get(node_id, 0) == 0:
            visit(node_id)

    output_ids = set()
    for index, output in enumerate(document.outputs):
        path = f"outputs[{index}]"
        if output.id in output_ids:
            issues.append(_issue("duplicate_output", f"duplicate output id '{output.id}'", path))
        output_ids.add(output.id)
        if output.node not in known_nodes:
            issues.append(_issue("missing_output", f"output node '{output.node}' does not exist", f"{path}.node"))
        if not output.format:
            issues.append(_issue("empty_output", "output format list cannot be empty", f"{path}.format"))

    for index, constraint in enumerate(document.constraints):
        path = f"constraints[{index}]"
        targets = constraint.target if isinstance(constraint.target, list) else [constraint.target]
        for target in [item for item in targets if item]:
            if target not in known_nodes and target not in known_parameters and target not in known_datums:
                issues.append(_issue("missing_constraint_target", f"constraint target '{target}' does not exist", f"{path}.target"))
        if constraint.parameter and constraint.parameter not in known_parameters:
            issues.append(_issue("missing_constraint_parameter", f"constraint parameter '{constraint.parameter}' does not exist", f"{path}.parameter"))
        if constraint.reference and constraint.reference not in known_nodes and constraint.reference not in known_datums and constraint.reference not in known_parameters:
            issues.append(_issue("missing_constraint_reference", f"constraint reference '{constraint.reference}' does not exist", f"{path}.reference"))

    if issues:
        raise IRValidationError(issues)
    return document.model_dump(mode="json")
