"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

from src.core.config import load_config, load_profile
from src.io.sensor_profile import sensor_profile_from_dict


def test_load_default_config():
    cfg = load_config()
    assert "app" in cfg
    assert "agent" in cfg
    assert cfg["agent"]["llm_agent"]["model"] == "claude-sonnet-4-20250514"


def test_load_lh_profile():
    profile = load_profile("lh")
    assert profile.get("name") or profile.get("dataset")


def test_lh_profile_preserves_calibration_and_flags():
    profile = sensor_profile_from_dict(load_profile("lh"))

    camera = profile.sensors["camera_main_left"]
    assert camera.path_template.endswith("/{frame_basename}.jpg")
    assert camera.extra["intrinsics"]["fx"] > 1.0
    assert len(camera.extra["extrinsics"]["matrix"]) == 16
    assert profile.sensors["camera_ir"].extra["enabled"] is False
    assert profile.label_format["format"] == "lh"
