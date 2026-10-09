"""Unit tests for CAD multi-view visual defect annotations and metrology overlays."""
from pathlib import Path
import sys
import tempfile
import numpy as np
import pytest
from PIL import Image, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from backend.multiview_renderer import (
        HeadlessCADRenderer,
        annotate_composite,
        _resolve_view_quadrant,
        _get_font,
        _measure_text,
        SEVERITY_PALETTE,
    )
except ImportError:
    from multiview_renderer import (
        HeadlessCADRenderer,
        annotate_composite,
        _resolve_view_quadrant,
        _get_font,
        _measure_text,
        SEVERITY_PALETTE,
    )


@pytest.fixture
def mock_composite_image(tmp_path: Path) -> Path:
    """Creates a mock 1024x1024 2x2 composite contact sheet."""
    img_path = tmp_path / "composite.png"
    img = Image.new("RGB", (1024, 1024), color=(240, 243, 246))
    img.save(str(img_path))
    return img_path


def test_quadrant_resolution_rules():
    """Validates engineering view routing rules."""
    counts = {"iso": 0, "top": 0, "front": 0, "right": 0}

    # Holes -> Top view
    assert _resolve_view_quadrant({"feature": "hole", "issue": "missing center hole"}, counts) == "top"
    assert _resolve_view_quadrant({"feature": "bolt_circle", "issue": "pcd pattern error"}, counts) == "top"
    assert _resolve_view_quadrant({"feature": "pocket", "issue": "depth of through-hole"}, counts) == "top"

    # Height / thickness / stepped layers -> Front or Right view
    assert _resolve_view_quadrant({"feature": "height", "issue": "stepped layer thickness"}, counts) == "front"
    # When front is crowded, balance to right
    assert _resolve_view_quadrant({"feature": "thickness", "issue": "base thickness mismatch"}, {"front": 1, "right": 0}) == "right"
    assert _resolve_view_quadrant({"feature": "flange", "issue": "side width"}, counts) == "right"

    # Topology / 3D shape -> ISO view
    assert _resolve_view_quadrant({"feature": "topology", "issue": "overall 3D proportion"}, counts) == "iso"
    assert _resolve_view_quadrant({"feature": "geometry", "issue": "mesh distortion"}, counts) == "iso"

    # Explicit override
    assert _resolve_view_quadrant({"feature": "hole", "issue": "side hole", "view": "right"}, counts) == "right"
    assert _resolve_view_quadrant({"feature": "height", "issue": "iso view", "quadrant": "iso"}, counts) == "iso"


def test_annotate_composite_severities_and_colors(mock_composite_image: Path, tmp_path: Path):
    """Checks visual annotation creation with high, medium, and low severity color coding."""
    renderer = HeadlessCADRenderer(resolution=512)
    discrepancies = [
        {"severity": "high", "feature": "hole", "issue": "missing through-hole"},
        {"severity": "medium", "feature": "thickness", "issue": "flange too thin"},
        {"severity": "low", "feature": "topology", "issue": "minor symmetry deviation"},
    ]
    out_file = tmp_path / "test_annotated.png"

    result_path = renderer.annotate_composite(
        composite_path=mock_composite_image,
        discrepancies=discrepancies,
        output_path=out_file,
    )

    assert result_path == out_file
    assert out_file.exists()

    with Image.open(out_file) as img:
        assert img.size == (1024, 1024)
        arr = np.array(img)

        # High severity vibrant orange/red (#e05638 -> 224, 86, 56) in Top-Right quadrant
        top_quad = arr[0:512, 512:1024]
        has_high_red = np.any((top_quad[:, :, 0] == 224) & (top_quad[:, :, 1] == 86) & (top_quad[:, :, 2] == 56))
        assert has_high_red, "High severity color #e05638 should be rendered in Top quadrant"

        # Medium severity amber (#e6a23c -> 230, 162, 60) in Front quadrant
        front_quad = arr[512:1024, 0:512]
        has_med_amber = np.any((front_quad[:, :, 0] == 230) & (front_quad[:, :, 1] == 162) & (front_quad[:, :, 2] == 60))
        assert has_med_amber, "Medium severity color #e6a23c should be rendered in Front quadrant"

        # Low severity cyan/blue (#3498db -> 52, 152, 219) in ISO quadrant
        iso_quad = arr[0:512, 0:512]
        has_low_cyan = np.any((iso_quad[:, :, 0] == 52) & (iso_quad[:, :, 1] == 152) & (iso_quad[:, :, 2] == 219))
        assert has_low_cyan, "Low severity color #3498db should be rendered in ISO quadrant"


def test_annotate_composite_metrology_overlay(mock_composite_image: Path, tmp_path: Path):
    """Verifies that bounding dimensions, volume, and mesh metrics are rendered."""
    metrics = {
        "bbox": [60.0, 60.0, 10.0],
        "volume": 25412.0,
        "faces": 1420,
    }
    out_file = tmp_path / "metrology_annotated.png"

    result_path = annotate_composite(
        composite_path=mock_composite_image,
        discrepancies=[],
        metrics=metrics,
        output_path=out_file,
    )

    assert result_path == out_file
    assert out_file.exists()

    with Image.open(out_file) as img:
        arr = np.array(img)
        # Check bottom margin for metrology badge border (64, 196, 255)
        bot_margin = arr[1024 - 45:1024, :]
        has_metro_border = np.any((bot_margin[:, :, 0] == 64) & (bot_margin[:, :, 1] == 196) & (bot_margin[:, :, 2] == 255))
        assert has_metro_border, "Metrology badge with cyan accent outline should be rendered in bottom margin"


def test_annotate_composite_dict_bbox(mock_composite_image: Path, tmp_path: Path):
    """Verifies dict bounding box format."""
    metrics = {
        "bbox": {"dx": 45.0, "dy": 30.0, "dz": 15.0},
        "vol": 12000.0,
        "triangles": 980,
    }
    out_file = tmp_path / "dict_bbox_annotated.png"
    annotate_composite(mock_composite_image, [], metrics=metrics, output_path=out_file)
    assert out_file.exists()


def test_annotate_composite_default_output_path(mock_composite_image: Path):
    """When output_path is None, it should default to annotated_composite.png in the same directory."""
    result = annotate_composite(mock_composite_image, discrepancies=[])
    expected = mock_composite_image.with_name("annotated_composite.png")
    assert result == expected
    assert expected.exists()


def test_annotate_composite_missing_file_raises():
    """Missing input composite file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        annotate_composite(Path("non_existent_composite.png"), discrepancies=[])


def test_font_fallback_resilience(monkeypatch):
    """Ensures fallback to PIL default font works without crashing."""
    # Force truetype to fail
    monkeypatch.setattr(ImageFont, "truetype", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("No font")))

    font = _get_font(size=14, bold=True)
    assert font is not None

    # Test annotation with forced fallback font
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_p = Path(tmpdir)
        comp_img = Image.new("RGB", (512, 512), (240, 240, 240))
        comp_file = tmp_p / "comp.png"
        comp_img.save(str(comp_file))

        out = annotate_composite(
            comp_file,
            discrepancies=[{"severity": "high", "feature": "hole", "issue": "fallback test"}],
            metrics={"bbox": [10, 10, 10]},
            output_path=tmp_p / "out.png",
        )
        assert out.exists()


def test_render_stl_multiview_with_and_without_annotations(tmp_path: Path, monkeypatch):
    """Tests render_stl_multiview returns composite and optionally annotated_composite."""
    stl_path = tmp_path / "test.stl"
    stl_path.write_text("solid test\nendsolid test")

    renderer = HeadlessCADRenderer(resolution=256)

    # Mock _render_matplotlib to avoid trimesh/vtk dependency in test environment
    def mock_render(stl_p, out_d):
        paths = {}
        for v in ["iso", "top", "front", "right"]:
            p = out_d / f"{v}.png"
            Image.new("RGB", (256, 256), (255, 255, 255)).save(str(p))
            paths[v] = p
        return paths

    monkeypatch.setattr(renderer, "_render_matplotlib", mock_render)
    renderer.prefer_vtk = False

    # 1. Without annotations
    run1_dir = tmp_path / "run1"
    views1 = renderer.render_stl_multiview(stl_path, run1_dir)
    assert "composite" in views1
    assert "annotated_composite" not in views1
    assert views1["composite"].exists()

    # 2. With annotations
    run2_dir = tmp_path / "run2"
    discrepancies = [{"severity": "high", "feature": "hole", "issue": "missing through-hole"}]
    metrics = {"bbox": [50.0, 50.0, 10.0], "volume": 20000.0}
    views2 = renderer.render_stl_multiview(
        stl_path,
        run2_dir,
        discrepancies=discrepancies,
        metrics=metrics,
    )
    assert "composite" in views2
    assert "annotated_composite" in views2
    assert views2["composite"].exists()
    assert views2["annotated_composite"].exists()


def test_annotate_composite_string_discrepancies(mock_composite_image: Path, tmp_path: Path):
    """Checks that string or malformed items in discrepancies do not crash annotate_composite."""
    out_path = tmp_path / "str_anno.png"
    result = annotate_composite(
        composite_path=mock_composite_image,
        discrepancies=["Missing through hole", {"issue": "wall too thin"}],
        output_path=out_path,
    )
    assert result.exists()


def test_apply_patches_edge_cases():
    """Validates robust handling of empty patches, string values, and output node linking."""
    from backend.ir_repair import apply_patches

    base_ir = {
        "version": "1.0",
        "parameters": {
            "width": {"value": 100.0, "unit": "mm"},
            "height": {"value": 20.0, "unit": "mm"},
        },
        "nodes": [
            {"id": "base_block", "kind": "primitive", "operation": "box", "parameters": {"width": 100, "height": 20}},
        ],
        "outputs": [{"id": "primary", "node": "base_block", "format": ["step", "stl", "glb"]}],
    }

    # 1. None and empty patches
    res_none = apply_patches(base_ir, None)
    assert res_none["outputs"][0]["node"] == "base_block"
    res_empty = apply_patches(base_ir, [])
    assert res_empty["outputs"][0]["node"] == "base_block"

    # 2. add_hole_pattern with string parameters and output propagation
    pattern_patch = [{
        "op": "add_hole_pattern",
        "target_node": "base_block",
        "count": "4.0",
        "circle_radius": "25.0",
        "hole_diameter": "6.0",
    }]
    res_pattern = apply_patches(base_ir, pattern_patch)
    assert res_pattern["outputs"][0]["node"] == "cut_hole_pattern_1"
    assert any(n["id"] == "cutter_1_3" for n in res_pattern["nodes"])

    # 3. add_chamfer and add_fillet with string parameters
    chamfer_patch = [{
        "op": "add_chamfer",
        "target_node": "base_block",
        "distance": "1.5",
    }]
    res_chamfer = apply_patches(base_ir, chamfer_patch)
    assert res_chamfer["outputs"][0]["node"] == "chamfer_1"

    fillet_patch = [{
        "op": "add_fillet",
        "target_node": "base_block",
        "radius": "2.0",
    }]
    res_fillet = apply_patches(base_ir, fillet_patch)
    assert res_fillet["outputs"][0]["node"] == "fillet_1"

    # 4. shell_hollow with string thickness
    shell_patch = [{
        "op": "shell_hollow",
        "target_node": "base_block",
        "thickness": "2.5",
    }]
    res_shell = apply_patches(base_ir, shell_patch)
    assert res_shell["outputs"][0]["node"] == "shell_1"


def test_round_view_and_glb_security(tmp_path: Path):
    """Validates path traversal rejection and negative round index handling."""
    from fastapi import HTTPException
    from backend.app import get_model_round_view, get_model_round_glb

    # Invalid model_id (traversal attempt)
    with pytest.raises(HTTPException) as exc:
        get_model_round_view("../../../etc/passwd", 0, "iso")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        get_model_round_glb("../../../etc/passwd", 0)
    assert exc.value.status_code == 400

    # Negative round_idx
    valid_id = "0123456789abcdef0123456789abcdef"
    with pytest.raises(HTTPException) as exc:
        get_model_round_view(valid_id, -1, "iso")
    assert exc.value.status_code == 400

    with pytest.raises(HTTPException) as exc:
        get_model_round_glb(valid_id, -1)
    assert exc.value.status_code == 400

    # Invalid / empty view_name (traversal attempt)
    with pytest.raises(HTTPException) as exc:
        get_model_round_view(valid_id, 0, "../..")
    assert exc.value.status_code == 400

