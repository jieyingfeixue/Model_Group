"""Regression tests for modality-aware pipeline sensor selection."""

from __future__ import annotations

import numpy as np

from src.core.pipeline import _pick_lidar
from src.core.types import FrameData


def _points() -> np.ndarray:
    return np.zeros((4, 4), dtype=np.float32)


def test_radar_pointcloud_is_not_selected_as_lidar():
    frame = FrameData(pointclouds={"radar_mmwave": _points()})
    assert _pick_lidar(frame) is None


def test_named_lidar_is_selected_when_radar_is_also_present():
    frame = FrameData(pointclouds={
        "radar_mmwave": _points(),
        "lidar_at360": _points(),
    })
    assert _pick_lidar(frame) == "lidar_at360"
