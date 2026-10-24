"""Node shape cache correctness and degraded-operation visibility tests.

These tests guard two executor behaviors:
1. `_NODE_SHAPE_CACHE` keys must capture everything that influences a node's
   geometry: resolved parameters, input geometry hashes, the mount target's
   geometry, and the node's own top-level fields (id/frame/rotation/orientation).
2. Silent fillet/chamfer/shell fallbacks must surface in the execution trace
   as `degraded_operations` entries.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ir_executor
from ir_executor import execute_ir


pytestmark = pytest.mark.skipif(ir_executor.cq is None, reason="requires the CadQuery kernel")


@pytest.fixture(autouse=True)
def _clear_shape_cache():
    with ir_executor._NODE_SHAPE_CACHE_LOCK:
        ir_executor._NODE_SHAPE_CACHE.clear()
    yield
    with ir_executor._NODE_SHAPE_CACHE_LOCK:
        ir_executor._NODE_SHAPE_CACHE.clear()


def _bbox(shape):
    values = ir_executor._get_shape_bbox(shape)
    return (values.xmin, values.xmax, values.ymin, values.ymax, values.zmin, values.zmax)


def _mounted_turret_ir(hull_height):
    """Tank-style fixture: turret cylinder mounted on the hull top face."""
    return {
        "schema_version": "0.2",
        "parameters": {},
        "nodes": [
            {
                "id": "hull",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [100.0, 60.0, hull_height]},
            },
            {
                "id": "turret",
                "kind": "primitive",
                "operation": "cylinder",
                "mount": {"target": "hull", "face": ">Z", "align": "center"},
                "parameters": {"radius": 15.0, "height": 10.0},
            },
            {
                "id": "assembly",
                "kind": "feature",
                "operation": "union",
                "inputs": ["hull", "turret"],
                "parameters": {},
            },
        ],
        "outputs": [{"id": "main", "node": "assembly"}],
    }


def test_cache_miss_when_mount_target_geometry_changes():
    first = execute_ir(_mounted_turret_ir(25.0))
    second = execute_ir(_mounted_turret_ir(40.0))

    first_bbox = _bbox(first["node_shapes"]["turret"])
    second_bbox = _bbox(second["node_shapes"]["turret"])
    # The turret sits on the hull top face; a taller hull must lift it.
    assert second_bbox[4] > first_bbox[4] + 10.0


def test_cache_miss_when_node_rotation_differs():
    def beam_ir(rotation):
        node = {
            "id": "beam",
            "kind": "primitive",
            "operation": "box",
            "parameters": {"size": [40.0, 10.0, 6.0]},
        }
        if rotation is not None:
            node["rotation"] = rotation
        return {
            "schema_version": "0.2",
            "parameters": {},
            "nodes": [node],
            "outputs": [{"id": "main", "node": "beam"}],
        }

    flat = execute_ir(beam_ir(None))
    rotated = execute_ir(beam_ir({"axis": "x", "degrees": 90.0}))

    flat_bbox = _bbox(flat["shape"])
    rotated_bbox = _bbox(rotated["shape"])
    assert abs(flat_bbox[3] - flat_bbox[2]) == pytest.approx(10.0, abs=1e-6)
    assert abs(rotated_bbox[3] - rotated_bbox[2]) == pytest.approx(6.0, abs=1e-6)


def test_cache_hit_when_identical_ir(monkeypatch):
    ir = {
        "schema_version": "0.2",
        "parameters": {},
        "nodes": [
            {
                "id": "base",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [30.0, 20.0, 10.0]},
            },
            {
                "id": "pillar",
                "kind": "primitive",
                "operation": "cylinder",
                "parameters": {"radius": 4.0, "height": 12.0},
            },
            {
                "id": "part",
                "kind": "feature",
                "operation": "union",
                "inputs": ["base", "pillar"],
                "parameters": {},
            },
        ],
        "outputs": [{"id": "main", "node": "part"}],
    }

    executed_ids = []
    original = ir_executor._raw_node_shape

    def counting_raw_node_shape(node, *args, **kwargs):
        executed_ids.append(str(node.get("id")))
        return original(node, *args, **kwargs)

    monkeypatch.setattr(ir_executor, "_raw_node_shape", counting_raw_node_shape)

    first = execute_ir(ir)
    assert executed_ids == ["base", "pillar", "part"]

    second = execute_ir(ir)
    assert executed_ids == ["base", "pillar", "part"]  # fully served from cache
    assert _bbox(first["shape"]) == pytest.approx(_bbox(second["shape"]))


def test_cache_hit_refreshes_recency_for_lru_eviction(monkeypatch):
    executed_ids = []
    original = ir_executor._raw_node_shape

    def counting_raw_node_shape(node, *args, **kwargs):
        executed_ids.append(str(node.get("id")))
        return original(node, *args, **kwargs)

    monkeypatch.setattr(ir_executor, "_raw_node_shape", counting_raw_node_shape)

    def box_ir(index):
        return {
            "schema_version": "0.2",
            "parameters": {},
            "nodes": [
                {
                    "id": f"box_{index}",
                    "kind": "primitive",
                    "operation": "box",
                    "parameters": {"size": [float(index), 10.0, 10.0]},
                }
            ],
            "outputs": [{"id": "main", "node": f"box_{index}"}],
        }

    capacity = ir_executor._MAX_SHAPE_CACHE_SIZE
    for index in range(1, capacity + 1):
        execute_ir(box_ir(index))
    assert len(executed_ids) == capacity

    # Touch the oldest entry, then overflow the cache: the freshly touched
    # entry must survive while the untouched runner-up becomes the LRU victim.
    execute_ir(box_ir(1))
    assert len(executed_ids) == capacity
    execute_ir(box_ir(capacity + 1))
    assert len(executed_ids) == capacity + 1

    execute_ir(box_ir(2))  # evicted by the overflow above
    assert executed_ids.count("box_2") == 2
    execute_ir(box_ir(1))  # still resident thanks to the recency refresh
    assert executed_ids.count("box_1") == 1


def _degraded_fillet_ir():
    return {
        "schema_version": "0.2",
        "parameters": {},
        "nodes": [
            {
                "id": "block",
                "kind": "primitive",
                "operation": "box",
                "parameters": {"size": [20.0, 20.0, 10.0]},
            },
            {
                "id": "rounded",
                "kind": "feature",
                "operation": "fillet",
                "inputs": ["block"],
                # Radius exceeds half of the smallest dimension, so OCCT cannot
                # apply the fillet and the executor must fall back to the base.
                "parameters": {"radius": 9.0},
            },
        ],
        "outputs": [{"id": "main", "node": "rounded"}],
    }


def test_degraded_fillet_recorded():
    execution = execute_ir(_degraded_fillet_ir())

    # Geometry is still returned (fallback to the base input), never raised.
    bbox = _bbox(execution["shape"])
    assert (bbox[1] - bbox[0], bbox[3] - bbox[2], bbox[5] - bbox[4]) == pytest.approx((20.0, 20.0, 10.0))

    trace_by_id = {event["id"]: event for event in execution["trace"]}
    degraded = trace_by_id["rounded"].get("degraded_operations")
    assert degraded, "fillet fallback must be recorded in the trace"
    assert degraded[0]["op"] == "fillet"
    assert degraded[0]["reason"]


def test_degraded_operations_survive_cache_hit():
    first = execute_ir(_degraded_fillet_ir())
    second = execute_ir(_degraded_fillet_ir())

    for execution in (first, second):
        trace_by_id = {event["id"]: event for event in execution["trace"]}
        degraded = trace_by_id["rounded"].get("degraded_operations")
        assert degraded and degraded[0]["op"] == "fillet"
