from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import uuid
from threading import BoundedSemaphore, Lock, Thread
from pathlib import Path
from typing import Any, Literal
from zipfile import ZIP_DEFLATED, ZipFile

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

try:
    import trimesh
    TRIMESH_ERROR = ""
except ImportError as exc:  # pragma: no cover - optional preview dependency
    trimesh = None
    TRIMESH_ERROR = str(exc)


APP_DIR = Path(__file__).resolve().parent
ARTIFACT_ROOT = Path(os.getenv("ARTIFACT_ROOT", APP_DIR / "artifacts"))
ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
MAX_PROMPT_LENGTH = 4000
ARTIFACT_TTL_SECONDS = int(os.getenv("ARTIFACT_TTL_SECONDS", "86400"))
LLM_API_URL = os.getenv("LLM_API_URL", "https://api.openai.com/v1/chat/completions")
LLM_API_KEY = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "20"))
EXPORT_LOCK = Lock()

PROCESS_PROFILES: dict[str, dict[str, Any]] = {
    "fdm": {
        "label": "FDM / FFF",
        "min_wall": 1.2,
        "min_radius": 0.8,
        "max_overhang": 45.0,
        "draft_angle": 0.0,
        "tolerance": 0.2,
        "clearance": 0.3,
    },
    "sla": {
        "label": "SLA / Resin",
        "min_wall": 0.8,
        "min_radius": 0.4,
        "max_overhang": 60.0,
        "draft_angle": 0.0,
        "tolerance": 0.1,
        "clearance": 0.2,
    },
    "cnc": {
        "label": "CNC Milling",
        "min_wall": 2.0,
        "min_radius": 1.0,
        "max_overhang": 90.0,
        "draft_angle": 0.0,
        "tolerance": 0.1,
        "clearance": 0.1,
    },
    "injection": {
        "label": "Injection Molding",
        "min_wall": 1.5,
        "min_radius": 0.8,
        "max_overhang": 90.0,
        "draft_angle": 1.0,
        "tolerance": 0.05,
        "clearance": 0.2,
    },
}


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=MAX_PROMPT_LENGTH)
    units: Literal["mm"] = "mm"
    process: Literal["fdm", "sla", "cnc", "injection"] = "fdm"
    mode: Literal["standard", "advanced"] = "standard"


class ModelParameters(BaseModel):
    kind: str
    width: float
    depth: float
    height: float
    compartments: int
    chamfer: float
    wall: float
    bottom: float
    drainage_holes: int = 0
    cable_channel: bool = False
    process: str = "fdm"
    tolerance: float = 0.2
    clearance: float = 0.3


class GenerateResponse(BaseModel):
    model_id: str
    title: str
    parameters: ModelParameters
    checks: dict[str, bool]
    artifacts: dict[str, str]
    process: str
    profile: dict[str, Any]
    analysis: dict[str, Any]
    step_schema: str
    mode: str = "standard"
    llm_used: bool = False
    assumptions: list[str] = []


CACHE_LOCK = Lock()
MODEL_CACHE: dict[str, GenerateResponse] = {}
JOB_LOCK = Lock()
JOBS: dict[str, dict[str, Any]] = {}
MAX_CONCURRENT_JOBS = max(1, int(os.getenv("MAX_CONCURRENT_JOBS", "2")))
GENERATION_SEMAPHORE = BoundedSemaphore(MAX_CONCURRENT_JOBS)


def _cache_key(request: GenerateRequest) -> str:
    normalized = " ".join(request.prompt.strip().lower().split())
    return hashlib.sha256(f"{request.mode}\0{request.process}\0{request.units}\0{normalized}".encode("utf-8")).hexdigest()


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


def parse_prompt(prompt: str, process: str = "fdm") -> tuple[str, ModelParameters]:
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
    elif any(token in text for token in ("plant", "pot", "花盆", "植物")):
        kind = "plant"
        title = "Parametric plant pot"
    elif any(token in text for token in ("lamp", "灯")):
        kind = "lamp"
        title = "Parametric lamp base"
    elif any(token in text for token in ("pen", "笔")):
        kind = "pen"
        title = "Parametric pen cup"
    else:
        kind = "block"
        title = "Parametric solid"

    unit_numbers = [
        float(value)
        for value in re.findall(r"(?<![a-z])(?<!\d)(\d+(?:\.\d+)?)\s*(?:mm|毫米)\b", text)
    ]
    treatment_numbers = [
        float(value)
        for value in re.findall(
            r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)\s*(?:chamfer|radius|倒角|圆角|圆弧|半径|wall|壁厚|bottom|floor|底厚)",
            text,
            flags=re.IGNORECASE,
        )
    ]
    treatment_numbers.extend(
        float(value)
        for value in re.findall(
            r"(?:chamfer|radius|倒角|圆角|圆弧|半径|wall|壁厚|bottom|floor|底厚)[^\d]{0,12}(\d+(?:\.\d+)?)\s*(?:mm|毫米)?",
            text,
            flags=re.IGNORECASE,
        )
    )
    generic_numbers = unit_numbers[:]
    for value in treatment_numbers:
        if value in generic_numbers:
            generic_numbers.remove(value)
    footprint = _number_after(text, [
        r"(?:footprint|占地|底面)\s*(?:of|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)?\s*(?:footprint|占地|底面)",
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
    width = width or (generic_numbers[0] if generic_numbers else 120.0)
    square_base = any(token in text for token in ("footprint", "见方", "占地", "底面"))
    depth = depth or (width if square_base else (generic_numbers[1] if len(generic_numbers) > 1 else width * 0.67))
    default_height = (
        18.0 if kind == "tray"
        else 42.0 if kind == "organizer"
        else 82.0 if kind == "plant"
        else 95.0 if kind == "pen"
        else 40.0 if kind == "lamp"
        else 24.0
    )
    generic_height = next(
        (value for value in generic_numbers[2:] ),
        None,
    )
    height = height or (generic_height if generic_height is not None else default_height)

    compartments = _word_number(text)
    if compartments is None:
        compartments = 3 if kind == "organizer" else 1
    compartments = int(max(1, min(12, compartments)))

    chamfer = _number_after(text, [
        r"(?:chamfer|radius|倒角|圆角|圆弧|半径)\s*(?:of|为|是|[:=])?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*(?:mm|毫米)?\s*(?:chamfer|radius|倒角|圆角|圆弧|半径)",
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
        drainage_holes=3 if kind == "plant" else 0,
        cable_channel=kind == "lamp",
        process=process,
        tolerance=float(PROCESS_PROFILES[process]["tolerance"]),
        clearance=float(PROCESS_PROFILES[process]["clearance"]),
    )
    return title, params


def _llm_json(prompt: str, process: str, baseline: ModelParameters) -> dict[str, Any]:
    if not LLM_API_KEY:
        raise RuntimeError("advanced mode requires LLM_API_KEY or OPENAI_API_KEY")
    schema = {
        "kind": "tray|organizer|clip|plant|lamp|pen|block",
        "width": "number in mm", "depth": "number in mm", "height": "number in mm",
        "compartments": "integer 1-12", "wall": "number in mm", "bottom": "number in mm",
        "chamfer": "number in mm", "drainage_holes": "integer 0-4", "cable_channel": "boolean",
        "assumptions": ["short user-facing assumption"],
    }
    system = (
        "You are a CAD design intent parser. Convert the user request into only valid JSON. "
        "Do not output code or explanations. Keep dimensions in millimetres. "
        "Choose the closest supported kind and make conservative manufacturing assumptions. "
        f"Supported JSON shape: {json.dumps(schema)}. "
        f"The deterministic baseline is {json.dumps(baseline.model_dump())}."
    )
    payload = {
        "model": LLM_MODEL,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
    }
    request = urllib.request.Request(
        LLM_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=LLM_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"LLM provider returned HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError("LLM provider timed out or was unreachable") from exc
    try:
        content = body["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
        content = str(content).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL).strip()
        parsed = json.loads(content)
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("LLM provider returned invalid CAD JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("LLM provider returned a non-object CAD spec")
    return parsed


def interpret_prompt(prompt: str, process: str, mode: str) -> tuple[str, ModelParameters, bool, list[str]]:
    baseline_title, baseline = parse_prompt(prompt, process)
    if mode != "advanced":
        return baseline_title, baseline, False, []
    try:
        raw = _llm_json(prompt, process, baseline)
    except RuntimeError as exc:
        return baseline_title, baseline, False, [str(exc)]
    candidate = raw.get("parameters", raw) if isinstance(raw, dict) else raw
    if not isinstance(candidate, dict):
        return baseline_title, baseline, False, ["LLM returned no CAD parameters"]
    aliases = {"plant_pot": "plant", "plant pot": "plant", "lamp_base": "lamp", "lamp base": "lamp", "pen_cup": "pen", "pen cup": "pen", "cable_clip": "clip", "cable clip": "clip"}
    kind = aliases.get(str(candidate.get("kind", baseline.kind)).strip().lower(), str(candidate.get("kind", baseline.kind)).strip().lower())
    if kind not in {"tray", "organizer", "clip", "plant", "lamp", "pen", "block"}:
        kind = baseline.kind
    def number(name: str, fallback: float, minimum: float, maximum: float) -> float:
        try:
            value = float(candidate.get(name, fallback))
        except (TypeError, ValueError):
            value = fallback
        return _bounded(value, minimum, maximum)
    width = number("width", baseline.width, 10.0, 1000.0)
    depth = number("depth", baseline.depth, 10.0, 1000.0)
    height = number("height", baseline.height, 5.0, 1000.0)
    wall = number("wall", baseline.wall, 1.2, min(20.0, width / 3, depth / 3))
    bottom = number("bottom", baseline.bottom, 1.2, min(height - 1.0, 20.0))
    chamfer = number("chamfer", baseline.chamfer, 0.0, min(width, depth, height) / 4)
    try:
        compartments = int(max(1, min(12, int(candidate.get("compartments", baseline.compartments)))))
    except (TypeError, ValueError):
        compartments = baseline.compartments
    features = candidate.get("features", {}) if isinstance(candidate.get("features", {}), dict) else {}
    try:
        drainage_holes = int(max(0, min(4, int(candidate.get("drainage_holes", features.get("drainage_holes", baseline.drainage_holes))))))
    except (TypeError, ValueError):
        drainage_holes = baseline.drainage_holes
    cable_channel = bool(candidate.get("cable_channel", features.get("cable_channel", baseline.cable_channel)))
    params = baseline.model_copy(update={"kind": kind, "width": width, "depth": depth, "height": height, "compartments": compartments, "chamfer": chamfer, "wall": wall, "bottom": bottom, "drainage_holes": drainage_holes, "cable_channel": cable_channel})
    titles = {"tray": "Parametric storage tray", "organizer": "Parametric desk organizer", "clip": "Parametric cable clip", "plant": "Parametric plant pot", "lamp": "Parametric lamp base", "pen": "Parametric pen cup", "block": "Parametric solid"}
    assumptions = [str(item)[:180] for item in raw.get("assumptions", []) if str(item).strip()][:6] if isinstance(raw.get("assumptions", []), list) else []
    return titles[kind], params, True, assumptions

def analyze_manufacturability(params: ModelParameters) -> dict[str, Any]:
    profile = PROCESS_PROFILES[params.process]
    issues: list[dict[str, Any]] = []
    wall_ok = params.wall >= profile["min_wall"] and params.wall < min(params.width, params.depth) / 3
    edge_ok = (params.chamfer == 0 or params.chamfer >= profile["min_radius"]) and params.chamfer <= min(params.width, params.depth, params.height) / 4
    clearance_ok = params.wall >= profile["clearance"]
    draft_ok = profile["draft_angle"] == 0.0
    overhang_ok = profile["max_overhang"] >= 45.0

    def add_issue(code: str, severity: str, message: str, message_zh: str, value: float | None = None, limit: float | None = None) -> None:
        issue: dict[str, Any] = {
            "code": code,
            "severity": severity,
            "message": message,
            "message_zh": message_zh,
        }
        if value is not None:
            issue["value"] = round(value, 3)
        if limit is not None:
            issue["limit"] = round(limit, 3)
        issues.append(issue)

    if not wall_ok:
        add_issue("wall_thickness", "error", "Wall thickness is below the selected process minimum.", "壁厚低于当前工艺的最小值。", params.wall, profile["min_wall"])
    if not edge_ok:
        add_issue("edge_treatment", "warning", "Edge radius/chamfer is outside the process range.", "圆角或倒角超出当前工艺范围。", params.chamfer, profile["min_radius"])
    if not clearance_ok:
        add_issue("clearance", "warning", "Clearance is below the selected process recommendation.", "间隙低于当前工艺建议值。", params.wall, profile["clearance"])
    if not overhang_ok:
        add_issue("overhang", "warning", "The selected process needs support review for this overhang.", "当前工艺需要复核悬空和支撑。", profile["max_overhang"], 45.0)
    if not draft_ok:
        add_issue("draft_angle", "warning", "Injection molding requires an explicit draft feature.", "注塑需要明确的拔模特征。", profile["draft_angle"], 1.0)

    wall_map = [
        {
            "region": "outer wall",
            "region_zh": "外壁",
            "nominal_mm": round(params.wall, 3),
            "minimum_mm": round(params.wall, 3),
            "status": "pass" if wall_ok else "fail",
        },
        {
            "region": "bottom",
            "region_zh": "底板",
            "nominal_mm": round(params.bottom, 3),
            "minimum_mm": round(params.bottom, 3),
            "status": "pass" if params.bottom >= profile["min_wall"] else "fail",
        },
    ]
    if params.compartments > 1:
        wall_map.append({
            "region": "dividers",
            "region_zh": "隔板",
            "nominal_mm": round(params.wall, 3),
            "minimum_mm": round(params.wall, 3),
            "status": "pass" if wall_ok else "fail",
        })
    return {
        "process": params.process,
        "profile": profile,
        "wall_map": wall_map,
        "issues": issues,
        "manufacturing_ready": not any(issue["severity"] == "error" for issue in issues),
    }


def _rounded_edges(workplane: Any, radius: float) -> Any:
    if radius <= 0:
        return workplane
    try:
        # The UI value is a chamfer; use the matching B-Rep operation first.
        return workplane.edges("|Z").chamfer(radius)
    except Exception:
        try:
            # Keep a fillet fallback for CadQuery versions or edge selections
            # where chamfer is unavailable, while preserving a valid solid.
            return workplane.edges("|Z").fillet(radius)
        except Exception:
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

    if params.kind in ("plant", "pen"):
        # Rotational containers share a stable hollow profile with the same
        # wall and bottom parameters as trays, keeping UI and B-Rep semantics aligned.
        radius = min(w, d) / 2
        inner_radius = max(1.0, radius - wall)
        inner_height = max(1.0, h - bottom)
        outer_round = cq.Workplane("XY").circle(radius).extrude(h)
        inner = cq.Workplane("XY").circle(inner_radius).extrude(inner_height).translate((0, 0, bottom))
        shape = outer_round.cut(inner)
        if params.kind == "plant" and params.drainage_holes > 0:
            hole_radius = max(0.8, min(3.0, wall * 0.45))
            hole_offset = radius * 0.35
            hole_positions = ((-hole_offset, 0), (hole_offset, 0), (0, hole_offset), (0, -hole_offset))
            for x, y in hole_positions[:min(params.drainage_holes, len(hole_positions))]:
                drainage_hole = cq.Workplane("XY").circle(hole_radius).extrude(bottom + 2.0).translate((x, y, -1.0))
                shape = shape.cut(drainage_hole)
        return shape

    if params.kind == "lamp" and params.cable_channel:
        # The cable channel is recessed from the underside so the lamp base
        # keeps a clean top surface while matching the prompt intent.
        channel_w = max(6.0, min(w * 0.4, w - 2 * wall))
        channel_d = max(4.0, min(d * 0.22, d - 2 * wall))
        channel = cq.Workplane("XY").box(channel_w, channel_d, max(1.0, wall * 1.6), centered=(True, True, False)).translate((0, d * 0.28, -0.1))
        return outer.cut(channel)

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


def _validate_shape(shape: Any, params: ModelParameters, analysis: dict[str, Any]) -> dict[str, bool]:
    solid = shape.val()
    volume = float(solid.Volume())
    bbox = solid.BoundingBox()
    issue_codes = {issue["code"] for issue in analysis["issues"]}
    return {
        "valid_brep": bool(solid.isValid()),
        "single_solid": len(shape.solids().vals()) == 1,
        "positive_volume": volume > 0,
        "bounded": all(
            dimension > 0
            for dimension in (bbox.xlen, bbox.ylen, bbox.zlen)
        ),
        "wall_thickness": "wall_thickness" not in issue_codes,
        "edge_treatment": "edge_treatment" not in issue_codes,
        "overhang": "overhang" not in issue_codes,
        "draft_angle": "draft_angle" not in issue_codes,
        "clearance": "clearance" not in issue_codes,
        # Export readiness is set to true only after all files have been written.
        "export_ready": False,
    }


def _export_step_ap242(shape: Any, step_path: Path) -> str:
    try:
        from OCP.Interface import Interface_Static_SetCVal
        from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

        Interface_Static_SetCVal("write.step.schema", "AP242DIS")
        writer = STEPControl_Writer()
        writer.Transfer(shape.val().wrapped, STEPControl_AsIs)
        writer.Write(str(step_path))
        if not step_path.exists() or step_path.stat().st_size == 0:
            raise RuntimeError("AP242 writer returned an empty file")
        return "AP242DIS"
    except Exception:
        exporters.export(shape, str(step_path))
        return "CADQUERY_DEFAULT"


def _write_3mf(mesh: Any, three_mf_path: Path) -> None:
    vertices = mesh.vertices
    faces = mesh.faces
    vertex_xml = "".join(
        f'<vertex x="{float(vertex[0]):.6f}" y="{float(vertex[1]):.6f}" z="{float(vertex[2]):.6f}"/>'
        for vertex in vertices
    )
    triangle_xml = "".join(
        f'<triangle v1="{int(face[0])}" v2="{int(face[1])}" v3="{int(face[2])}"/>'
        for face in faces
    )
    model_xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">
  <resources><object id="1" type="model"><mesh><vertices>{vertex_xml}</vertices><triangles>{triangle_xml}</triangles></mesh></object></resources>
  <build><item objectid="1"/></build>
</model>'''
    content_types = '''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/3D/3dmodel.model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>'''
    relationships = '''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>'''
    with ZipFile(three_mf_path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("3D/3dmodel.model", model_xml)


def _write_artifacts(
    model_id: str,
    shape: Any,
    title: str,
    params: ModelParameters,
    checks: dict[str, bool],
    analysis: dict[str, Any],
    generation: dict[str, Any] | None = None,
) -> tuple[dict[str, str], str]:
    model_dir = ARTIFACT_ROOT / model_id
    model_dir.mkdir(parents=True, exist_ok=False)
    step_path = model_dir / "model.step"
    stl_path = model_dir / "model.stl"
    analysis_path = model_dir / "analysis.json"

    with EXPORT_LOCK:
        step_schema = _export_step_ap242(shape, step_path)
    exporters.export(shape, str(stl_path))
    preview_files: dict[str, Path] = {}
    if trimesh is not None:
        try:
            mesh = trimesh.load_mesh(str(stl_path), file_type="stl", force="mesh")
            if isinstance(mesh, trimesh.Scene):
                mesh = trimesh.util.concatenate(tuple(mesh.geometry.values()))
            glb_path = model_dir / "model.glb"
            three_mf_path = model_dir / "model.3mf"
            mesh.export(str(glb_path), file_type="glb")
            _write_3mf(mesh, three_mf_path)
            preview_files = {"glb": glb_path, "3mf": three_mf_path}
        except Exception:
            preview_files = {}
    analysis_path.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
    export_paths = [step_path, stl_path, analysis_path, *preview_files.values()]
    checks["export_ready"] = all(path.exists() and path.stat().st_size > 0 for path in export_paths)
    if not checks["export_ready"]:
        raise RuntimeError("one or more generated artifacts are empty")
    manifest = {
        "model_id": model_id,
        "title": title,
        "parameters": params.model_dump(),
        "process": params.process,
        "process_profile": PROCESS_PROFILES[params.process],
        "generation": generation or {"mode": "standard", "llm_used": False, "assumptions": []},
        "checks": checks,
        "analysis": analysis,
        "step_schema": step_schema,
        "units": "mm",
        "generator": "TextToCad geometry backend 0.3.0",
        "formats": ["step", "stl"] + sorted(preview_files),
    }
    manifest_path = model_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    artifacts = {
        "step": f"/v1/models/{model_id}/download?format=step",
        "stl": f"/v1/models/{model_id}/download?format=stl",
        "analysis": f"/v1/models/{model_id}/analysis",
    }
    for format_name in preview_files:
        artifacts[format_name] = f"/v1/models/{model_id}/download?format={format_name}"
    return artifacts, step_schema


def cleanup_artifacts() -> None:
    """Remove expired model and job records so repeated previews cannot fill memory or disk."""
    cutoff = time.time() - max(ARTIFACT_TTL_SECONDS, 3600)
    with JOB_LOCK:
        for job_id, job in list(JOBS.items()):
            if job.get("status") in {"succeeded", "failed", "cancelled"} and job.get("created_at", 0) < cutoff:
                JOBS.pop(job_id, None)
    if ARTIFACT_TTL_SECONDS <= 0:
        return
    cutoff = time.time() - ARTIFACT_TTL_SECONDS
    for model_dir in ARTIFACT_ROOT.iterdir():
        if not model_dir.is_dir() or model_dir.stat().st_mtime >= cutoff:
            continue
        try:
            shutil.rmtree(model_dir)
        except OSError:
            # Cleanup is best effort and must never block a new generation.
            continue


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
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok" if cq is not None else "degraded",
        "engine": "CadQuery/OCCT",
        "cadquery_available": cq is not None,
        "cadquery_error": CADQUERY_ERROR or None,
        "trimesh_available": trimesh is not None,
        "trimesh_error": TRIMESH_ERROR or None,
        "process_profiles": list(PROCESS_PROFILES),
    }


@app.get("/v1/process-profiles")
def get_process_profiles() -> dict[str, dict[str, Any]]:
    return PROCESS_PROFILES


@app.post("/v1/models", response_model=GenerateResponse)
def generate_model(request: GenerateRequest) -> GenerateResponse:
    cleanup_artifacts()
    cache_key = _cache_key(request)
    with CACHE_LOCK:
        cached = MODEL_CACHE.get(cache_key)
        if cached and (ARTIFACT_ROOT / cached.model_id / "manifest.json").exists():
            return cached
    model_id: str | None = None
    try:
        title, params, llm_used, assumptions = interpret_prompt(request.prompt, request.process, request.mode)
        shape = build_geometry(params)
        analysis = analyze_manufacturability(params)
        checks = _validate_shape(shape, params, analysis)
        hard_checks = {key: checks[key] for key in ("valid_brep", "single_solid", "positive_volume", "bounded")}
        if not all(hard_checks.values()):
            raise ValueError(f"geometry validation failed: {checks}")
        model_id = uuid.uuid4().hex
        artifacts, step_schema = _write_artifacts(
            model_id,
            shape,
            title,
            params,
            checks,
            analysis,
            {"mode": request.mode, "llm_used": llm_used, "assumptions": assumptions},
        )
        response = GenerateResponse(
            model_id=model_id,
            title=title,
            parameters=params,
            checks=checks,
            artifacts=artifacts,
            process=params.process,
            profile=PROCESS_PROFILES[params.process],
            analysis=analysis,
            step_schema=step_schema,
            mode=request.mode,
            llm_used=llm_used,
            assumptions=assumptions,
        )
        with CACHE_LOCK:
            MODEL_CACHE[cache_key] = response
        return response
    except RuntimeError as exc:
        if model_id:
            shutil.rmtree(ARTIFACT_ROOT / model_id, ignore_errors=True)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        if model_id:
            shutil.rmtree(ARTIFACT_ROOT / model_id, ignore_errors=True)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        if model_id:
            shutil.rmtree(ARTIFACT_ROOT / model_id, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"geometry generation failed: {exc}") from exc


def _run_job(job_id: str, request: GenerateRequest) -> None:
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job or job["status"] == "cancelled":
            return
        job["status"] = "running"
    try:
        with GENERATION_SEMAPHORE:
            result = generate_model(request)
        with JOB_LOCK:
            job = JOBS.get(job_id)
            if not job:
                return
            if job["status"] == "cancelled":
                return
            job["status"] = "succeeded"
            job["result"] = result.model_dump()
    except HTTPException as exc:
        with JOB_LOCK:
            if job_id in JOBS and JOBS[job_id]["status"] != "cancelled":
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = {"status_code": exc.status_code, "detail": exc.detail}
    except Exception as exc:
        with JOB_LOCK:
            if job_id in JOBS and JOBS[job_id]["status"] != "cancelled":
                JOBS[job_id]["status"] = "failed"
                JOBS[job_id]["error"] = {"status_code": 500, "detail": str(exc)}


@app.post("/v1/jobs")
def create_job(request: GenerateRequest) -> dict[str, Any]:
    job_id = uuid.uuid4().hex
    with JOB_LOCK:
        JOBS[job_id] = {"job_id": job_id, "status": "queued", "created_at": time.time()}
    Thread(target=_run_job, args=(job_id, request), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/v1/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=400, detail="invalid job id")
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        return dict(job)


@app.delete("/v1/jobs/{job_id}")
def cancel_job(job_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise HTTPException(status_code=400, detail="invalid job id")
    with JOB_LOCK:
        job = JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="job not found")
        if job["status"] in {"queued", "running"}:
            job["status"] = "cancelled"
        return {"job_id": job_id, "status": job["status"]}


@app.get("/v1/models/{model_id}/analysis")
def get_analysis(model_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", model_id):
        raise HTTPException(status_code=400, detail="invalid model id")
    analysis_path = ARTIFACT_ROOT / model_id / "analysis.json"
    if not analysis_path.exists():
        raise HTTPException(status_code=404, detail="analysis not found")
    return json.loads(analysis_path.read_text(encoding="utf-8"))


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
    format: Literal["step", "stl", "3mf", "glb"] = Query(default="step"),
) -> FileResponse:
    if not re.fullmatch(r"[0-9a-f]{32}", model_id):
        raise HTTPException(status_code=400, detail="invalid model id")
    suffixes = {"step": ".step", "stl": ".stl", "3mf": ".3mf", "glb": ".glb"}
    file_path = ARTIFACT_ROOT / model_id / f"model{suffixes[format]}"
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="model artifact not found")
    media_type = {
        "step": "application/step",
        "stl": "application/vnd.ms-pki.stl",
        "3mf": "application/vnd.ms-package.3dmanufacturing-3mf",
        "glb": "model/gltf-binary",
    }[format]
    return FileResponse(file_path, media_type=media_type, filename=file_path.name)
