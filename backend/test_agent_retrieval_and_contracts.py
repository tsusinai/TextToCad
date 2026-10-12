"""Unit tests for feature_catalog, agent_contracts, and ir_registry."""
import pytest
from feature_catalog import retrieve_feature_recipes, FEATURE_RECIPES
from agent_contracts import extract_requirement_spec, verify_requirement_spec
from ir_registry import OPERATION_SPECS, ALLOWED_OPERATIONS, get_operation_spec, validate_operation_node


def test_feature_catalog_retrieves_relevant_recipes():
    # Hole pattern prompt
    r_holes = retrieve_feature_recipes("A circular flange with 4 mounting holes and a central bore")
    assert len(r_holes) > 0
    assert any(item["id"] == "mounting_hole_pattern" for item in r_holes)

    # Finned heat sink prompt
    r_fins = retrieve_feature_recipes("A heat sink base with 5 cooling fins and a chip pocket")
    assert len(r_fins) > 0
    assert any(item["id"] == "linear_fins" for item in r_fins)

    # Stepped shaft prompt
    r_shaft = retrieve_feature_recipes("A 3-tier stepped shaft with large, mid, and output diameters")
    assert len(r_shaft) > 0
    assert any(item["id"] == "stepped_shaft" for item in r_shaft)

    # Dovetail prompt
    r_dove = retrieve_feature_recipes("A linear slide base with a dovetail slot profile")
    assert len(r_dove) > 0
    assert any(item["id"] == "dovetail_base" for item in r_dove)

    # Gear prompt
    r_gear = retrieve_feature_recipes("A spur gear with 16 teeth and pitch diameter 48 mm")
    assert len(r_gear) > 0
    assert any(item["id"] == "gear_like_pattern" for item in r_gear)


def test_agent_contracts_extracts_structured_requirements():
    spec1 = extract_requirement_spec("A flange with 4 mounting holes and 2mm chamfer")
    features = {f["kind"]: f for f in spec1.get("features", [])}
    assert "hole_pattern" in features
    assert features["hole_pattern"].get("count") == 4
    assert "edge_treatment" in features

    spec2 = extract_requirement_spec("Heat sink with 5 fins and hollow pocket")
    features2 = {f["kind"]: f for f in spec2.get("features", [])}
    assert "fins" in features2
    assert features2["fins"].get("count") == 5
    assert "shell" in features2


def test_agent_contracts_verifies_requirement_spec():
    spec = extract_requirement_spec("A flange with 4 mounting holes")
    # IR missing holes
    empty_ir = {"nodes": [{"id": "base", "operation": "cylinder"}], "outputs": [{"node": "base"}]}
    issues = verify_requirement_spec(spec, empty_ir)
    assert len(issues) > 0
    assert any("hole" in i.get("issue", "").lower() for i in issues)

    # IR with 4 cutters
    complete_ir = {
        "nodes": [
            {"id": "base", "operation": "cylinder"},
            {"id": "cutter_0", "operation": "cylinder"},
            {"id": "cutter_1", "operation": "cylinder"},
            {"id": "cutter_2", "operation": "cylinder"},
            {"id": "cutter_3", "operation": "cylinder"},
            {"id": "cut_node", "operation": "cut", "inputs": ["base", "cutter_0", "cutter_1", "cutter_2", "cutter_3"]}
        ],
        "outputs": [{"node": "cut_node"}]
    }
    issues_ok = verify_requirement_spec(spec, complete_ir)
    assert len(issues_ok) == 0


def test_ir_registry_operation_contracts():
    assert "box" in ALLOWED_OPERATIONS
    assert "cylinder" in ALLOWED_OPERATIONS
    assert "cut" in ALLOWED_OPERATIONS
    assert "union" in ALLOWED_OPERATIONS
    assert "linear_pattern" in ALLOWED_OPERATIONS
    assert "polar_pattern" in ALLOWED_OPERATIONS
    assert "unregistered_magic_op" not in ALLOWED_OPERATIONS

    cut_contract = get_operation_spec("cut")
    assert cut_contract is not None
    assert cut_contract.min_inputs == 1

    box_contract = get_operation_spec("box")
    assert box_contract is not None
    # Validate node
    valid_box = {"id": "my_box", "operation": "box", "parameters": {"width": 10, "depth": 10, "height": 10}}
    issues = validate_operation_node(valid_box, "nodes[0]")
    assert len(issues) == 0


def test_feature_catalog_retrieves_composite_assembly_recipes():
    # Tank assembly prompt (English)
    r_tank = retrieve_feature_recipes("Assemble a tank chassis with turret and barrel")
    assert len(r_tank) > 0
    assert any(item["id"] == "tank_chassis_assembly" for item in r_tank)
    tank_recipe = next(item for item in r_tank if item["id"] == "tank_chassis_assembly")
    assert "turret" in tank_recipe["graph"][3]
    assert "barrel" in tank_recipe["graph"][4]
    assert "hull proportions" in tank_recipe["checks"]

    # Tank assembly prompt (Chinese)
    r_tank_cn = retrieve_feature_recipes("履带坦克与旋转炮塔")
    assert len(r_tank_cn) > 0
    assert any(item["id"] == "tank_chassis_assembly" for item in r_tank_cn)

    # Vehicle chassis with wheels prompt (English)
    r_car = retrieve_feature_recipes("A wheeled vehicle with car chassis and four wheels")
    assert len(r_car) > 0
    assert any(item["id"] == "vehicle_chassis_wheels" for item in r_car)
    car_recipe = next(item for item in r_car if item["id"] == "vehicle_chassis_wheels")
    assert "cabin" in car_recipe["graph"][1]
    assert "wheel" in car_recipe["graph"][2]
    assert "wheel symmetry" in car_recipe["checks"]

    # Vehicle prompt (Chinese)
    r_car_cn = retrieve_feature_recipes("小车底盘与车轮")
    assert len(r_car_cn) > 0
    assert any(item["id"] == "vehicle_chassis_wheels" for item in r_car_cn)

    # Pulley bracket assembly prompt (English)
    r_pulley = retrieve_feature_recipes("A pulley bracket assembly with center shaft and sheave")
    assert len(r_pulley) > 0
    assert any(item["id"] == "pulley_bracket_assembly" for item in r_pulley)
    pulley_recipe = next(item for item in r_pulley if item["id"] == "pulley_bracket_assembly")
    assert "shaft" in pulley_recipe["graph"][1]
    assert "pulley" in pulley_recipe["graph"][2]

    # Pulley prompt (Chinese)
    r_pulley_cn = retrieve_feature_recipes("带中心轴的滑轮支架")
    assert len(r_pulley_cn) > 0
    assert any(item["id"] == "pulley_bracket_assembly" for item in r_pulley_cn)


def test_feature_metrics_detect_vertical_stacking():
    from feature_metrics import detect_vertical_stacking

    class MockBox:
        def __init__(self, xmin, xmax, ymin, ymax, zmin, zmax):
            self.xmin, self.xmax = xmin, xmax
            self.ymin, self.ymax = ymin, ymax
            self.zmin, self.zmax = zmin, zmax
            self.xlen, self.ylen, self.zlen = xmax - xmin, ymax - ymin, zmax - zmin

    class MockSolid:
        def __init__(self, box):
            self._box = box
        def BoundingBox(self):
            return self._box

    # Multi-solid: hull base with turret stacked on top
    hull = MockSolid(MockBox(-50, 50, -25, 25, 0, 20))
    turret = MockSolid(MockBox(-15, 15, -15, 15, 20, 35))
    barrel = MockSolid(MockBox(-3, 3, 10, 55, 25, 31))

    stacked = detect_vertical_stacking(solids=[hull, turret, barrel])
    assert stacked["detected"] is True
    assert stacked["confidence"] == "high"
    assert stacked["stage_count"] >= 2
    assert stacked["base_zmin"] == 0.0
    assert stacked["base_zmax"] == 20.0
    assert stacked["stacked_height_mm"] == 35.0

    # Multi-solid negative case: single solid or side-by-side without vertical stack
    single_box = MockSolid(MockBox(-10, 10, -10, 10, 0, 20))
    assert detect_vertical_stacking(solids=[single_box])["detected"] is False

    # Single-solid with tiered planar faces and vertical cylinder
    planar_faces = [
        {"center": (0, 0, 0), "normal": (0, 0, -1), "area_mm2": 5000},
        {"center": (0, 0, 20), "normal": (0, 0, 1), "area_mm2": 4000},
        {"center": (0, 0, 35), "normal": (0, 0, 1), "area_mm2": 700},
    ]
    cylindrical_faces = [
        {"axis": (0, 0, 1), "center": (0, 0, 27.5), "radius_mm": 15, "extent_mm": 15},
    ]
    bounds = {"xmin": -50, "xmax": 50, "ymin": -25, "ymax": 25, "zmin": 0, "zmax": 35, "xlen": 100, "ylen": 50, "zlen": 35}

    res_single = detect_vertical_stacking(planar_faces=planar_faces, cylindrical_faces=cylindrical_faces, bounds=bounds)
    assert res_single["detected"] is True
    assert res_single["stage_count"] >= 2
    assert res_single["confidence"] == "high"


def test_feature_metrics_detect_horizontal_protrusion():
    from feature_metrics import detect_horizontal_protrusion

    class MockBox:
        def __init__(self, xmin, xmax, ymin, ymax, zmin, zmax):
            self.xmin, self.xmax = xmin, xmax
            self.ymin, self.ymax = ymin, ymax
            self.zmin, self.zmax = zmin, zmax
            self.xlen, self.ylen, self.zlen = xmax - xmin, ymax - ymin, zmax - zmin

    class MockSolid:
        def __init__(self, box):
            self._box = box
        def BoundingBox(self):
            return self._box

    hull = MockSolid(MockBox(-50, 50, -25, 25, 0, 20))
    barrel = MockSolid(MockBox(-3, 3, 10, 55, 25, 31))  # extends to y=55, hull is y=25

    protrusion = detect_horizontal_protrusion(solids=[hull, barrel])
    assert protrusion["detected"] is True
    assert protrusion["axis"] == "y"
    assert protrusion["direction"] == "+y"
    assert protrusion["protrusion_mm"] == 30.0
    assert protrusion["base_extent_mm"] == 25.0
    assert protrusion["total_extent_mm"] == 55.0

    # Single-solid with forward cylinder
    cylindrical_faces = [
        {"axis": (0, 1, 0), "center": (0, 32.5, 28), "radius_mm": 3, "extent_mm": 45},
    ]
    planar_faces = [
        {"center": (0, 25, 10), "normal": (0, 1, 0), "area_mm2": 2000},
    ]
    bounds = {"xmin": -50, "xmax": 50, "ymin": -25, "ymax": 55, "zmin": 0, "zmax": 35, "xlen": 100, "ylen": 80, "zlen": 35}

    single_protrusion = detect_horizontal_protrusion(
        cylindrical_faces=cylindrical_faces,
        planar_faces=planar_faces,
        bounds=bounds,
    )
    assert single_protrusion["detected"] is True
    assert single_protrusion["axis"] == "y"
    assert single_protrusion["direction"] == "+y"
    assert single_protrusion["protrusion_mm"] == 30.0


def test_measure_occt_features_schema_includes_assembly():
    from feature_metrics import measure_occt_features

    res = measure_occt_features(None)
    assert "assembly" in res
    assert "vertical_stacking" in res["assembly"]
    assert "horizontal_protrusion" in res["assembly"]
    assert res["assembly"]["detected"] is False
    assert res["assembly"]["vertical_stacking"]["detected"] is False
    assert res["assembly"]["horizontal_protrusion"]["detected"] is False

