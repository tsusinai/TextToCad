"""Constraint evaluation for Semantic CAD IR v0.2.

This first solver pass is deterministic and intentionally small: it resolves
numeric parameter expressions and evaluates range/manufacturing constraints.
Topology and geometric constraints remain deferred in the scalar solver; the executor now resolves basic OCCT selectors, while full geometric relation solving is still reported for review.
"""
from __future__ import annotations

import operator
from typing import Any

try:
    from .ir_executor import _resolve
except ImportError:  # pragma: no cover
    from ir_executor import _resolve


_OPERATORS = {
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
    "==": operator.eq,
    "=": operator.eq,
}


def _parameter_values(parameters: dict[str, Any]) -> dict[str, Any]:
    return {
        name: _resolve(value, parameters)
        for name, value in parameters.items()
    }


def _target_name(constraint: dict[str, Any], parameters: dict[str, Any]) -> str | None:
    parameter = constraint.get("parameter")
    if isinstance(parameter, str) and parameter in parameters:
        return parameter
    target = constraint.get("target")
    if isinstance(target, str) and target in parameters:
        return target
    return None


def solve_constraints(
    ir: dict[str, Any],
    *,
    process_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate constraints and return explainable hard/soft violations."""
    parameters = ir.get("parameters") or {}
    resolved = _parameter_values(parameters)
    violations: list[dict[str, Any]] = []
    evaluated = 0
    deferred = 0

    def add(constraint: dict[str, Any], status: str, message: str, value: Any = None, limit: Any = None) -> None:
        violations.append({
            "id": constraint.get("id"),
            "type": constraint.get("type"),
            "severity": "error" if constraint.get("hard", False) else "warning",
            "status": status,
            "message": message,
            "value": value,
            "limit": limit,
            "hard": bool(constraint.get("hard", False)),
        })

    for constraint in ir.get("constraints") or []:
        kind = str(constraint.get("type", ""))
        name = _target_name(constraint, parameters)
        if kind in {"range", "manufacturing", "process_rule", "profile_rule"} and name:
            value = resolved.get(name)
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                add(constraint, "failed", f"parameter '{name}' is not numeric", value=value)
                continue
            evaluated += 1
            minimum = constraint.get("min_mm", constraint.get("minimum_mm"))
            maximum = constraint.get("max_mm", constraint.get("maximum_mm"))
            if kind in {"process_rule", "manufacturing"} and minimum is None and process_profile:
                minimum = process_profile.get("min_wall") if name == "wall" else None
            failed = False
            if minimum is not None and numeric < float(minimum):
                failed = True
                add(constraint, "violated", f"{name}={numeric:g} is below minimum {float(minimum):g}", numeric, minimum)
            if maximum is not None and numeric > float(maximum):
                failed = True
                add(constraint, "violated", f"{name}={numeric:g} exceeds maximum {float(maximum):g}", numeric, maximum)
            if not failed:
                operator_name = constraint.get("operator")
                expected = constraint.get("value")
                if operator_name in _OPERATORS and expected is not None:
                    expected_value = float(_resolve(expected, parameters))
                    if not _OPERATORS[operator_name](numeric, expected_value):
                        failed = True
                        add(constraint, "violated", f"{name}={numeric:g} fails {operator_name} {expected_value:g}", numeric, expected_value)
            if not failed:
                continue
        elif kind in {"range", "manufacturing", "process_rule", "profile_rule"}:
            deferred += 1
            add(constraint, "deferred", "constraint target is not a parameter")
        else:
            deferred += 1
            add(constraint, "deferred", f"constraint type '{kind}' requires geometry validation")

    hard_violations = [item for item in violations if item["severity"] == "error" and item["status"] == "violated"]
    return {
        "valid": not hard_violations,
        "evaluated": evaluated,
        "deferred": deferred,
        "hard_violation_count": len(hard_violations),
        "violations": violations,
        "parameters": resolved,
    }
