"""Sensor profile loader and schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class SensorEntry:
    name: str = ""
    type: str = ""  # camera | lidar | radar_3d | radar_4d
    path_template: str = ""
    file_extension: str = ""
    resolution: list[int] | None = None
    fov: dict[str, float] | None = None
    channels: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class SensorProfile:
    """Describes a dataset's sensor layout and file conventions."""

    name: str = ""
    dataset: str = ""
    version: str = ""
    base_path: str = ""
    structure: str = ""
    sensors: dict[str, SensorEntry] = field(default_factory=dict)
    calibration: dict[str, Any] = field(default_factory=dict)
    label_format: dict[str, Any] = field(default_factory=dict)
    viewer: dict[str, Any] = field(default_factory=dict)  # UI display hints

    def camera_names(self) -> list[str]:
        return [k for k, v in self.sensors.items() if v.type == "camera"]

    def lidar_names(self) -> list[str]:
        return [k for k, v in self.sensors.items() if v.type == "lidar"]

    def radar_names(self) -> list[str]:
        return [k for k, v in self.sensors.items() if v.type in ("radar_3d", "radar_4d")]


def load_sensor_profile(path_or_name: str | Path, profiles_dir: Path | None = None) -> SensorProfile:
    """Load sensor profile from YAML file or profile name."""
    path = Path(path_or_name)
    if not path.exists() and profiles_dir:
        path = profiles_dir / f"{path_or_name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Sensor profile not found: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return sensor_profile_from_dict(raw)


def sensor_profile_from_dict(raw: dict[str, Any]) -> SensorProfile:
    """Build a :class:`SensorProfile` from the canonical YAML mapping.

    Desktop and Web entry points must use this function so fields such as
    ``intrinsics``, ``extrinsics`` and ``enabled`` are preserved identically.
    The small aliases below keep older profiles readable without maintaining a
    second, subtly different schema in the Web server.
    """
    profile = SensorProfile(
        name=raw.get("name", raw.get("profile_name", "")),
        dataset=raw.get("dataset", ""),
        version=raw.get("version", ""),
        base_path=raw.get("base_path", ""),
        structure=raw.get("structure", ""),
        calibration=raw.get("calibration", {}),
        label_format=raw.get("label_format", raw.get("labels", {})),
        viewer=raw.get("viewer", {}),
    )
    for key, s in raw.get("sensors", {}).items():
        known_fields = {
            "name", "type", "path", "path_template", "data_pattern",
            "extension", "file_extension", "resolution", "fov", "channels",
            "extra",
        }
        extra = dict(s.get("extra", {}) or {})
        extra.update({k: v for k, v in s.items() if k not in known_fields})
        profile.sensors[key] = SensorEntry(
            name=s.get("name", key),
            type=s.get("type", ""),
            path_template=s.get(
                "path", s.get("path_template", s.get("data_pattern", ""))
            ),
            file_extension=s.get("extension", s.get("file_extension", "")),
            resolution=s.get("resolution"),
            fov=s.get("fov"),
            channels=s.get("channels", 0),
            extra=extra,
        )
    return profile
