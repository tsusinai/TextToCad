"""Family-independent Semantic CAD IR executor.

Only registered operations in this module may reach CadQuery. The executor is
kept separate from the HTTP layer so it can be tested with small IR documents
and later used by the main generation path.
"""
from __future__ import annotations

import ast
import math
from typing import Any

try:
    import cadquery as cq
except ImportError as exc:  # pragma: no cover
    cq = None
    CADQUERY_ERROR = str(exc)
else:
    CADQUERY_ERROR = ""


class IRExecutionError(RuntimeError):
    pass


def _resolve(value: Any, parameters: dict[str, Any]) -> Any:
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_resolve(item, parameters) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve(item, parameters) for item in value)
    if isinstance(value, dict):
        if "value" in value:
            return _resolve(value["value"], parameters)
        if "expression" in value:
            return _resolve(value["expression"], parameters)
        return {key: _resolve(item, parameters) for key, item in value.items()}
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text in parameters:
        raw = parameters[text]
        if isinstance(raw, dict):
            raw = raw.get("value")
        return _resolve(raw, parameters)
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        return value

    def evaluate(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in parameters:
            raw = parameters[node.id]
            if isinstance(raw, dict):
                raw = raw.get("value")
            resolved = _resolve(raw, parameters)
            if not isinstance(resolved, (int, float)):
                raise IRExecutionError(f"parameter '{node.id}' is not numeric")
            return float(resolved)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = evaluate(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow)):
            left = evaluate(node.left)
            right = evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if abs(right) <= 1e-12:
                    raise IRExecutionError("division by zero in parameter expression")
                return left / right
            if isinstance(node.op, ast.Mod):
                return left % right
            return left ** right
        raise IRExecutionError("unsupported parameter expression")

    try:
        return evaluate(tree)
    except IRExecutionError:
        raise
    except Exception as exc:
        raise IRExecutionError(f"invalid parameter expression '{text}'") from exc


def _number(parameters: dict[str, Any], value: Any, name: str, minimum: float = 0.0) -> float:
    resolved = _resolve(value, parameters)
    try:
        number = float(resolved)
    except (TypeError, ValueError) as exc:
        raise IRExecutionError(f"{name} must resolve to a number") from exc
    if not math.isfinite(number) or number <= minimum:
        raise IRExecutionError(f"{name} must be greater than {minimum}")
    return number


def _vector(parameters: dict[str, Any], value: Any, name: str, length: int = 3) -> tuple[float, ...]:
    resolved = _resolve(value, parameters)
    if not isinstance(resolved, (list, tuple)) or len(resolved) != length:
        raise IRExecutionError(f"{name} must contain {length} numbers")
    return tuple(float(item) for item in resolved)


def _workplane(frame: str | None) -> Any:
    if cq is None:
        raise IRExecutionError(f"CadQuery is not installed: {CADQUERY_ERROR}")
    return cq.Workplane((frame or "XY").upper())


def _as_shape(value: Any, node_id: str) -> Any:
    if value is None:
        raise IRExecutionError(f"node '{node_id}' did not produce a shape")
    return value


def _combine(inputs: list[Any], operation: str) -> Any:
    if len(inputs) < 2:
        raise IRExecutionError(f"{operation} requires at least two inputs")
    result = inputs[0]
    for item in inputs[1:]:
        if operation == "union":
            result = result.union(item)
        elif operation == "cut":
            result = result.cut(item)
        elif operation == "intersect":
            result = result.intersect(item)
    return result


def _entity_tuple(entity: Any) -> tuple[float, float, float] | None:
    """Read a CadQuery/OCC vector without depending on one Vector API version."""
    try:
        value = entity.toTuple()
        if len(value) == 3:
            return tuple(float(item) for item in value)
    except Exception:
        pass
    try:
        return (float(entity.x), float(entity.y), float(entity.z))
    except Exception:
        return None


def _entity_direction(entity: Any, topology: str) -> tuple[float, float, float] | None:
    if topology == "face":
        for args in ((), (0.5, 0.5)):
            try:
                vector = entity.normalAt(*args)
                direction = _entity_tuple(vector)
                if direction is not None:
                    return direction
            except Exception:
                continue
        return None
    try:
        return _entity_tuple(entity.tangentAt(0.5))
    except Exception:
        return None


def _normalize_vector(vector: tuple[float, float, float]) -> tuple[float, float, float]:
    length = math.sqrt(sum(component * component for component in vector))
    if length <= 1e-12:
        raise IRExecutionError("selector direction cannot be zero")
    return tuple(component / length for component in vector)


def _selector_clause_matches(entity: Any, topology: str, clause: dict[str, Any]) -> bool:
    if len(clause) != 1:
        raise IRExecutionError("selector clauses must contain one property")
    property_name, expected = next(iter(clause.items()))
    if property_name == "index":
        return False
    if property_name in {"normal", "parallel_to", "perpendicular_to", "axis"}:
        if not isinstance(expected, (list, tuple)) or len(expected) != 3:
            raise IRExecutionError(f"selector '{property_name}' must contain three numbers")
        actual = _entity_direction(entity, topology)
        if actual is None:
            raise IRExecutionError(f"selector cannot read {topology} direction")
        actual_n = _normalize_vector(actual)
        expected_n = _normalize_vector(tuple(float(item) for item in expected))
        dot = sum(actual_n[index] * expected_n[index] for index in range(3))
        tolerance = 1e-3
        if property_name == "normal":
            return all(abs(actual_n[index] - expected_n[index]) <= tolerance for index in range(3))
        if property_name == "parallel_to" or property_name == "axis":
            return abs(abs(dot) - 1.0) <= tolerance
        return abs(dot) <= tolerance
    if property_name == "position":
        if not isinstance(expected, (list, tuple)) or len(expected) != 3:
            raise IRExecutionError("selector position must contain three numbers")
        try:
            actual = _entity_tuple(entity.Center())
        except Exception as exc:
            raise IRExecutionError("selector cannot read entity position") from exc
        if actual is None:
            raise IRExecutionError("selector cannot read entity position")
        tolerance = 1e-3
        return all(abs(actual[index] - float(expected[index])) <= tolerance for index in range(3))
    if property_name == "area":
        try:
            actual_area = float(entity.Area())
        except Exception as exc:
            raise IRExecutionError("selector cannot read entity area") from exc
        if isinstance(expected, (int, float)):
            return abs(actual_area - float(expected)) <= 1e-3
        if isinstance(expected, dict):
            minimum = expected.get("min", expected.get("minimum"))
            maximum = expected.get("max", expected.get("maximum"))
            if minimum is not None and actual_area < float(minimum):
                return False
            if maximum is not None and actual_area > float(maximum):
                return False
            return True
        raise IRExecutionError("selector area must be a number or min/max object")
    raise IRExecutionError(f"selector property '{property_name}' is not implemented")


def _topology_entity_key(entity: Any) -> str:
    try:
        return f"hash:{int(entity.hashCode())}"
    except Exception:
        return f"repr:{repr(entity)}"


def _finalize_selector_metadata(metadata: dict[str, Any], output_shape: Any) -> None:
    """Map selected input topology entities to the final output only when OCCT identity survives."""
    selected_entities = metadata.pop("_selected_entities", [])
    target = str(metadata.get("target_topology", "face"))
    collections = {
        "solid": "solids",
        "shell": "shells",
        "face": "faces",
        "edge": "edges",
        "vertex": "vertices",
    }
    collection_name = collections.get(target)
    if not selected_entities or collection_name is None:
        metadata["mapping_status"] = "unavailable"
        metadata["output_indices"] = []
        return
    try:
        output_entities = list(getattr(output_shape, collection_name)().vals())
    except Exception:
        metadata["mapping_status"] = "unavailable"
        metadata["output_indices"] = []
        return
    output_keys = {_topology_entity_key(entity): index for index, entity in enumerate(output_entities)}
    output_indices = [
        output_keys[_topology_entity_key(entity)]
        for entity in selected_entities
        if _topology_entity_key(entity) in output_keys
    ]
    metadata["output_indices"] = output_indices
    if len(output_indices) == len(selected_entities):
        metadata["mapping_status"] = "final_output"
    elif output_indices:
        metadata["mapping_status"] = "partial"
    else:
        metadata["mapping_status"] = "unmapped"


def _topology_selection(
    shape: Any,
    selector: dict[str, Any],
    target: str,
    metadata: dict[str, Any] | None = None,
) -> Any:
    if not isinstance(selector, dict):
        raise IRExecutionError("selector must be an object")
    source_topology = str(selector.get("topology", "face")).lower()
    collections = {
        "solid": "solids",
        "shell": "shells",
        "face": "faces",
        "edge": "edges",
        "vertex": "vertices",
    }
    collection_name = collections.get(source_topology)
    if collection_name is None:
        raise IRExecutionError(f"selector topology '{source_topology}' is not supported")
    collection = getattr(shape, collection_name)()
    entities = list(collection.vals())
    where = selector.get("where") or []
    if not isinstance(where, list):
        raise IRExecutionError("selector where must be a list")
    selected_pairs = [(entity, index) for index, entity in enumerate(entities)]
    for clause in where:
        if not isinstance(clause, dict) or len(clause) != 1:
            raise IRExecutionError("selector clauses must contain one property")
        if "index" in clause:
            try:
                index = int(clause["index"])
            except (TypeError, ValueError) as exc:
                raise IRExecutionError("selector index must be an integer") from exc
            if index < 0 or index >= len(entities):
                raise IRExecutionError("selector index is out of range")
            selected_pairs = [(entities[index], index)]
            continue
        selected_pairs = [
            (entity, index) for entity, index in selected_pairs
            if _selector_clause_matches(entity, source_topology, clause)
        ]
    if not selected_pairs:
        raise IRExecutionError("selector matched no topology entities")
    selected = [entity for entity, _ in selected_pairs]
    source_indices = [index for _, index in selected_pairs]

    if target == "edge" and source_topology == "face":
        expanded: list[Any] = []
        seen: set[str] = set()
        for face in selected:
            try:
                edges = face.Edges()
            except Exception as exc:
                raise IRExecutionError("selector cannot expand face edges") from exc
            for edge in edges:
                key = str(edge.hashCode()) if hasattr(edge, "hashCode") else repr(edge)
                if key not in seen:
                    seen.add(key)
                    expanded.append(edge)
        selected = expanded
    if target == "face" and source_topology == "edge":
        raise IRExecutionError("edge selector cannot be used as an open face selector")
    if metadata is not None:
        metadata.update({
            "source_topology": source_topology,
            "target_topology": target,
            "source_indices": source_indices,
            "_selected_entities": selected,

            "matched_indices": [
                index for index, entity in enumerate(list(getattr(shape, collections.get(target, "faces"))().vals()))
                if any(
                    (str(entity.hashCode()) if hasattr(entity, "hashCode") else repr(entity))
                    == (str(selected_entity.hashCode()) if hasattr(selected_entity, "hashCode") else repr(selected_entity))
                    for selected_entity in selected
                )
            ] if target != "solid" else source_indices,
            "matched_count": len(selected),
        })
    return shape.newObject(selected)


def _node_shape(
    node: dict[str, Any],
    inputs: list[Any],
    parameters: dict[str, Any],
    selector_metadata: dict[str, Any] | None = None,
) -> Any:
    operation = str(node.get("operation", ""))
    values = node.get("parameters") or {}
    frame = node.get("frame")

    if operation == "box":
        size = values.get("size")
        if size is None:
            size = [values.get("width"), values.get("depth"), values.get("height")]
        width, depth, height = (_number(parameters, item, f"box.{axis}") for item, axis in zip(size, ("width", "depth", "height")))
        centered = values.get("centered", (True, True, False))
        centered = tuple(bool(item) for item in _resolve(centered, parameters))
        return _workplane(frame).box(width, depth, height, centered=centered)
    if operation == "cylinder":
        radius_value = values.get("radius")
        if radius_value is None:
            diameter = values.get("diameter")
            radius_value = _number(parameters, diameter, "cylinder.diameter") / 2
        radius = _number(parameters, radius_value, "cylinder.radius")
        height = _number(parameters, values.get("height"), "cylinder.height")
        return _workplane(frame).circle(radius).extrude(height)
    if operation == "sphere":
        return _workplane(frame).sphere(_number(parameters, values.get("radius"), "sphere.radius"))
    if operation == "cone":
        height = _number(parameters, values.get("height"), "cone.height")
        radius1 = _number(parameters, values.get("radius1"), "cone.radius1")
        radius2 = _number(parameters, values.get("radius2", 0.01), "cone.radius2", -1e-12)
        return _workplane(frame).cone(height, radius1, radius2)
    if operation == "torus":
        major = _number(parameters, values.get("major_radius"), "torus.major_radius")
        minor = _number(parameters, values.get("minor_radius"), "torus.minor_radius")
        return _workplane(frame).torus(major, minor)
    if operation == "sketch":
        geometry = values.get("geometry", values.get("elements", []))
        if not isinstance(geometry, list) or not geometry:
            raise IRExecutionError("sketch requires a non-empty geometry list")
        sketch = _workplane(frame)
        for element in geometry:
            if not isinstance(element, dict):
                raise IRExecutionError("sketch geometry entries must be objects")
            kind = str(element.get("type", "")).lower()
            if kind in {"rectangle", "rect"}:
                width = _number(parameters, element.get("width"), "sketch.rectangle.width")
                height = _number(parameters, element.get("height"), "sketch.rectangle.height")
                sketch = sketch.rect(width, height, centered=bool(element.get("centered", True)))
            elif kind == "circle":
                sketch = sketch.circle(_number(parameters, element.get("radius"), "sketch.circle.radius"))
            elif kind in {"polygon", "polyline"}:
                points = _resolve(element.get("points"), parameters)
                if not isinstance(points, list) or len(points) < 3:
                    raise IRExecutionError("sketch polygon requires at least three points")
                sketch = sketch.polyline(points).close()
            else:
                raise IRExecutionError(f"unsupported sketch geometry '{kind}'")
        return sketch
    if operation == "polygon_prism":
        points = _resolve(values.get("points"), parameters)
        height = _number(parameters, values.get("height"), "polygon_prism.height")
        if not isinstance(points, list) or len(points) < 3:
            raise IRExecutionError("polygon_prism requires at least three points")
        return _workplane(frame).polyline(points).close().extrude(height)
    if operation == "sweep":
        if len(inputs) != 2:
            raise IRExecutionError("sweep requires a profile and a path input")
        profile, path = inputs
        return profile.sweep(path, isFrenet=bool(_resolve(values.get("is_frenet", False), parameters)))
    if operation == "loft":
        if len(inputs) < 2:
            raise IRExecutionError("loft requires at least two section inputs")
        sections = inputs[0]
        for section in inputs[1:]:
            sections = sections.add(section)
        return sections.loft(combine=bool(_resolve(values.get("combine", True), parameters)))
    if operation == "linear_pattern":
        if len(inputs) != 1:
            raise IRExecutionError("linear_pattern requires exactly one input")
        count = int(_number(parameters, values.get("count", 2), "linear_pattern.count", 0))
        spacing = _vector(parameters, values.get("spacing", [10, 0, 0]), "linear_pattern.spacing")
        result = inputs[0]
        for index in range(1, count):
            vector = tuple(component * index for component in spacing)
            result = result.union(inputs[0].translate(vector))
        return result
    if operation == "polar_pattern":
        if len(inputs) != 1:
            raise IRExecutionError("polar_pattern requires exactly one input")
        count = int(_number(parameters, values.get("count", 2), "polar_pattern.count", 0))
        angle = float(_resolve(values.get("angle", 360), parameters))
        axis = _vector(parameters, values.get("axis", [0, 0, 1]), "polar_pattern.axis")
        result = inputs[0]
        for index in range(1, count):
            result = result.union(inputs[0].rotate((0, 0, 0), axis, angle * index / count))
        return result
    if operation in {"union", "cut", "intersect"}:
        return _combine(inputs, operation)
    if operation == "translate":
        if len(inputs) != 1:
            raise IRExecutionError("translate requires exactly one input")
        return inputs[0].translate(_vector(parameters, values.get("vector", [0, 0, 0]), "translate.vector"))
    if operation == "rotate":
        if len(inputs) != 1:
            raise IRExecutionError("rotate requires exactly one input")
        axis = _vector(parameters, values.get("axis", [0, 0, 1]), "rotate.axis")
        angle = _number(parameters, values.get("angle", 0.01), "rotate.angle", -360.0)
        return inputs[0].rotate((0, 0, 0), axis, angle)
    if operation == "revolve":
        if len(inputs) != 1:
            raise IRExecutionError("revolve requires exactly one input")
        angle = _number(parameters, values.get("angle", 360), "revolve.angle", -360.0)
        axis_start = _vector(parameters, values.get("axis_start", [0, 0, 0]), "revolve.axis_start")
        axis_end = _vector(parameters, values.get("axis_end", [0, 0, 1]), "revolve.axis_end")
        return inputs[0].revolve(angle, axisStart=axis_start, axisEnd=axis_end)
    if operation == "extrude":
        if len(inputs) != 1:
            raise IRExecutionError("extrude requires exactly one input")
        return inputs[0].extrude(_number(parameters, values.get("length"), "extrude.length"))
    if operation in {"fillet", "chamfer"}:
        if len(inputs) != 1:
            raise IRExecutionError(f"{operation} requires exactly one input")
        structured_selector = values.get("selector") or values.get("face_selector") or values.get("edge_selector")
        radius = _number(parameters, values.get("radius", values.get("distance")), f"{operation}.radius")
        if isinstance(structured_selector, dict):
            edges = _topology_selection(inputs[0], structured_selector, "edge", selector_metadata)
        else:
            selection = values.get("selection")
            edges = inputs[0].edges(selection) if selection else inputs[0].edges()
        return getattr(edges, operation)(radius)
    if operation == "shell":
        if len(inputs) != 1:
            raise IRExecutionError("shell requires exactly one input")
        thickness = _number(parameters, values.get("thickness"), "shell.thickness")
        selector = values.get("selector") or values.get("face_selector")
        if isinstance(selector, dict):
            return _topology_selection(inputs[0], selector, "face", selector_metadata).shell(-thickness)
        selection = values.get("open_face", ">Z")
        return inputs[0].faces(selection).shell(-thickness)
    if operation == "mirror":
        if len(inputs) != 1:
            raise IRExecutionError("mirror requires exactly one input")
        plane = str(values.get("plane", "XY"))
        return inputs[0].mirror(plane)
    raise IRExecutionError(f"operation '{operation}' is not implemented by the IR executor")


def _topological_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {str(node["id"]): node for node in nodes}
    state: dict[str, int] = {}
    result: list[dict[str, Any]] = []

    def visit(node_id: str) -> None:
        if state.get(node_id) == 1:
            raise IRExecutionError(f"dependency cycle at '{node_id}'")
        if state.get(node_id) == 2:
            return
        state[node_id] = 1
        for dependency in by_id[node_id].get("inputs", []):
            if dependency not in by_id:
                raise IRExecutionError(f"missing node input '{dependency}'")
            visit(dependency)
        state[node_id] = 2
        result.append(by_id[node_id])

    for node in nodes:
        visit(str(node["id"]))
    return result


def execute_ir(ir: dict[str, Any]) -> dict[str, Any]:
    """Execute a validated generic IR and return shapes plus a stable trace."""
    if cq is None:
        raise IRExecutionError(f"CadQuery is not installed: {CADQUERY_ERROR}")
    nodes = ir.get("nodes", [])
    parameters = ir.get("parameters", {})
    ordered = _topological_nodes(nodes)
    shapes: dict[str, Any] = {}
    trace: list[dict[str, Any]] = []
    for node in ordered:
        node_id = str(node["id"])
        inputs = [shapes[reference] for reference in node.get("inputs", [])]
        selector_metadata: dict[str, Any] = {}
        shape = _node_shape(node, inputs, parameters, selector_metadata)
        shapes[node_id] = _as_shape(shape, node_id)
        if selector_metadata:
            _finalize_selector_metadata(selector_metadata, shapes[node_id])
        trace_event = {
            "id": node_id,
            "operation": node.get("operation"),
            "status": "succeeded",
            "inputs": list(node.get("inputs", [])),
        }
        selector = (node.get("parameters") or {}).get("selector")
        if not isinstance(selector, dict):
            selector = (node.get("parameters") or {}).get("face_selector") or (node.get("parameters") or {}).get("edge_selector")
        if isinstance(selector, dict):
            trace_event["selector"] = {
                "entity": selector.get("entity"),
                "topology": selector.get("topology", "face"),
                "where": selector.get("where", []),
            }
            if selector_metadata:
                trace_event["selector_matches"] = selector_metadata
        trace.append(trace_event)
    output_nodes = ir.get("outputs") or ([{"node": ordered[-1]["id"]}] if ordered else [])
    output_ids = [item.get("node") for item in output_nodes if isinstance(item, dict)]
    if not output_ids or any(not output_id or output_id not in shapes for output_id in output_ids):
        raise IRExecutionError("IR has no valid output node")
    output_shapes = {output_id: shapes[output_id] for output_id in output_ids}
    return {
        "shape": output_shapes[output_ids[0]],
        "output_shapes": output_shapes,
        "output_nodes": output_ids,
        "node_shapes": shapes,
        "trace": trace,
        "output_node": output_ids[0],
    }


def shape_metrics(shape: Any) -> dict[str, Any]:
    if cq is None:
        raise IRExecutionError("CadQuery is unavailable")
    solid = shape.val()
    bbox = solid.BoundingBox()
    return {
        "volume_mm3": round(float(solid.Volume()), 6),
        "bbox_mm": {
            "x": round(float(bbox.xlen), 6),
            "y": round(float(bbox.ylen), 6),
            "z": round(float(bbox.zlen), 6),
        },
        "solid_count": len(shape.solids().vals()),
        "face_count": len(solid.Faces()),
        "valid_brep": bool(solid.isValid()),
    }
