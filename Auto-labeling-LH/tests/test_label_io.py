"""Tests for label I/O."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from src.core.types import Label3D
from src.io.label_io import load_labels, save_labels


def test_json_roundtrip():
    boxes = [
        Label3D(object_id="b1", class_name="car",
                center=np.array([1.0, 2.0, 3.0]),
                dimensions=np.array([4.0, 1.8, 1.5]),
                rotation=0.5, score=0.9),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "labels.json"
        save_labels(boxes, path, "json")
        loaded = load_labels(path, "json")
        assert len(loaded) == 1
        assert loaded[0].class_name == "car"
        assert np.allclose(loaded[0].center, [1.0, 2.0, 3.0])


def test_kitti_roundtrip():
    boxes = [
        Label3D(object_id="b1", class_name="Car",
                center=np.array([10.0, 0.0, 1.0]),
                dimensions=np.array([4.5, 1.8, 1.5]),
                rotation=0.0),
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "labels.txt"
        save_labels(boxes, path, "kitti")
        loaded = load_labels(path, "kitti")
        assert len(loaded) == 1
        assert loaded[0].class_name == "Car"
