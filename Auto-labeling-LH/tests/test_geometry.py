"""Tests for geometry utilities."""

from __future__ import annotations

import numpy as np
import pytest

from src.core.types import Label3D
from src.fusion.geometry import (
    angle_diff,
    compute_bev_iou,
    compute_pca_yaw,
    count_points_in_box,
    estimate_ground_plane,
    extract_points_in_box,
)


def test_count_points_in_box():
    pts = np.array([
        [0.0, 0.0, 0.0, 1.0],
        [10.0, 10.0, 10.0, 1.0],
        [0.5, 0.5, 0.5, 1.0],
    ])
    box = Label3D(
        center=np.array([0.0, 0.0, 0.0]),
        dimensions=np.array([2.0, 2.0, 2.0]),
    )
    assert count_points_in_box(pts, box) == 2


def test_extract_points_in_box():
    pts = np.random.randn(100, 4).astype(np.float32)
    box = Label3D(
        center=np.array([0.0, 0.0, 0.0]),
        dimensions=np.array([10.0, 10.0, 10.0]),
    )
    inside = extract_points_in_box(pts, box)
    assert len(inside) > 0


def test_compute_bev_iou_identical():
    box = Label3D(
        center=np.array([0.0, 0.0, 0.0]),
        dimensions=np.array([4.0, 2.0, 1.5]),
    )
    iou = compute_bev_iou(box, box)
    assert iou > 0.99


def test_compute_bev_iou_no_overlap():
    a = Label3D(center=np.array([0.0, 0.0, 0.0]), dimensions=np.array([2.0, 2.0, 1.0]))
    b = Label3D(center=np.array([100.0, 100.0, 0.0]), dimensions=np.array([2.0, 2.0, 1.0]))
    iou = compute_bev_iou(a, b)
    assert iou < 0.01


def test_angle_diff():
    assert np.isclose(angle_diff(0.0, np.pi), np.pi, atol=0.01)
    assert np.isclose(angle_diff(0.1, 0.1), 0.0, atol=0.01)


def test_estimate_ground_plane():
    # Flat ground at z=-1
    pts = np.random.randn(500, 4).astype(np.float32)
    pts[:, 2] = -1.0 + 0.01 * np.random.randn(500)
    plane = estimate_ground_plane(pts, height_percentile=50)
    assert plane is not None
    assert len(plane) == 4


def test_pca_yaw():
    # Points along x-axis
    pts = np.array([[i, 0.0] for i in range(20)], dtype=float)
    yaw = compute_pca_yaw(pts)
    assert np.isclose(abs(yaw), 0.0, atol=0.1)
