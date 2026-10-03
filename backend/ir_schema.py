"""Versioned, family-independent Semantic CAD IR models.

The IR is intentionally data-only. It can be validated and inspected without
starting CadQuery; an executor is the only component allowed to turn operations
into kernel calls.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


IR_SCHEMA_VERSION = "0.2"
IR_ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_-]{0,63}$"


class IRBaseModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class IRParameter(IRBaseModel):
    value: Any
    unit: str = "mm"
    source: Literal[
        "user", "parser", "llm", "derived", "default", "inferred", "system", "legacy"
    ] = "derived"
    role: str = "dimension"
    constraint: str | None = None
    status: str = "resolved"
    expression: str | None = None


class IRDatum(IRBaseModel):
    id: str
    type: str
    origin: list[float] | None = None
    normal: list[float] | None = None
    direction: list[float] | None = None
    reference: str | None = None
    description: str | None = None


class IRNode(IRBaseModel):
    id: str
    kind: str
    operation: str
    inputs: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    frame: str | None = None
    status: str = "planned"
    actual_operation: str | None = None


class IRConstraint(IRBaseModel):
    id: str
    type: str
    target: str | list[str] | None = None
    parameter: str | None = None
    operator: str | None = None
    value: Any = None
    reference: str | None = None
    hard: bool = False


class IROutput(IRBaseModel):
    id: str
    node: str
    format: list[str] = Field(default_factory=lambda: ["step", "stl", "glb"])


class CADIRDocument(IRBaseModel):
    schema_version: Literal["0.2"] = IR_SCHEMA_VERSION
    document: dict[str, Any] = Field(default_factory=dict)
    units: str = "mm"
    process: str = "fdm"
    parameters: dict[str, IRParameter] = Field(default_factory=dict)
    datums: list[IRDatum] = Field(default_factory=list)
    nodes: list[IRNode] = Field(default_factory=list)
    constraints: list[IRConstraint] = Field(default_factory=list)
    outputs: list[IROutput] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    builder: str = "CadQuery/OCCT"
    # v0.1 clients used this name. It remains an explicitly documented
    # compatibility alias while nodes becomes the canonical field.
    features: list[dict[str, Any]] = Field(default_factory=list)


class IRValidationIssue(IRBaseModel):
    code: str
    message: str
    path: str | None = None
    severity: Literal["error", "warning"] = "error"


class IRValidationResult(IRBaseModel):
    valid: bool
    schema_version: str = IR_SCHEMA_VERSION
    issues: list[IRValidationIssue] = Field(default_factory=list)
    ir: CADIRDocument | None = None
