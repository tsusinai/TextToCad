from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

try:
    import cadquery as cq
    from cadquery import exporters
    CADQUERY_ERROR = ""
except ImportError as exc:  # pragma: no cover - container configuration issue
    cq = None
    exporters = None
    CADQUERY_ERROR = str(exc)


APP_DIR = Path(__file__).resolve().parent
ARTIFACT_ROOT = Path(os.getenv("ARTIFACT_ROOT", APP_DIR / "artifacts"))
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
MAX_PROMPT_LENGTH = 4000


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=MAX_PROMPT_LENGTH)
    units: Literal["mm"] = "mm"


class ModelParameters(BaseModel):
    kind: str
    width: float
    depth: float
    height: float
    compartments: int
    chamfer: float
    wall: float
    bottom: float


class GenerateResponse(BaseModel):
    model_id: str
    title: str
    parameters: ModelParameters
    checks: dict[str, bool]
    artifacts: dict[str, str]


def _number_after(text: str, patterns: list[str]) -> float | None:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def _word_number(text: str) -> int | None:
    words = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
        "five": 5, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
        "五": 5,
    }
    for word, value in words.items():
        if re.search(rf"(?:{word})\s*(?:compartments?|sections?|隔间|格)", text, re.I):
            return value
    match = re.search(r"(\d+)\s*(?:compartments?|sections?|隔间|格)", text, re.I)
    return int(match.group(1)) if match else None


def _bounded(value: float, minimum: float, maximum: float) -> float:
    return round(max(minimum, min(maximum, value)), 2)


def parse_prompt(prompt: str) -> tuple[str, ModelParameters]:
    text = " ".join(prompt.strip().lower().split())
    if not text:
        raise ValueError("prompt must contain a shape description")

    if any(token in text for token in ("tray", "shallow", "托盘", "盘")):
        kind = "tray"
        title = "Parametric storage tray"
    elif any(token in text for token in ("organizer", "desk", "收纳", "隔间", "桌面")):
        kind = "organizer"
        title = "Parametric desk organizer"
    elif any(token in text for token in ("clip", "cable", "wire", "线缆", "电缆", "夹")):
        kind = "clip"
        title = "Parametric cable clip"
    else:
        kind = "block"
        title = "Parametric solid"

    unit_numbers = [
        float(value)
        for value in re.findall(r"(?<![a-z])(?<!\d)(\d+(?:\.\d+)?)\s*(?:mm|毫米)\b", text)
    ]
    footprint = _number_after(text, [
        r"(?:footprint|占地|底面)\s*(?:of|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
    ])
    width = _number_after(text, [
        r"(?:width|wide|宽)\s*(?:is|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)?\s*(?:wide|width|宽)",
    ])
    depth = _number_after(text, [
        r"(?:depth|deep|length|长|深)\s*(?:is|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)?\s*(?:deep|depth|长|深)",
    ])
    height = _number_after(text, [
        r"(?:height|tall|高)\s*(?:is|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)?\s*(?:tall|height|高)",
    ])

    if footprint is not None:
        width = width or footprint
        depth = depth or footprint
    width = width or (unit_numbers[0] if unit_numbers else 120.0)
    depth = depth or (unit_numbers[1] if len(unit_numbers) > 1 else width * 0.67)
    default_height = 18.0 if kind == "tray" else 42.0 if kind == "organizer" else 24.0
    height = height or (unit_numbers[2] if len(unit_numbers) > 2 else default_height)

    compartments = _word_number(text)
    if compartments is None:
        compartments = 3 if kind == "organizer" else 1
    compartments = int(max(1, min(12, compartments)))

    chamfer = _number_after(text, [
        r"(?:chamfer|radius|倒角|圆角|圆弧)\s*(?:of|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)?\s*(?:chamfer|radius|倒角|圆角)",
    ]) or 2.0

    wall = _number_after(text, [
        r"(?:wall|壁厚)\s*(?:of|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
    ]) or (3.0 if kind in ("tray", "organizer") else 2.0)
    bottom = _number_after(text, [
        r"(?:bottom|floor|底厚)\s*(?:of|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
    ]) or wall

    width = _bounded(width, 10.0, 1000.0)
    depth = _bounded(depth, 10.0, 1000.0)
    height = _bounded(height, 5.0, 1000.0)
    wall = _bounded(wall, 1.2, min(20.0, width / 3, depth / 3))
    bottom = _bounded(bottom, 1.2, min(height - 1.0, 20.0))
    chamfer = _bounded(chamfer, 0.0, min(width, depth, height) / 4)

    params = ModelParameters(
        kind=kind,
        width=width,
        depth=depth,
        height=height,
        compartments=compartments,
        chamfer=chamfer,
        wall=wall,
        bottom=bottom,
    )
    return title, params


def _rounded_edges(workplane: Any, radius: float) -> Any:
    if radius <= 0:
        return workplane
    try:
        return workplane.edges("|Z").fillet(radius)
    except Exception:
        # A valid sharp solid is preferable to failing the whole request when
        # a user asks for a radius that is too large for a local edge.
        return workplane


def build_geometry(params: ModelParameters) -> Any:
    if cq is None:
        raise RuntimeError(f"CadQuery is not installed: {CADQUERY_ERROR}")

    w, d, h = params.width, params.depth, params.height
    wall, bottom = params.wall, params.bottom
    outer = cq.Workplane("XY").box(w, d, h, centered=(True, True, False))
    outer = _rounded_edges(outer, params.chamfer)

    if params.kind in ("tray", "organizer"):
        inner_w = w - 2 * wall
        inner_d = d - 2 * wall
        inner_h = max(1.0, h - bottom)
        inner = cq.Workplane("XY").box(
            inner_w, inner_d, inner_h, centered=(True, True, False)
        ).translate((0, 0, bottom))
        shape = outer.cut(inner)

        if params.compartments > 1:
            cell_w = inner_w / params.compartments
            divider_height = max(1.0, h - bottom)
            for index in range(1, params.compartments):
                x = -inner_w / 2 + cell_w * index
                divider = cq.Workplane("XY").box(
                    wall, inner_d, divider_height, centered=(True, True, False)
                ).translate((x, 0, bottom))
                shape = shape.union(divider)
        return shape

    if params.kind == "clip":
        # A manufacturable cable clip: a rounded base plus a centered cable
        # relief cut. The cut opens from the top and leaves a strong bottom.
        relief_w = min(w * 0.55, max(4.0, w - 2 * wall))
        relief_d = min(d * 0.55, max(4.0, d - 2 * wall))
        relief = cq.Workplane("XY").box(
            relief_w, relief_d, max(1.0, h - wall),
            centered=(True, True, False),
        ).translate((0, 0, wall))
        return outer.cut(relief)

    return outer


def _validate_shape(shape: Any) -> dict[str, bool]:
    solid = shape.val()
    volume = float(solid.Volume())
    bbox = solid.BoundingBox()
    return {
        "valid_brep": bool(solid.isValid()),
        "single_solid": len(shape.solids().vals()) == 1,
        "positive_volume": volume > 0,
        "bounded": all(
            dimension > 0
            for dimension in (bbox.xlen, bbox.ylen, bbox.zlen)
        ),
    }


def _write_artifacts(model_id: str, shape: Any, title: str, params: ModelParameters, checks: dict[str, bool]) -> dict[str, str]:
    model_dir = ARTIFACT_ROOT / model_id
    model_dir.mkdir(parents=True, exist_ok=False)
    step_path = model_dir / "model.step"
    stl_path = model_dir / "model.stl"
    manifest_path = model_dir / "manifest.json"

    exporters.export(shape, str(step_path))
    exporters.export(shape, str(stl_path))
    manifest = {
        "model_id": model_id,
        "title": title,
        "parameters": params.model_dump(),
        "checks": checks,
        "formats": ["step", "stl"],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "step": f"/v1/models/{model_id}/download?format=step",
        "stl": f"/v1/models/{model_id}/download?format=stl",
        "manifest": f"/v1/models/{model_id}/manifest",
    }


app = FastAPI(
    title="TextToCad Geometry Backend",
    version="0.1.0",
    description="Natural-language parametric CAD generation with CadQuery/OCCT.",
)
origins = [
    item.strip()
    for item in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5173,https://tsusinai.github.io",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok" if cq is not None else "degraded",
        "engine": "CadQuery/OCCT",
        "cadquery_available": cq is not None,
        "cadquery_error": CADQUERY_ERROR or None,
    }


@app.post("/v1/models", response_model=GenerateResponse)
def generate_model(request: GenerateRequest) -> GenerateResponse:
    try:
        title, params = parse_prompt(request.prompt)
        shape = build_geometry(params)
        checks = _validate_shape(shape)
        if not all(checks.values()):
            raise ValueError(f"geometry validation failed: {checks}")
        model_id = uuid.uuid4().hex
        artifacts = _write_artifacts(model_id, shape, title, params, checks)
        return GenerateResponse(
            model_id=model_id,
            title=title,
            parameters=params,
            checks=checks,
            artifacts=artifacts,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"geometry generation failed: {exc}") from exc


@app.get("/v1/models/{model_id}/manifest")
def get_manifest(model_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", model_id):
        raise HTTPException(status_code=400, detail="invalid model id")
    manifest_path = ARTIFACT_ROOT / model_id / "manifest.json"
    if not manifest_path.exists():
        raise HTTPException(status_code=404, detail="model not found")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


@app.get("/v1/models/{model_id}/download")
def download_model(
    model_id: str,
    format: Literal["step", "stl"] = Query(default="step"),
) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{32}", model_id):
        raise HTTPException(status_code=400, detail="invalid model id")
    suffix = ".step" if format == "step" else ".stl"
    file_path = ARTIFACT_ROOT / model_id / f"model{suffix}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="model artifact not found")
    media_type = (
        "application/step"
        if format == "step"
        else "application/vnd.ms-pki.stl"
    )
    return FileResponse(file_path, media_type=media_type, filename=file_path.name)
