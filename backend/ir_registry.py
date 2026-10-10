"""Single source of truth for Semantic CAD IR operation contracts.

The planner, validator and repair loop used to maintain separate operation
allow-lists.  That made it easy for an Agent to emit an operation that the
validator accepted but the executor could not interpret.  This module keeps
the public vocabulary and the cheap plan-level contracts together while
leaving kernel-specific checks to :mod:`ir_executor`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OperationSpec:
    name: str
    category: str
    min_inputs: int = 0
    max_inputs: int | None = None
    required_params: tuple[str, ...] = ()
    parameter_alternatives: tuple[tuple[str, ...], ...] = ()
    output_kind: str = "solid"
    executor: str = "ir_executor"

    def validate(self, node: dict[str, Any], path: str) -> list[dict[str, Any]]:
        """Return deterministic contract errors for one planned node."""
        issues: list[dict[str, Any]] = []
        inputs = node.get("inputs") or []
        params = node.get("parameters") or {}
        if len(inputs) < self.min_inputs:
            issues.append({
                "code": "operation_inputs",
                "message": f"operation '{self.name}' requires at least {self.min_inputs} input(s)",
                "path": f"{path}.inputs",
                "severity": "error",
            })
        if self.max_inputs is not None and len(inputs) > self.max_inputs:
            issues.append({
                "code": "operation_inputs",
                "message": f"operation '{self.name}' accepts at most {self.max_inputs} input(s)",
                "path": f"{path}.inputs",
                "severity": "error",
            })
        for name in self.required_params:
            if name not in params:
                issues.append({
                    "code": "missing_operation_parameter",
                    "message": f"operation '{self.name}' requires parameter '{name}'",
                    "path": f"{path}.parameters.{name}",
                    "severity": "error",
                })
        for alternatives in self.parameter_alternatives:
            if not any(name in params for name in alternatives):
                names = " or ".join(alternatives)
                issues.append({
                    "code": "missing_operation_parameter",
                    "message": f"operation '{self.name}' requires one of: {names}",
                    "path": f"{path}.parameters",
                    "severity": "error",
                })
        return issues


def _spec(name: str, category: str, **kwargs: Any) -> OperationSpec:
    return OperationSpec(name=name, category=category, **kwargs)


_SPECS: tuple[OperationSpec, ...] = (
    _spec("box", "primitive"),
    _spec("cylinder", "primitive"),
    _spec("sphere", "primitive"),
    _spec("cone", "primitive"),
    _spec("torus", "primitive"),
    _spec("polygon_prism", "primitive", required_params=("points", "height")),
    _spec("regular_polygon", "primitive"),
    _spec("profile", "legacy"),
    _spec("sketch", "sketch", parameter_alternatives=(("geometry", "elements"),)),
    _spec("component", "legacy"),
    _spec("rounded_box", "legacy"),
    _spec("l_profile_extrusion", "legacy"),
    _spec("airframe_fusion", "legacy"),
    _spec("extrude", "feature", min_inputs=1, max_inputs=1, required_params=("length",)),
    _spec("revolve", "feature", min_inputs=1, max_inputs=1),
    _spec("sweep", "feature", min_inputs=2, max_inputs=2),
    _spec("loft", "feature", min_inputs=2),
    _spec("shell", "feature", min_inputs=1, max_inputs=1, required_params=("thickness",)),
    _spec("union", "boolean", min_inputs=1),
    _spec("cut", "boolean", min_inputs=1),
    _spec("intersect", "boolean", min_inputs=1),
    _spec("translate", "transform", min_inputs=1, max_inputs=1),
    _spec("rotate", "transform", min_inputs=1, max_inputs=1),
    # ``align`` remains a compatibility token until a deterministic alignment
    # frame operation is implemented by the generic executor.
    _spec("align", "legacy"),
    _spec("mirror", "transform", min_inputs=1, max_inputs=1),
    _spec("linear_pattern", "pattern", min_inputs=1, max_inputs=1),
    _spec("polar_pattern", "pattern", min_inputs=1, max_inputs=1),
    _spec("fillet", "edge", min_inputs=1, max_inputs=1),
    _spec("chamfer", "edge", min_inputs=1, max_inputs=1),
    # These operations are kept for v0.1 compatibility.  Their geometry is
    # produced by the legacy application builder rather than the generic
    # executor, so they intentionally have no generic input contract.
    _spec("cut_inner_volume", "legacy"),
    _spec("cut_inner_cylinder", "legacy"),
    _spec("cut_relief", "legacy"),
    _spec("cut_cylinders", "legacy"),
    _spec("cut_recess", "legacy"),
    _spec("union_l_legs", "legacy"),
    _spec("fuse_fuselage_wings_tail", "legacy"),
    _spec("check_single_solid", "inspection"),
    _spec("clearance_check", "inspection"),
    _spec("single_solid_check", "inspection"),
)

OPERATION_SPECS: dict[str, OperationSpec] = {item.name: item for item in _SPECS}
ALLOWED_OPERATIONS = frozenset(OPERATION_SPECS)


def get_operation_spec(operation: str) -> OperationSpec | None:
    return OPERATION_SPECS.get(str(operation).strip().lower())


def validate_operation_node(node: dict[str, Any], path: str) -> list[dict[str, Any]]:
    operation = str(node.get("operation", "")).strip().lower()
    spec = get_operation_spec(operation)
    if spec is None:
        return []
    return spec.validate(node, path)


def operation_contracts(*, include_legacy: bool = False) -> list[dict[str, Any]]:
    """Return a JSON-friendly API description for prompts and diagnostics."""
    return [
        {
            "operation": spec.name,
            "category": spec.category,
            "min_inputs": spec.min_inputs,
            "max_inputs": spec.max_inputs,
            "required_params": list(spec.required_params),
            "parameter_alternatives": [list(item) for item in spec.parameter_alternatives],
            "output_kind": spec.output_kind,
        }
        for spec in _SPECS
        if include_legacy or spec.category not in {"legacy", "inspection"}
    ]


__all__ = [
    "ALLOWED_OPERATIONS",
    "OPERATION_SPECS",
    "OperationSpec",
    "get_operation_spec",
    "operation_contracts",
    "validate_operation_node",
]
