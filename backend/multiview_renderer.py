"""Headless CAD Multi-View Offscreen Renderer.

Renders canonical engineering views (Isometric, Top, Front, Right) and creates
a stitched 2x2 contact sheet for Vision-Language Model consumption without a GUI display server.
Supports VTK offscreen rendering with a robust Matplotlib Agg fallback.
"""
from __future__ import annotations

import math
from pathlib import Path
import re
import struct
from typing import Any
import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import vtk
    import os
    import sys
    # On Linux/headless, standard vtkXOpenGLRenderWindow crashes if DISPLAY is not present
    VTK_AVAILABLE = bool(vtk is not None and (sys.platform == "win32" or os.environ.get("DISPLAY")))
except Exception:
    vtk = None
    VTK_AVAILABLE = False


# Severity visual configuration for CAD inspection callouts
SEVERITY_PALETTE: dict[str, dict[str, Any]] = {
    "high": {
        "color": (224, 86, 56),        # Vibrant orange/red #e05638
        "bg_color": (36, 18, 16, 235),
        "tag_bg": (224, 86, 56, 255),
        "tag_text": (255, 255, 255),
        "tag": "HIGH",
        "priority": 0,
    },
    "medium": {
        "color": (230, 162, 60),       # Amber #e6a23c
        "bg_color": (38, 28, 14, 235),
        "tag_bg": (230, 162, 60, 255),
        "tag_text": (28, 20, 10),
        "tag": "MED",
        "priority": 1,
    },
    "low": {
        "color": (52, 152, 219),       # Cyan/blue #3498db
        "bg_color": (16, 26, 40, 235),
        "tag_bg": (52, 152, 219, 255),
        "tag_text": (255, 255, 255),
        "tag": "LOW",
        "priority": 2,
    },
}


def _load_stl_triangles(stl_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Load binary or ASCII STL without requiring trimesh.

    The Agent renderer is part of the acceptance loop, so a missing optional
    mesh convenience package must not turn a valid CadQuery export into a
    failed modeling run.
    """
    data = Path(stl_path).read_bytes()
    if len(data) >= 84:
        triangle_count = struct.unpack_from("<I", data, 80)[0]
        record_size = 50
        if 0 < triangle_count <= 10_000_000 and 84 + record_size * triangle_count <= len(data):
            record_dtype = np.dtype([
                ("normal", "<f4", (3,)),
                ("vertices", "<f4", (3, 3)),
                ("attribute", "<u2"),
            ])
            records = np.frombuffer(
                data,
                dtype=record_dtype,
                count=triangle_count,
                offset=84,
            )
            vertices = np.asarray(records["vertices"], dtype=float).reshape(-1, 3)
            faces = np.arange(len(vertices), dtype=np.int64).reshape(-1, 3)
            return vertices, faces

    text = data.decode("utf-8", errors="ignore")
    matches = re.findall(
        r"\bvertex\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)",
        text,
        flags=re.IGNORECASE,
    )
    if len(matches) >= 3 and len(matches) % 3 == 0:
        vertices = np.asarray([[float(x), float(y), float(z)] for x, y, z in matches], dtype=float)
        faces = np.arange(len(vertices), dtype=np.int64).reshape(-1, 3)
        return vertices, faces
    raise ValueError(f"Could not load valid binary or ASCII STL from {stl_path}")


def _get_font(size: int = 12, bold: bool = False) -> ImageFont.ImageFont | None:
    """Helper to load a system TrueType font with graceful fallback to default bitmap font."""
    candidates = (
        ["arialbd.ttf", "seguisb.ttf", "DejaVuSans-Bold.ttf", "arial.ttf", "segoeui.ttf"]
        if bold
        else ["arial.ttf", "segoeui.ttf", "DejaVuSans.ttf", "calibri.ttf"]
    )
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:
        pass
    try:
        return ImageFont.load_default()
    except Exception:
        pass
    try:
        if hasattr(ImageFont, "load_default_imagefont"):
            return ImageFont.load_default_imagefont()
    except Exception:
        pass
    return None


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont | None) -> tuple[int, int]:
    """Measures text bounding width and height safely across PIL versions."""
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        return max(1, int(bbox[2] - bbox[0])), max(1, int(bbox[3] - bbox[1]))
    except Exception:
        try:
            if font is not None and hasattr(font, "getlength"):
                return max(1, int(font.getlength(text))), 12
        except Exception:
            pass
        return max(1, len(text) * 8), 12


def _resolve_view_quadrant(discrepancy: dict[str, Any], existing_counts: dict[str, int]) -> str:
    """Determines which CAD view quadrant best highlights the discrepancy.

    Canonical Quadrant Mapping:
      - Top-Left:  ISO (ISOMETRIC 3D) -> Overall 3D shape / general topology
      - Top-Right: Top view (+Z)      -> Holes / through-holes / bolt circles / cutouts
      - Bottom-Left: Front view (+Y)  -> Height / thickness / stepped layers / edge treatments
      - Bottom-Right: Right view (+X) -> Width / lateral profile / secondary height features
    """
    explicit = str(discrepancy.get("view", discrepancy.get("quadrant", ""))).lower().strip()
    if explicit in ("iso", "top", "front", "right"):
        return explicit

    feature_str = str(discrepancy.get("feature", "")).lower()
    issue_str = str(discrepancy.get("issue", "")).lower()
    combined = f"{feature_str} {issue_str}"

    # 1. Holes / through-holes / bolt circles / pockets / cutouts -> Top view
    top_keywords = (
        "hole", "bore", "through", "cutout", "pocket", "slot", "drill",
        "bolt", "screw", "pin", "circle", "cavity", "pattern", "boss",
        "cylinder", "cylindrical", "opening", "通孔", "孔", "槽", "开孔", "螺栓", "螺纹",
    )
    if any(kw in combined for kw in top_keywords):
        return "top"

    # 2. Height / thickness / stepped layers / edge treatments -> Front / Right views
    front_keywords = (
        "height", "thickness", "step", "layer", "elevation", "z-axis", "base",
        "flange", "fillet", "chamfer", "bevel", "wall", "vertical", "depth",
        "tall", "高", "厚", "台阶", "层", "倒角", "圆角", "壁厚",
    )
    right_keywords = (
        "width", "right", "side", "lateral", "x-axis", "profile", "rib",
        "gusset", "fin", "web", "flange_side", "宽", "侧", "筋",
    )

    has_front = any(kw in combined for kw in front_keywords)
    has_right = any(kw in combined for kw in right_keywords)

    if has_right and not has_front:
        return "right"
    if has_front:
        # If right keywords are also present or front quadrant is already crowded, balance to right
        if has_right or (existing_counts.get("front", 0) > existing_counts.get("right", 0)):
            return "right"
        return "front"

    # 3. Overall 3D shape / general topology -> ISO view
    return "iso"


class HeadlessCADRenderer:
    def __init__(
        self,
        resolution: int = 512,
        background_rgb: tuple[float, float, float] = (0.95, 0.96, 0.98),
        prefer_vtk: bool = False,
    ):
        self.resolution = resolution
        self.background_rgb = background_rgb
        self.prefer_vtk = prefer_vtk and VTK_AVAILABLE

    def render_stl_multiview(
        self,
        stl_path: Path,
        output_dir: Path,
        discrepancies: list[dict] | None = None,
        metrics: dict | None = None,
    ) -> dict[str, Path]:
        """Reads an STL file and outputs ISO, TOP, FRONT, RIGHT views + 2x2 composite.

        Optionally produces an annotated contact sheet (`annotated_composite.png`)
        with engineering defect callout markers and metrology overlays if discrepancies
        or metrics are provided.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        rendered_paths: dict[str, Path] = {}

        if self.prefer_vtk:
            try:
                rendered_paths = self._render_vtk(stl_path, output_dir)
            except Exception:
                rendered_paths = self._render_matplotlib(stl_path, output_dir)
        else:
            rendered_paths = self._render_matplotlib(stl_path, output_dir)

        # Assemble 2x2 collage for single-token-budget VLM input
        composite_path = output_dir / "composite.png"
        self._compose_grid(rendered_paths, composite_path)
        rendered_paths["composite"] = composite_path

        # Generate annotated composite if discrepancies or metrics are specified
        if discrepancies is not None or metrics is not None:
            annotated_path = output_dir / "annotated_composite.png"
            self.annotate_composite(
                composite_path=composite_path,
                discrepancies=discrepancies or [],
                metrics=metrics,
                output_path=annotated_path,
            )
            rendered_paths["annotated_composite"] = annotated_path

        return rendered_paths

    def _render_vtk(self, stl_path: Path, output_dir: Path) -> dict[str, Path]:
        render_window = vtk.vtkRenderWindow()
        render_window.SetOffScreenRendering(1)
        render_window.SetSize(self.resolution, self.resolution)

        renderer = vtk.vtkRenderer()
        renderer.SetBackground(*self.background_rgb)
        render_window.AddRenderer(renderer)

        reader = vtk.vtkSTLReader()
        reader.SetFileName(str(stl_path))
        reader.Update()
        polydata = reader.GetOutput()

        if polydata.GetNumberOfPoints() == 0:
            raise ValueError(f"STL at {stl_path} contains zero vertices.")

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(reader.GetOutputPort())
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(0.24, 0.54, 0.82)
        actor.GetProperty().SetAmbient(0.25)
        actor.GetProperty().SetDiffuse(0.7)
        actor.GetProperty().SetSpecular(0.35)
        actor.GetProperty().SetSpecularPower(25.0)
        renderer.AddActor(actor)

        # Feature edge extractor for crisp CAD lines
        edge_filter = vtk.vtkFeatureEdges()
        edge_filter.SetInputConnection(reader.GetOutputPort())
        edge_filter.BoundaryEdgesOn()
        edge_filter.FeatureEdgesOn()
        edge_filter.SetFeatureAngle(28.0)
        edge_filter.ManifoldEdgesOff()

        edge_mapper = vtk.vtkPolyDataMapper()
        edge_mapper.SetInputConnection(edge_filter.GetOutputPort())
        edge_mapper.SetResolveCoincidentTopologyToPolygonOffset()

        edge_actor = vtk.vtkActor()
        edge_actor.SetMapper(edge_mapper)
        edge_actor.GetProperty().SetColor(0.12, 0.15, 0.18)
        edge_actor.GetProperty().SetLineWidth(1.6)
        renderer.AddActor(edge_actor)

        bounds = polydata.GetBounds()
        center = [(bounds[0] + bounds[1]) / 2.0, (bounds[2] + bounds[3]) / 2.0, (bounds[4] + bounds[5]) / 2.0]
        max_span = max(bounds[1] - bounds[0], bounds[3] - bounds[2], bounds[5] - bounds[4], 1.0)
        cam_dist = max_span * 2.3

        camera = renderer.GetActiveCamera()
        w2i = vtk.vtkWindowToImageFilter()
        w2i.SetInput(render_window)
        w2i.ReadFrontBufferOff()

        png_writer = vtk.vtkPNGWriter()

        views = {
            "iso": ((1.0, 1.0, 1.0), (0.0, 0.0, 1.0)),
            "top": ((0.0001, 0.0001, 1.0), (0.0, 1.0, 0.0)),
            "front": ((0.0001, -1.0, 0.0001), (0.0, 0.0, 1.0)),
            "right": ((1.0, 0.0001, 0.0001), (0.0, 0.0, 1.0)),
        }

        rendered: dict[str, Path] = {}
        for view_name, (offset, view_up) in views.items():
            norm = math.sqrt(sum(x * x for x in offset))
            eye_pos = [center[i] + (offset[i] / norm) * cam_dist for i in range(3)]

            camera.SetPosition(*eye_pos)
            camera.SetFocalPoint(*center)
            camera.SetViewUp(*view_up)
            renderer.ResetCameraClippingRange()

            render_window.Render()
            w2i.Modified()
            w2i.Update()

            view_file = output_dir / f"{view_name}.png"
            png_writer.SetFileName(str(view_file))
            png_writer.SetInputConnection(w2i.GetOutputPort())
            png_writer.Write()
            rendered[view_name] = view_file

        try:
            render_window.Finalize()
        except Exception:
            pass

        return rendered

    def _render_matplotlib(self, stl_path: Path, output_dir: Path) -> dict[str, Path]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection

        verts, faces = _load_stl_triangles(stl_path)

        tri_verts = verts[faces]
        all_v = tri_verts.reshape(-1, 3)
        min_b = all_v.min(axis=0) - 1.0
        max_b = all_v.max(axis=0) + 1.0

        view_angles = {
            "iso": (28, 45),
            "top": (90, -90),
            "front": (0, -90),
            "right": (0, 0),
        }

        rendered: dict[str, Path] = {}
        for view_name, (elev, azim) in view_angles.items():
            fig = plt.figure(figsize=(self.resolution / 100, self.resolution / 100), dpi=100)
            try:
                ax = fig.add_subplot(111, projection="3d")
                poly = Poly3DCollection(tri_verts, alpha=0.92, facecolor="#4589c9", edgecolor="#1a2530", linewidth=0.25)
                ax.add_collection3d(poly)
                ax.set_xlim([min_b[0], max_b[0]])
                ax.set_ylim([min_b[1], max_b[1]])
                ax.set_zlim([min_b[2], max_b[2]])
                ax.view_init(elev=elev, azim=azim)
                ax.axis("off")
                plt.tight_layout()

                view_file = output_dir / f"{view_name}.png"
                plt.savefig(str(view_file), bbox_inches="tight", pad_inches=0.02)
                rendered[view_name] = view_file
            finally:
                plt.close(fig)

        return rendered

    def _compose_grid(self, view_paths: dict[str, Path], output_path: Path) -> None:
        """Stitches individual views into a 2x2 grid with clear viewpoint badges."""
        res = self.resolution
        canvas = Image.new("RGB", (res * 2, res * 2), color=(240, 243, 246))
        draw = ImageDraw.Draw(canvas)

        layout = [
            ("iso", (0, 0), "ISOMETRIC 3D"),
            ("top", (res, 0), "TOP (+Z)"),
            ("front", (0, res), "FRONT (+Y)"),
            ("right", (res, res), "RIGHT (+X)"),
        ]

        for key, pos, label in layout:
            if key in view_paths and view_paths[key].exists():
                with Image.open(view_paths[key]) as img:
                    img_resized = img.resize((res, res), Image.Resampling.LANCZOS)
                    canvas.paste(img_resized, pos)
                # Draw viewpoint label tag
                tag_x = pos[0] + 12
                tag_y = pos[1] + 12
                draw.rectangle([tag_x, tag_y, tag_x + 110, tag_y + 24], fill=(24, 28, 34), outline=(212, 255, 79), width=1)
                draw.text((tag_x + 8, tag_y + 5), label, fill=(255, 255, 255))

        # Divider grid lines
        draw.line([(res, 0), (res, res * 2)], fill=(200, 205, 215), width=2)
        draw.line([(0, res), (res * 2, res)], fill=(200, 205, 215), width=2)
        canvas.save(str(output_path), format="PNG", optimize=True)

    def annotate_composite(
        self,
        composite_path: Path | str,
        discrepancies: list[dict],
        metrics: dict | None = None,
        output_path: Path | str | None = None,
    ) -> Path:
        """Annotates a 2x2 multi-view composite image with defect callout markers and metrology badges.

        Parameters:
            composite_path: Path to the base 2x2 composite CAD rendering.
            discrepancies: List of discrepancy dicts, each with 'severity', 'feature', and 'issue'.
            metrics: Optional dict with metrology stats (e.g. bbox, volume, faces, score).
            output_path: Destination path for the annotated image (defaults to annotated_composite.png).

        Returns:
            Path to the saved annotated composite image.
        """
        composite_file = Path(composite_path)
        if not composite_file.exists():
            raise FileNotFoundError(f"Composite image not found: {composite_file}")

        if output_path is None:
            dest_path = composite_file.with_name("annotated_composite.png")
        else:
            dest_path = Path(output_path)

        dest_path.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(composite_file) as source_img:
            base_canvas = source_img.convert("RGB").copy()

        W, H = base_canvas.size
        hw, hh = W // 2, H // 2

        quadrant_bounds = {
            "iso": (0, 0, hw, hh),
            "top": (hw, 0, W, hh),
            "front": (0, hh, hw, H),
            "right": (hw, hh, W, H),
        }

        # Setup translucent RGBA overlay
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)

        # 1. Group discrepancies by target view quadrant
        grouped: dict[str, list[dict[str, Any]]] = {"iso": [], "top": [], "front": [], "right": []}
        counts: dict[str, int] = {"iso": 0, "top": 0, "front": 0, "right": 0}

        for raw_disc in discrepancies:
            if isinstance(raw_disc, dict):
                disc = raw_disc
            elif isinstance(raw_disc, str):
                disc = {"feature": "inspection", "issue": raw_disc, "severity": "medium"}
            elif raw_disc is not None:
                disc = {"feature": "inspection", "issue": str(raw_disc), "severity": "medium"}
            else:
                continue
            view = _resolve_view_quadrant(disc, counts)
            grouped[view].append(disc)
            counts[view] += 1

        # Fonts for callouts
        font_tag = _get_font(size=11, bold=True)
        font_body = _get_font(size=11, bold=False)

        # 2. Render Callouts and Target Reticles for each quadrant
        for view_key, items in grouped.items():
            if not items:
                continue

            # Prioritize high severity first; limit to top 4 per quadrant to prevent overflow
            sorted_items = sorted(
                items,
                key=lambda d: SEVERITY_PALETTE.get(
                    str(d.get("severity", "medium")).lower().strip(),
                    SEVERITY_PALETTE["medium"],
                )["priority"],
            )[:4]

            qx0, qy0, qx1, qy1 = quadrant_bounds[view_key]
            qw = qx1 - qx0
            qh = qy1 - qy0
            cx = qx0 + qw // 2
            cy = qy0 + qh // 2

            pin_offsets = [(0, 0), (-36, -26), (36, 28), (-32, 32), (32, -30)]

            for idx, disc in enumerate(sorted_items):
                sev_key = str(disc.get("severity", "medium")).lower().strip()
                sev_cfg = SEVERITY_PALETTE.get(sev_key, SEVERITY_PALETTE["medium"])

                feature = str(disc.get("feature", "feature")).strip()
                issue = str(disc.get("issue", "")).strip()

                # Format label: "[HIGH] feature: issue"
                issue_snippet = (issue[:34] + "...") if len(issue) > 36 else issue
                body_text = f"{feature}: {issue_snippet}" if issue_snippet else feature

                tag_text = sev_cfg["tag"]
                tw, th = _measure_text(draw, tag_text, font_tag)
                bw, bh = _measure_text(draw, body_text, font_body)

                tag_pill_w = tw + 10
                tag_pill_h = 18

                box_h = max(26, tag_pill_h + 8, bh + 10)
                box_w = tag_pill_w + bw + 20

                # Constrain box width to avoid overlapping the viewpoint badge on the left
                max_w = max(180, qw - 145)
                if box_w > max_w:
                    box_w = max_w

                # Anchor callout badge in the top-right of the quadrant
                box_r = qx1 - 14
                box_l = box_r - box_w
                box_t = qy0 + 12 + idx * (box_h + 6)
                box_b = box_t + box_h

                # Center / offset for target pin
                p_dx, p_dy = pin_offsets[idx % len(pin_offsets)]
                tx = cx + p_dx
                ty = cy + p_dy

                # Draw Target Reticle (Marker Pin)
                color_rgba = sev_cfg["color"] + (255,)
                # Outer circle
                draw.ellipse([tx - 13, ty - 13, tx + 13, ty + 13], outline=color_rgba, width=2)
                # Center pip
                draw.ellipse([tx - 3, ty - 3, tx + 3, ty + 3], fill=color_rgba)
                # Crosshair ticks
                draw.line([(tx - 19, ty), (tx - 14, ty)], fill=color_rgba, width=2)
                draw.line([(tx + 14, ty), (tx + 19, ty)], fill=color_rgba, width=2)
                draw.line([(tx, ty - 19), (tx, ty - 14)], fill=color_rgba, width=2)
                draw.line([(tx, ty + 14), (tx, ty + 19)], fill=color_rgba, width=2)

                # Leader line connecting reticle to callout box
                start_lx = tx + 13
                start_ly = ty - 4
                end_lx = box_l
                end_ly = box_t + box_h // 2
                draw.ellipse([start_lx - 2, start_ly - 2, start_lx + 2, start_ly + 2], fill=color_rgba)
                draw.line([(start_lx, start_ly), (end_lx, end_ly)], fill=sev_cfg["color"] + (180,), width=2)

                # Draw Callout Box
                draw.rounded_rectangle(
                    [box_l, box_t, box_r, box_b],
                    radius=5,
                    fill=sev_cfg["bg_color"],
                    outline=color_rgba,
                    width=2,
                )

                # Draw Severity Pill
                pill_x0 = box_l + 5
                pill_y0 = box_t + (box_h - tag_pill_h) // 2
                pill_x1 = pill_x0 + tag_pill_w
                pill_y1 = pill_y0 + tag_pill_h
                draw.rounded_rectangle(
                    [pill_x0, pill_y0, pill_x1, pill_y1],
                    radius=3,
                    fill=sev_cfg["tag_bg"],
                )
                draw.text(
                    (pill_x0 + (tag_pill_w - tw) // 2, pill_y0 + (tag_pill_h - th) // 2),
                    tag_text,
                    fill=sev_cfg["tag_text"],
                    font=font_tag,
                )

                # Draw Text Label
                label_x = pill_x1 + 6
                label_y = box_t + (box_h - bh) // 2
                draw.text(
                    (label_x, label_y),
                    body_text,
                    fill=(245, 248, 252),
                    font=font_body,
                )

        # 3. Metrology Info Overlay Badge (if metrics provided)
        if metrics:
            units = str(metrics.get("units", "mm")).strip()
            parts: list[str] = []

            # Bounding box
            if "bbox" in metrics:
                bbox_val = metrics["bbox"]
                if isinstance(bbox_val, (list, tuple)) and len(bbox_val) >= 3:
                    dx, dy, dz = float(bbox_val[0]), float(bbox_val[1]), float(bbox_val[2])
                    parts.append(f"DIM: {dx:.1f} × {dy:.1f} × {dz:.1f} {units}")
                elif isinstance(bbox_val, dict):
                    dx = float(bbox_val.get("dx", bbox_val.get("width", bbox_val.get("x", 0.0))))
                    dy = float(bbox_val.get("dy", bbox_val.get("depth", bbox_val.get("y", 0.0))))
                    dz = float(bbox_val.get("dz", bbox_val.get("height", bbox_val.get("z", 0.0))))
                    parts.append(f"DIM: {dx:.1f} × {dy:.1f} × {dz:.1f} {units}")

            # Volume
            vol_val = metrics.get("volume", metrics.get("vol"))
            if vol_val is not None:
                try:
                    vol_num = float(vol_val)
                    if vol_num >= 100:
                        parts.append(f"VOL: {vol_num:,.0f} {units}³")
                    else:
                        parts.append(f"VOL: {vol_num:.1f} {units}³")
                except (ValueError, TypeError):
                    parts.append(f"VOL: {vol_val} {units}³")

            # Mesh faces / triangles
            faces_val = metrics.get("faces", metrics.get("triangles", metrics.get("poly_count")))
            if faces_val is not None:
                try:
                    parts.append(f"MESH: {int(faces_val):,} faces")
                except (ValueError, TypeError):
                    parts.append(f"MESH: {faces_val} faces")

            if "score" in metrics:
                try:
                    parts.append(f"SCORE: {float(metrics['score']):.1f}/10")
                except (ValueError, TypeError):
                    pass

            if "label" in metrics:
                parts.append(str(metrics["label"]))

            if not parts and metrics:
                # Fallback for generic key-value pairs
                parts = [f"{str(k).upper()}: {v}" for k, v in metrics.items() if k not in ("units",)]

            if parts:
                metro_text = "  |  ".join(parts)
                font_metro = _get_font(size=12, bold=False)
                font_metro_tag = _get_font(size=11, bold=True)

                mw, mh = _measure_text(draw, metro_text, font_metro)
                mtw, mth = _measure_text(draw, "METROLOGY", font_metro_tag)

                tag_w = mtw + 12
                metro_h = 28
                metro_w = tag_w + mw + 26
                metro_x0 = (W - metro_w) // 2
                metro_y0 = H - 38
                metro_x1 = metro_x0 + metro_w
                metro_y1 = metro_y0 + metro_h

                # Semi-transparent dark container with crisp cyan border
                draw.rounded_rectangle(
                    [metro_x0, metro_y0, metro_x1, metro_y1],
                    radius=5,
                    fill=(16, 22, 30, 230),
                    outline=(64, 196, 255, 255),
                    width=1,
                )

                # METROLOGY pill tag
                draw.rounded_rectangle(
                    [metro_x0 + 4, metro_y0 + 4, metro_x0 + 4 + tag_w, metro_y1 - 4],
                    radius=3,
                    fill=(24, 68, 96, 255),
                )
                draw.text(
                    (metro_x0 + 4 + (tag_w - mtw) // 2, metro_y0 + 4 + (metro_h - 8 - mth) // 2),
                    "METROLOGY",
                    fill=(100, 215, 255),
                    font=font_metro_tag,
                )

                # Main metrology text
                draw.text(
                    (metro_x0 + tag_w + 14, metro_y0 + (metro_h - mh) // 2),
                    metro_text,
                    fill=(235, 245, 255),
                    font=font_metro,
                )

        # 4. Composite overlay onto base canvas
        base_rgba = base_canvas.convert("RGBA")
        result_img = Image.alpha_composite(base_rgba, overlay).convert("RGB")
        result_img.save(str(dest_path), format="PNG", optimize=True)
        return dest_path

    def render_annotated_composite(
        self,
        view_paths: dict[str, Path],
        discrepancies: list[dict[str, Any]],
        output_path: Path,
        metrics: dict | None = None,
    ) -> Path:
        """Render annotated composite contact sheet with DFM/discrepancy engineering overlays."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        composite_path = view_paths.get("composite")
        temp_comp = None
        if not composite_path or not Path(composite_path).exists():
            temp_comp = output_path.parent / "temp_composite.png"
            self._compose_grid(view_paths, temp_comp)
            composite_path = temp_comp
        try:
            return self.annotate_composite(
                composite_path=composite_path,
                discrepancies=discrepancies,
                metrics=metrics,
                output_path=output_path,
            )
        finally:
            if temp_comp and temp_comp.exists() and temp_comp != output_path:
                try:
                    temp_comp.unlink()
                except Exception:
                    pass


def annotate_composite(
    composite_path: Path | str,
    discrepancies: list[dict],
    metrics: dict | None = None,
    output_path: Path | str | None = None,
) -> Path:
    """Standalone helper to annotate a 2x2 CAD composite image with defect callouts and metrology overlays."""
    renderer = HeadlessCADRenderer()
    return renderer.annotate_composite(
        composite_path=composite_path,
        discrepancies=discrepancies,
        metrics=metrics,
        output_path=output_path,
    )
