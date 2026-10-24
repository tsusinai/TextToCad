"""Tests for the metrology annotation rule registry (iteration 4).

These prompt fragments were previously hardcoded inside call_vlm_critic and
never covered by tests; the registry keeps them byte-stable and testable.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from feature_catalog import (
    METROLOGY_RULES,
    collect_metrology_notes,
    horizontal_barrel_fragment,
)


def _cyl(axis, radius=12.0, extent=30.0, center=(0, 0, 5)):
    return {"axis": axis, "radius_mm": radius, "extent_mm": extent, "center": list(center)}


def _metrics(cyls, zmin=0.0, zmax=40.0):
    return {
        "cylindrical_faces": cyls,
        "bounds_mm": {"zmin": zmin, "zmax": zmax},
    }


def test_rolling_wheels_rule_fires_with_two_transverse_cylinders():
    metrics = _metrics([_cyl((1, 0, 0), radius=10), _cyl((-1, 0, 0), radius=9)], zmin=-6.0)
    notes = collect_metrology_notes(metrics)
    assert len(notes) == 1
    assert "VERIFIED 2 ROLLING WHEELS" in notes[0]
    assert "extend 6.0 mm below chassis bottom" in notes[0]
    assert "overall Z=[-6.0, 40.0]" in notes[0]


def test_rolling_wheels_rule_requires_two_large_transverse_cylinders():
    small = _metrics([_cyl((1, 0, 0), radius=5)])
    assert collect_metrology_notes(small) == []
    single = _metrics([_cyl((1, 0, 0), radius=10)])
    assert collect_metrology_notes(single) == []


def test_pipe_manifold_rule_fires_on_orthogonal_axes():
    metrics = _metrics([_cyl((0, 0, 1)), _cyl((1, 0, 0))])
    notes = collect_metrology_notes(metrics)
    assert len(notes) == 1
    assert "Pipe Manifold Junction" in notes[0]
    assert "perpendicular pipe intersection at 90 degrees" in notes[0]


def test_pipe_manifold_rule_ignores_parallel_axes():
    metrics = _metrics([_cyl((0, 0, 1)), _cyl((0, 0, -1))])
    assert collect_metrology_notes(metrics) == []


def test_bearing_housing_rule_reports_bore_diameter():
    metrics = _metrics([_cyl((0, 1, 0), radius=12.5)])
    notes = collect_metrology_notes(metrics)
    assert len(notes) == 1
    assert "Bearing Housing Metrology" in notes[0]
    assert "diameter 25.0 mm" in notes[0]


def test_horizontal_barrel_fragment_reports_longest_horizontal_cylinder():
    metrics = _metrics([_cyl((0, 1, 0), extent=25.0), _cyl((1, 0, 0), extent=40.0)])
    fragment = horizontal_barrel_fragment(metrics)
    assert "full horizontal cylinder length = 40.0 mm" in fragment
    assert "mid-height of upper turret stage" in fragment


def test_horizontal_barrel_fragment_empty_without_horizontal_cylinders():
    assert horizontal_barrel_fragment(_metrics([_cyl((0, 0, 1), extent=50.0)])) == ""
    assert horizontal_barrel_fragment({}) == ""


def test_collect_preserves_registry_order_and_handles_empty():
    metrics = _metrics([
        _cyl((1, 0, 0), radius=10),          # wheels (transverse pair)
        _cyl((-1, 0, 0), radius=10),
        _cyl((0, 0, 1)),                      # orthogonal pipe partner
        _cyl((0, 1, 0), radius=12.5),         # bearing bore
    ])
    notes = collect_metrology_notes(metrics)
    assert [note.split(" (")[0].strip().lstrip("* ") for note in notes] == [
        "Rolling Wheels",
        "Pipe Manifold Junction",
        "Bearing Housing Metrology",
    ]
    assert collect_metrology_notes({}) == []
    assert collect_metrology_notes(None) == []
    assert [rule["id"] for rule in METROLOGY_RULES] == [
        "rolling_wheels", "pipe_manifold", "bearing_housing",
    ]
