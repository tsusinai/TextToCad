import pytest
import math

import ir_validate
from ir_validate import validate_ir, IRValidationError
import ir_executor
from ir_executor import _apply_mount, _topological_nodes, _node_shape, IRExecutionError


class MockBBox:
    def __init__(self, xmin, xmax, ymin, ymax, zmin, zmax):
        self.xmin = float(xmin)
        self.xmax = float(xmax)
        self.ymin = float(ymin)
        self.ymax = float(ymax)
        self.zmin = float(zmin)
        self.zmax = float(zmax)
        self.xlen = self.xmax - self.xmin
        self.ylen = self.ymax - self.ymin
        self.zlen = self.zmax - self.zmin


class MockShape:
    def __init__(self, xmin, xmax, ymin, ymax, zmin, zmax):
        self.bbox = MockBBox(xmin, xmax, ymin, ymax, zmin, zmax)
        self.rotations = []
        self.translations = []

    def val(self):
        return self

    def BoundingBox(self):
        return self.bbox

    def rotate(self, origin, axis, angle):
        new_shape = MockShape(
            self.bbox.xmin, self.bbox.xmax,
            self.bbox.ymin, self.bbox.ymax,
            self.bbox.zmin, self.bbox.zmax,
        )
        new_shape.rotations = list(self.rotations) + [(origin, axis, angle)]
        new_shape.translations = list(self.translations)
        if axis == (1, 0, 0) and angle == -90:
            new_shape.bbox = MockBBox(
                self.bbox.xmin, self.bbox.xmax,
                self.bbox.zmin, self.bbox.zmax,
                -self.bbox.ymax, -self.bbox.ymin,
            )
        elif axis == (1, 0, 0) and angle == 90:
            new_shape.bbox = MockBBox(
                self.bbox.xmin, self.bbox.xmax,
                -self.bbox.zmax, -self.bbox.zmin,
                self.bbox.ymin, self.bbox.ymax,
            )
        elif axis == (0, 1, 0) and angle == 90:
            new_shape.bbox = MockBBox(
                self.bbox.zmin, self.bbox.zmax,
                self.bbox.ymin, self.bbox.ymax,
                -self.bbox.xmax, -self.bbox.xmin,
            )
        elif axis == (0, 1, 0) and angle == -90:
            new_shape.bbox = MockBBox(
                -self.bbox.zmax, -self.bbox.zmin,
                self.bbox.ymin, self.bbox.ymax,
                self.bbox.xmin, self.bbox.xmax,
            )
        return new_shape

    def translate(self, vec):
        dx, dy, dz = vec
        new_shape = MockShape(
            self.bbox.xmin + dx, self.bbox.xmax + dx,
            self.bbox.ymin + dy, self.bbox.ymax + dy,
            self.bbox.zmin + dz, self.bbox.zmax + dz,
        )
        new_shape.rotations = list(self.rotations)
        new_shape.translations = list(self.translations) + [vec]
        return new_shape


# =========================================================================
# Validation Tests for ir_validate.py
# =========================================================================

def test_validate_ir_accepts_valid_mount_configuration():
    doc = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "hull",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [100, 60, 20]},
            },
            {
                "id": "turret",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 15, "height": 10},
                "mount": {
                    "target": "hull",
                    "face": ">Z",
                    "align": "center",
                    "offset": [0, 5, 0],
                    "orientation": "auto",
                },
            },
        ],
        "outputs": [{"id": "main", "node": "turret"}],
    }
    validated = validate_ir(doc)
    assert validated["nodes"][1]["mount"]["target"] == "hull"
    assert validated["nodes"][1]["mount"]["face"] == ">Z"
    assert validated["nodes"][1]["mount"]["align"] == "center"
    assert validated["nodes"][1]["mount"]["offset"] == [0, 5, 0]


def test_validate_ir_accepts_named_faces_and_parameters():
    doc = {
        "schema_version": "0.2",
        "parameters": {"dx": {"value": 10.0, "unit": "mm"}},
        "nodes": [
            {
                "id": "base",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [50, 50, 20]},
            },
            {
                "id": "sensor",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [10, 10, 5]},
                "mount": {
                    "target": "base",
                    "face": "front",
                    "align": "flush",
                    "offset": ["dx", 0, 0],
                    "orientation": "forward",
                },
            },
        ],
        "outputs": [{"id": "main", "node": "sensor"}],
    }
    validated = validate_ir(doc)
    assert validated["nodes"][1]["mount"]["face"] == "front"
    assert validated["nodes"][1]["mount"]["align"] == "flush"


def test_validate_ir_rejects_missing_target():
    doc = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "turret",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 15, "height": 10},
                "mount": {"face": ">Z"},
            },
        ],
        "outputs": [{"id": "main", "node": "turret"}],
    }
    with pytest.raises(IRValidationError) as exc:
        validate_ir(doc)
    assert any(i["code"] == "mount_target" for i in exc.value.issues)


def test_validate_ir_rejects_nonexistent_target():
    doc = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "turret",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 15, "height": 10},
                "mount": {"target": "nonexistent_hull", "face": ">Z"},
            },
        ],
        "outputs": [{"id": "main", "node": "turret"}],
    }
    with pytest.raises(IRValidationError) as exc:
        validate_ir(doc)
    assert any(i["code"] == "mount_target" for i in exc.value.issues)


def test_validate_ir_rejects_self_mounting():
    doc = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "solo",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [10, 10, 10]},
                "mount": {"target": "solo", "face": ">Z"},
            },
        ],
        "outputs": [{"id": "main", "node": "solo"}],
    }
    with pytest.raises(IRValidationError) as exc:
        validate_ir(doc)
    assert any(i["code"] == "mount_target" for i in exc.value.issues)


def test_validate_ir_rejects_cyclic_mount_dependency():
    doc = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "node_a",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [10, 10, 10]},
                "mount": {"target": "node_b", "face": ">Z"},
            },
            {
                "id": "node_b",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [10, 10, 10]},
                "mount": {"target": "node_a", "face": ">Z"},
            },
        ],
        "outputs": [{"id": "main", "node": "node_a"}],
    }
    with pytest.raises(IRValidationError) as exc:
        validate_ir(doc)
    assert any(i["code"] == "cycle" for i in exc.value.issues)


def test_validate_ir_rejects_invalid_face_and_align():
    doc = {
        "schema_version": "0.2",
        "nodes": [
            {"id": "base", "kind": "primitive", "operation": "box", "parameters": {"size": [10, 10, 10]}},
            {
                "id": "part",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [5, 5, 5]},
                "mount": {"target": "base", "face": "diagonal_invalid", "align": "skewed_invalid"},
            },
        ],
        "outputs": [{"id": "main", "node": "part"}],
    }
    with pytest.raises(IRValidationError) as exc:
        validate_ir(doc)
    codes = {i["code"] for i in exc.value.issues}
    assert "mount_face" in codes
    assert "mount_align" in codes


def test_validate_ir_rejects_invalid_offset_and_orientation():
    doc = {
        "schema_version": "0.2",
        "nodes": [
            {"id": "base", "kind": "primitive", "operation": "box", "parameters": {"size": [10, 10, 10]}},
            {
                "id": "part",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [5, 5, 5]},
                "mount": {"target": "base", "orientation": "upside_down_invalid", "offset": [1, 2]},
            },
        ],
        "outputs": [{"id": "main", "node": "part"}],
    }
    with pytest.raises(IRValidationError) as exc:
        validate_ir(doc)
    codes = {i["code"] for i in exc.value.issues}
    assert "mount_orientation" in codes
    assert "mount_offset" in codes


# =========================================================================
# Geometry & Orientation Tests for ir_executor.py
# =========================================================================

def test_topological_sort_orders_mounted_children_after_hosts():
    nodes = [
        {"id": "barrel", "mount": {"target": "turret"}},
        {"id": "hull"},
        {"id": "turret", "mount": {"target": "hull"}},
    ]
    ordered = _topological_nodes(nodes)
    ids = [n["id"] for n in ordered]
    assert ids.index("hull") < ids.index("turret")
    assert ids.index("turret") < ids.index("barrel")


def test_mount_top_face_z_positive_contact_and_centering():
    # Host: box 100x60x20 centered at origin in XY, Z in [0, 20]
    host = MockShape(-50, 50, -30, 30, 0, 20)
    # Child: turret box 30x30x10, centered in XY, Z in [0, 10]
    child = MockShape(-15, 15, -15, 15, 0, 10)
    node = {"id": "turret", "operation": "box"}
    mount = {"target": "hull", "face": ">Z", "align": "center"}
    shapes = {"hull": host}

    placed = _apply_mount(child, node, mount, shapes, {})
    # Bottom of child (zmin) must touch top of host (zmax = 20)
    assert math.isclose(placed.bbox.zmin, 20.0)
    assert math.isclose(placed.bbox.zmax, 30.0)
    # Center must match host center (xmid = 0, ymid = 0)
    assert math.isclose((placed.bbox.xmin + placed.bbox.xmax) / 2.0, 0.0)
    assert math.isclose((placed.bbox.ymin + placed.bbox.ymax) / 2.0, 0.0)


def test_mount_bottom_face_z_negative_contact():
    host = MockShape(-50, 50, -30, 30, 0, 20)
    # Child: foot box 20x20x5, Z in [0, 5]
    child = MockShape(-10, 10, -10, 10, 0, 5)
    node = {"id": "foot", "operation": "box"}
    mount = {"target": "hull", "face": "<Z", "align": "center"}
    shapes = {"hull": host}

    placed = _apply_mount(child, node, mount, shapes, {})
    # Top of child (zmax) must touch bottom of host (zmin = 0)
    assert math.isclose(placed.bbox.zmax, 0.0)
    assert math.isclose(placed.bbox.zmin, -5.0)


def test_mount_front_face_y_positive_auto_rotates_cylinder():
    # Host: turret 30x30x10, X in [-15, 15], Y in [-15, 15], Z in [20, 30]
    host = MockShape(-15, 15, -15, 15, 20, 30)
    # Barrel: cylinder r=2, h=40 originally along Z in [0, 40]
    child = MockShape(-2, 2, -2, 2, 0, 40)
    node = {"id": "gun_barrel", "operation": "cylinder"}
    mount = {"target": "turret", "face": ">Y", "orientation": "auto"}
    shapes = {"turret": host}

    placed = _apply_mount(child, node, mount, shapes, {})
    # Cylinder must be rotated -90 deg around X so it points horizontally along +Y
    assert ((0, 0, 0), (1, 0, 0), -90) in placed.rotations
    # Contact face (ymin) must touch front of host (ymax = 15)
    assert math.isclose(placed.bbox.ymin, 15.0)
    # Tip of barrel must be at ymax = 15 + 40 = 55
    assert math.isclose(placed.bbox.ymax, 55.0)
    # Height center in Z must align with turret center in Z (zmid = 25)
    assert math.isclose((placed.bbox.zmin + placed.bbox.zmax) / 2.0, 25.0)
    # X center must align with turret center in X (xmid = 0)
    assert math.isclose((placed.bbox.xmin + placed.bbox.xmax) / 2.0, 0.0)


def test_mount_back_face_y_negative_auto_rotates_cylinder():
    host = MockShape(-15, 15, -15, 15, 20, 30)
    child = MockShape(-2, 2, -2, 2, 0, 40)
    node = {"id": "exhaust_pipe", "operation": "cylinder"}
    mount = {"target": "turret", "face": "<Y", "orientation": "auto"}
    shapes = {"turret": host}

    placed = _apply_mount(child, node, mount, shapes, {})
    # Cylinder rotated 90 deg around X so it points along -Y
    assert ((0, 0, 0), (1, 0, 0), 90) in placed.rotations
    # Contact face (ymax) must touch back of host (ymin = -15)
    assert math.isclose(placed.bbox.ymax, -15.0)
    # Tip extends backwards to -15 - 40 = -55
    assert math.isclose(placed.bbox.ymin, -55.0)


def test_mount_right_face_x_positive_auto_rotates_cylinder():
    # Chassis: box 100x60x20, X in [-50, 50], Y in [-30, 30], Z in [0, 20]
    host = MockShape(-50, 50, -30, 30, 0, 20)
    # Wheel: cylinder r=15, h=10 along Z
    child = MockShape(-15, 15, -15, 15, 0, 10)
    node = {"id": "wheel_right", "operation": "cylinder"}
    mount = {"target": "chassis", "face": ">X", "orientation": "auto"}
    shapes = {"chassis": host}

    placed = _apply_mount(child, node, mount, shapes, {})
    # Cylinder rotated 90 deg around Y so it points along +X
    assert ((0, 0, 0), (0, 1, 0), 90) in placed.rotations
    # Contact face (xmin) touches right face (xmax = 50)
    assert math.isclose(placed.bbox.xmin, 50.0)
    assert math.isclose(placed.bbox.xmax, 60.0)


def test_mount_left_face_x_negative_auto_rotates_cylinder():
    host = MockShape(-50, 50, -30, 30, 0, 20)
    child = MockShape(-15, 15, -15, 15, 0, 10)
    node = {"id": "wheel_left", "operation": "cylinder"}
    mount = {"target": "chassis", "face": "<X", "orientation": "auto"}
    shapes = {"chassis": host}

    placed = _apply_mount(child, node, mount, shapes, {})
    # Cylinder rotated -90 deg around Y so it points along -X
    assert ((0, 0, 0), (0, 1, 0), -90) in placed.rotations
    # Contact face (xmax) touches left face (xmin = -50)
    assert math.isclose(placed.bbox.xmax, -50.0)
    assert math.isclose(placed.bbox.xmin, -60.0)


def test_mount_flush_alignment_and_offset():
    host = MockShape(0, 100, 0, 60, 0, 20)
    child = MockShape(0, 20, 0, 20, 0, 10)
    node = {"id": "corner_bracket", "operation": "box"}
    mount = {
        "target": "base",
        "face": "top",
        "align": "flush",
        "offset": [5, 10, 0],
    }
    shapes = {"base": host}

    placed = _apply_mount(child, node, mount, shapes, {})
    # Sits on top of host z=20
    assert math.isclose(placed.bbox.zmin, 20.0)
    # Flush with min x and min y, plus offset [5, 10, 0]
    assert math.isclose(placed.bbox.xmin, 5.0)
    assert math.isclose(placed.bbox.ymin, 10.0)


def test_mount_box_on_front_face_does_not_auto_rotate():
    # Armor plate: box 40x5x15 on front face of hull
    host = MockShape(-50, 50, -30, 30, 0, 20)
    plate = MockShape(-20, 20, 0, 5, 0, 15)
    node = {"id": "front_armor", "operation": "box"}
    mount = {"target": "hull", "face": ">Y", "orientation": "auto"}
    shapes = {"hull": host}

    placed = _apply_mount(plate, node, mount, shapes, {})
    # Box should NOT have been rotated
    assert len(placed.rotations) == 0
    # Back face of plate (ymin=0) touches front of hull (ymax=30)
    assert math.isclose(placed.bbox.ymin, 30.0)
    assert math.isclose(placed.bbox.ymax, 35.0)
    # Centered in X and Z
    assert math.isclose((placed.bbox.xmin + placed.bbox.xmax) / 2.0, 0.0)
    assert math.isclose((placed.bbox.zmin + placed.bbox.zmax) / 2.0, 10.0)


def test_mount_cylinder_with_axial_orientation_keeps_original_axis():
    host = MockShape(-50, 50, -30, 30, 0, 20)
    cyl = MockShape(-5, 5, -5, 5, 0, 20)
    node = {"id": "vertical_sensor", "operation": "cylinder"}
    mount = {"target": "hull", "face": ">Y", "orientation": "axial"}
    shapes = {"hull": host}

    placed = _apply_mount(cyl, node, mount, shapes, {})
    # "axial" should NOT trigger orthogonal auto-rotation
    assert len(placed.rotations) == 0
    # Back face of cylinder (ymin=-5) touches front of hull (ymax=30)
    assert math.isclose(placed.bbox.ymin, 30.0)


def test_chained_assembly_mounting_hull_turret_barrel():
    # 1. Hull: box 100x60x20
    hull = MockShape(-50, 50, -30, 30, 0, 20)
    shapes = {"hull": hull}

    # 2. Turret: box 30x30x10 mounted on hull >Z
    raw_turret = MockShape(-15, 15, -15, 15, 0, 10)
    turret_node = {"id": "turret", "operation": "box", "mount": {"target": "hull", "face": ">Z"}}
    mounted_turret = _apply_mount(raw_turret, turret_node, turret_node["mount"], shapes, {})
    shapes["turret"] = mounted_turret

    assert math.isclose(mounted_turret.bbox.zmin, 20.0)
    assert math.isclose(mounted_turret.bbox.zmax, 30.0)

    # 3. Gun barrel: cylinder r=2, h=50 mounted on turret >Y
    raw_barrel = MockShape(-2, 2, -2, 2, 0, 50)
    barrel_node = {"id": "barrel", "operation": "cylinder", "mount": {"target": "turret", "face": ">Y", "orientation": "auto"}}
    mounted_barrel = _apply_mount(raw_barrel, barrel_node, barrel_node["mount"], shapes, {})
    shapes["barrel"] = mounted_barrel

    # Barrel should be rotated -90 around X
    assert ((0, 0, 0), (1, 0, 0), -90) in mounted_barrel.rotations
    # Barrel base attaches to front of mounted turret (ymax = 15)
    assert math.isclose(mounted_barrel.bbox.ymin, 15.0)
    # Barrel tip reaches 15 + 50 = 65
    assert math.isclose(mounted_barrel.bbox.ymax, 65.0)
    # Barrel height center is at turret center in Z (which is (20 + 30)/2 = 25)
    assert math.isclose((mounted_barrel.bbox.zmin + mounted_barrel.bbox.zmax) / 2.0, 25.0)
    # Barrel is never buried, never floating!


@pytest.mark.skipif(ir_executor.cq is None, reason="CadQuery is required for end-to-end kernel execution")
def test_cadquery_full_assembly_semantic_mount_smoke():
    import app
    ir = {
        "schema_version": "0.2",
        "nodes": [
            {
                "id": "hull",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [100, 60, 20]},
            },
            {
                "id": "turret",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [30, 30, 10]},
                "mount": {"target": "hull", "face": ">Z", "align": "center"},
            },
            {
                "id": "barrel",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 3, "height": 40},
                "mount": {"target": "turret", "face": ">Y", "orientation": "auto"},
            },
            {
                "id": "tank",
                "kind": "feature",
                "operation": "union",
                "inputs": ["hull", "turret", "barrel"],
            },
        ],
        "outputs": [{"id": "main", "node": "tank", "format": ["step"]}],
    }
    validated = app.validate_ir(ir)
    execution = app.execute_ir(validated)
    metrics = app.shape_metrics(execution["shape"])
    assert metrics["valid_brep"] is True
    # Verify overall bounding box reflects proper mounting:
    # Hull Z: 20, Turret Z: 10 with 0.05 mm coplanar overlap -> total Z = 29.95
    assert math.isclose(metrics["bbox_mm"]["z"], 29.95, abs_tol=1e-2)
    # Hull Y: [-30, 30], Turret Y: [-15, 15], Barrel with 1.5 mm side cylinder overlap
    # extends from 15 - 1.5 = 13.5 to 13.5 + 40 = 53.5 -> Total Y: [-30, 53.5] -> 83.5
    assert math.isclose(metrics["bbox_mm"]["y"], 83.5, abs_tol=1e-2)

