"""Tests for core types."""

from __future__ import annotations

import numpy as np
import pytest

from src.core.types import Label3D, SessionState, CalibrationBundle, CameraIntrinsics


def test_label3d_copy():
    box = Label3D(
        class_name="car",
        center=np.array([1.0, 2.0, 3.0]),
        dimensions=np.array([4.0, 1.8, 1.5]),
        rotation=0.5,
    )
    clone = box.copy()
    assert clone.class_name == "car"
    assert np.allclose(clone.center, box.center)
    # Modify clone should not affect original
    clone.center[0] = 99.0
    assert box.center[0] == 1.0


def test_label3d_corners():
    box = Label3D(
        center=np.array([0.0, 0.0, 0.0]),
        dimensions=np.array([4.0, 2.0, 1.0]),
        rotation=0.0,
    )
    corners = box.corners()
    assert corners.shape == (8, 3)
    assert np.isclose(corners[:, 0].max(), 2.0)
    assert np.isclose(corners[:, 1].max(), 1.0)


def test_session_state_get_box():
    state = SessionState()
    box = Label3D(object_id="abc", class_name="car")
    state.boxes.append(box)
    assert state.get_box("abc") is box
    assert state.get_box("xyz") is None


def test_calibration_identity_transform():
    calib = CalibrationBundle()
    T = calib.get_transform("a", "b")
    assert np.allclose(T, np.eye(4))


def test_calibration_projection():
    calib = CalibrationBundle()
    calib.intrinsics["cam"] = CameraIntrinsics(fx=500, fy=500, cx=320, cy=240)
    calib.extrinsics["cam"] = np.eye(4)
    pts = np.array([[0.0, 0.0, 10.0]])
    pix = calib.project_3d_to_image(pts, "cam")
    assert pix.shape == (1, 2)
    assert np.isclose(pix[0, 0], 320.0, atol=1)
    assert np.isclose(pix[0, 1], 240.0, atol=1)
