"""Calibration loader utilities."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np

from src.core.types import CalibrationBundle, CameraIntrinsics

logger = logging.getLogger(__name__)


def load_calibration(calib_dir: Path, profile_calib: dict[str, Any]) -> CalibrationBundle:
    """Load calibration from a directory following the sensor profile spec."""
    bundle = CalibrationBundle()

    # Load intrinsics
    intrinsics_file = calib_dir / profile_calib.get("intrinsics_file", "intrinsics.json")
    if intrinsics_file.exists():
        data = json.loads(intrinsics_file.read_text(encoding="utf-8"))
        for cam, vals in data.items():
            bundle.intrinsics[cam] = CameraIntrinsics(
                fx=vals.get("fx", 1.0),
                fy=vals.get("fy", 1.0),
                cx=vals.get("cx", 0.0),
                cy=vals.get("cy", 0.0),
                distortion=np.array(vals.get("distortion", [0, 0, 0, 0, 0]), dtype=float),
            )

    # Load extrinsics
    extrinsics_file = calib_dir / profile_calib.get("extrinsics_file", "extrinsics.json")
    if extrinsics_file.exists():
        data = json.loads(extrinsics_file.read_text(encoding="utf-8"))
        for sensor, mat in data.items():
            bundle.extrinsics[sensor] = np.array(mat, dtype=float).reshape(4, 4)

    # Try K-Radar style: calib_dir itself contains .txt calibration files
    if not bundle.extrinsics and calib_dir.is_dir():
        bundle = _load_kradar_calib(calib_dir)

    return bundle


def _load_kradar_calib(info_calib_dir: Path) -> CalibrationBundle:
    """Parse K-Radar calibration format.

    Handles both matrix files and the ``calib_radar_lidar.txt`` CSV offset
    format (``frame difference,x,y\\n32,-2.54,0.3``).

    K-Radar file name → standard sensor key mapping::

        calib_radar_lidar.txt          → extrinsics["calib_radar_lidar"]
        calib_lidar_camera_front.txt   → extrinsics["cam-front"]
        calib_lidar_camera_left.txt    → extrinsics["cam-left"]
        calib_lidar_camera_rear.txt    → extrinsics["cam-rear"]
        calib_lidar_camera_right.txt   → extrinsics["cam-right"]
        calib_camera_front_intrinsic.txt → intrinsics["cam-front"]
        calib_camera_left_intrinsic.txt  → intrinsics["cam-left"]
        etc.
    """
    # Map K-Radar file stems to standard camera keys used throughout the app
    _EXTRINSICS_ALIAS: dict[str, str] = {
        "calib_lidar_camera_front":  "cam-front",
        "calib_lidar_camera_left":   "cam-left",
        "calib_lidar_camera_rear":   "cam-rear",
        "calib_lidar_camera_right":  "cam-right",
        "calib_lidar_cam_front":     "cam-front",
        "calib_lidar_cam_left":      "cam-left",
        "calib_lidar_cam_rear":      "cam-rear",
        "calib_lidar_cam_right":     "cam-right",
    }
    _INTRINSICS_ALIAS: dict[str, str] = {
        "calib_camera_front_intrinsic": "cam-front",
        "calib_camera_left_intrinsic":  "cam-left",
        "calib_camera_rear_intrinsic":  "cam-rear",
        "calib_camera_right_intrinsic": "cam-right",
        "calib_cam_front_intrinsic":    "cam-front",
        "calib_cam_left_intrinsic":     "cam-left",
        "calib_cam_rear_intrinsic":     "cam-rear",
        "calib_cam_right_intrinsic":    "cam-right",
    }

    bundle = CalibrationBundle()
    for txt_file in info_calib_dir.glob("*.txt"):
        lines = txt_file.read_text(encoding="utf-8").strip().splitlines()
        name = txt_file.stem
        if not lines:
            continue
        # K-Radar radar-lidar offset CSV: header + data row
        if lines[0].startswith("frame difference"):
            try:
                vals = lines[1].split(",")
                dx, dy = float(vals[1]), float(vals[2])
                mat = np.eye(4, dtype=float)
                mat[0, 3] = dx
                mat[1, 3] = dy
                bundle.extrinsics[name] = mat
            except (IndexError, ValueError) as exc:
                logger.debug("Skipping calib file %s: %s", txt_file, exc)
            continue
        try:
            mat = np.loadtxt(lines, dtype=float)
            if mat.size == 16:
                key = _EXTRINSICS_ALIAS.get(name, name)
                bundle.extrinsics[key] = mat.reshape(4, 4)
                # Also store under original name for backward compat
                if key != name:
                    bundle.extrinsics[name] = mat.reshape(4, 4)
            elif mat.size == 9:
                vals = mat.flatten()
                key = _INTRINSICS_ALIAS.get(name, name)
                intr = CameraIntrinsics(fx=vals[0], fy=vals[4], cx=vals[2], cy=vals[5])
                bundle.intrinsics[key] = intr
                if key != name:
                    bundle.intrinsics[name] = intr
        except Exception:
            logger.debug("Skipping calib file %s", txt_file)
    return bundle


# ── Calibration override utilities (shared across adapters) ─────────────────

_OVERRIDE_FILENAMES = [
    "profiles/lh_calib_overrides.json",
    "lh_calib_overrides.json",
]


def rpy_to_rot3(rx: float, ry: float, rz: float) -> "np.ndarray":
    """Build a 3×3 ZYX rotation matrix from roll/pitch/yaw deltas (radians)."""
    cx, sx = np.cos(rx), np.sin(rx)
    cy, sy = np.cos(ry), np.sin(ry)
    cz, sz = np.cos(rz), np.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=float)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=float)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=float)
    return Rz @ Ry @ Rx


def apply_delta_to_extrinsic(T: "np.ndarray",
                              delta_xyz: "list[float]",
                              delta_rpy: "list[float]") -> "np.ndarray":
    """Return T_new = T_delta @ T, where T_delta encodes xyz/rpy corrections.

    The delta is expressed in the same coordinate frame as T,
    so it is applied on the LEFT side of the existing extrinsic matrix.
    """
    dx, dy, dz = delta_xyz
    dr, dp, dy_ = delta_rpy
    dR = rpy_to_rot3(dr, dp, dy_)
    T_delta = np.eye(4, dtype=float)
    T_delta[:3, :3] = dR
    T_delta[:3, 3] = [dx, dy, dz]
    return T_delta @ T


def save_calib_override(seq_id: str, cam_name: str,
                        delta_xyz: "list[float]", delta_rpy: "list[float]",
                        root: "Path | None" = None) -> None:
    """Persist a calibration delta override to the JSON file.

    Existing overrides for other cams/seqs are preserved.  Passing
    ``delta_xyz=[0,0,0], delta_rpy=[0,0,0]`` removes the entry.
    """
    import json as _json

    override_path: Path | None = None
    candidates: list[Path] = []
    if root is not None:
        for fn in _OVERRIDE_FILENAMES:
            candidates.append(root / fn)
    for fn in _OVERRIDE_FILENAMES:
        candidates.append(Path(fn))

    for p in candidates:
        if p.exists():
            override_path = p
            break
    if override_path is None:
        override_path = candidates[0]
        override_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if override_path.exists():
            data = _json.loads(override_path.read_text(encoding="utf-8"))
        else:
            data = {"__version__": 1, "overrides": {}}

        overrides = data.setdefault("overrides", {})
        seq_block = overrides.setdefault(str(seq_id), {})

        is_zero = (all(abs(v) < 1e-9 for v in delta_xyz) and
                   all(abs(v) < 1e-9 for v in delta_rpy))
        if is_zero:
            seq_block.pop(cam_name, None)
            if not seq_block:
                overrides.pop(str(seq_id), None)
        else:
            seq_block[cam_name] = {
                "delta_xyz": [round(v, 6) for v in delta_xyz],
                "delta_rpy": [round(v, 8) for v in delta_rpy],
            }

        override_path.write_text(_json.dumps(data, indent=2, ensure_ascii=False),
                                  encoding="utf-8")
        logger.info("Saved calib override: seq=%s cam=%s", seq_id, cam_name)
    except Exception as exc:
        logger.error("Failed to save calib override: %s", exc)
