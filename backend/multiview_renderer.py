"""Headless CAD Multi-View Offscreen Renderer.

Renders canonical engineering views (Isometric, Top, Front, Right) and creates
a stitched 2x2 contact sheet for Vision-Language Model consumption without a GUI display server.
Supports VTK offscreen rendering with a robust Matplotlib Agg fallback.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any
import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    import vtk
    VTK_AVAILABLE = True
except ImportError:
    vtk = None
    VTK_AVAILABLE = False


class HeadlessCADRenderer:
    def __init__(
        self,
        resolution: int = 512,
        background_rgb: tuple[float, float, float] = (0.95, 0.96, 0.98),
        prefer_vtk: bool = True,
    ):
        self.resolution = resolution
        self.background_rgb = background_rgb
        self.prefer_vtk = prefer_vtk and VTK_AVAILABLE

    def render_stl_multiview(self, stl_path: Path, output_dir: Path) -> dict[str, Path]:
        """Reads an STL file and outputs ISO, TOP, FRONT, RIGHT views + 2x2 composite."""
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

        return rendered

    def _render_matplotlib(self, stl_path: Path, output_dir: Path) -> dict[str, Path]:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d.art3d import Poly3DCollection
        import trimesh

        mesh = trimesh.load(stl_path)
        if hasattr(mesh, "vertices") and len(mesh.vertices) > 0:
            verts = np.array(mesh.vertices)
            faces = np.array(mesh.faces)
        else:
            raise ValueError(f"Could not load valid mesh from {stl_path}")

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
            plt.close(fig)
            rendered[view_name] = view_file

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
