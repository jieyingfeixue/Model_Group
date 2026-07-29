"""Tests for the rule engine."""

from __future__ import annotations

import numpy as np
import pytest

from src.core.types import Label3D
from src.agent.rule_engine import RuleEngine
from src.agent.tool_executor import FrameContext


def _make_ctx(boxes=None, lidar=None, ground=None):
    return FrameContext(
        seq_id="1", frame_id="001",
        boxes=boxes or [],
        lidar_points=lidar,
        ground_plane=ground,
    )


def test_lidar_zero_points():
    engine = RuleEngine()
    box = Label3D(object_id="b1", class_name="car",
                  center=np.array([50.0, 50.0, 0.0]),
                  dimensions=np.array([4.0, 1.8, 1.5]))
    pts = np.array([[0.0, 0.0, 0.0, 1.0]])  # Far from box
    ctx = _make_ctx(boxes=[box], lidar=pts)
    results = engine.check_all(box, ctx)
    lidar_result = next(r for r in results if r.rule == "lidar_support")
    assert lidar_result.severity == "error"
    assert lidar_result.auto_action is not None
    assert lidar_result.auto_action.type == "delete"


def test_dimension_prior_ok():
    engine = RuleEngine()
    box = Label3D(object_id="b1", class_name="Sedan",
                  center=np.array([10.0, 0.0, 0.0]),
                  dimensions=np.array([4.5, 1.8, 1.5]))
    ctx = _make_ctx(boxes=[box])
    results = engine.check_all(box, ctx)
    dim_result = next(r for r in results if r.rule == "dimension_prior")
    assert dim_result.severity == "ok"


def test_dimension_prior_warning():
    engine = RuleEngine()
    box = Label3D(object_id="b1", class_name="Sedan",
                  center=np.array([10.0, 0.0, 0.0]),
                  dimensions=np.array([10.0, 5.0, 5.0]))  # Very wrong
    ctx = _make_ctx(boxes=[box])
    results = engine.check_all(box, ctx)
    dim_result = next(r for r in results if r.rule == "dimension_prior")
    assert dim_result.severity == "warning"
    assert dim_result.auto_action is not None


def test_overlap_detection():
    engine = RuleEngine()
    a = Label3D(object_id="a", class_name="car",
                center=np.array([0.0, 0.0, 0.0]),
                dimensions=np.array([4.0, 2.0, 1.5]))
    b = Label3D(object_id="b", class_name="car",
                center=np.array([0.5, 0.0, 0.0]),
                dimensions=np.array([4.0, 2.0, 1.5]))
    ctx = _make_ctx(boxes=[a, b])
    results = engine.check_all(a, ctx)
    overlap_result = next(r for r in results if r.rule == "overlap")
    assert overlap_result.severity == "error"


def test_ground_penetration():
    engine = RuleEngine()
    box = Label3D(object_id="b1", class_name="car",
                  center=np.array([0.0, 0.0, -1.0]),  # Center below ground
                  dimensions=np.array([4.0, 2.0, 1.5]))
    ground = np.array([0.0, 0.0, 1.0, 0.0])  # z=0 plane
    ctx = _make_ctx(boxes=[box], ground=ground)
    results = engine.check_all(box, ctx)
    gp_result = next(r for r in results if r.rule == "ground_penetration")
    assert gp_result.severity == "warning"
