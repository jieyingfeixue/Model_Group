"""Visualize one LH mmWave MAT point cloud on the existing map renderer.

Usage:
    python tools/visualize_mat_on_map.py path/to/mmwave_*.mat

If no MAT path is supplied, a file picker is shown.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _build_pose_track(layers: list[dict]) -> np.ndarray | None:
    rows: list[np.ndarray] = []
    for layer in layers:
        pose = np.asarray(layer.get("pose"), dtype=np.float64)
        if pose.ndim != 2 or pose.shape[1] < 7 or pose.shape[0] == 0:
            continue
        rows.append(pose[:, [2, 3, 6]])  # lat, lon, relative time
    if not rows:
        return None
    track = np.concatenate(rows, axis=0)
    valid = np.isfinite(track[:, 0]) & np.isfinite(track[:, 1])
    track = track[valid]
    if len(track) < 2:
        return None
    if np.ptp(track[:, 2]) > 0:
        order = np.argsort(track[:, 2])
        track = track[order]
    if len(track) > 2000:
        step = max(1, len(track) // 2000)
        track = track[::step]
    return track


def _pose_summary(layers: list[dict]) -> dict[str, float | None]:
    poses: list[np.ndarray] = []
    for layer in layers:
        pose = np.asarray(layer.get("pose"), dtype=np.float64)
        if pose.ndim == 2 and pose.shape[1] >= 7 and pose.shape[0] > 0:
            poses.append(pose)
    if not poses:
        return {
            "heading": None,
            "alt": None,
            "frame_time": None,
        }
    pose_all = np.concatenate(poses, axis=0)
    return {
        "heading": float(np.nanmedian(pose_all[:, 5])),
        "alt": float(np.nanmedian(pose_all[:, 4])),
        "frame_time": (
            float(np.nanmedian(pose_all[:, 6]))
            if np.nanmax(pose_all[:, 6]) > np.nanmin(pose_all[:, 6])
            else None
        ),
    }


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = (
        math.cos(lat1_rad) * math.sin(lat2_rad)
        - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    )
    return math.degrees(math.atan2(y, x)) % 360.0


def _point_cloud_mid_heading(
    points: np.ndarray,
    center_lat: float,
    center_lon: float,
) -> tuple[float, float, float]:
    """Direction from the aircraft center to the rendered cloud bbox center."""
    lats = np.asarray(points[:, 0], dtype=np.float64)
    lons = np.asarray(points[:, 1], dtype=np.float64)
    mid_lat = float((np.nanmin(lats) + np.nanmax(lats)) * 0.5)
    mid_lon = float((np.nanmin(lons) + np.nanmax(lons)) * 0.5)
    return _bearing_deg(center_lat, center_lon, mid_lat, mid_lon), mid_lat, mid_lon


def _load_mat_points(mat_path: Path):
    from src.io.adapters.lh_adapter import (
        _load_mmwave_enu_pts,
        _load_mmwave_layers,
    )

    layers = _load_mmwave_layers(mat_path)
    points, center_lat, center_lon = _load_mmwave_enu_pts(mat_path)
    track = _build_pose_track(layers)
    pose = _pose_summary(layers)
    return points, float(center_lat), float(center_lon), track, pose


class MatMapWindow:
    def __init__(
        self,
        mat_path: Path,
        *,
        camera_heading: float | None = None,
    ) -> None:
        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

        from src.ui.panels.map_panel import MapView

        class MatOnlyMapView(MapView):
            def _draw_fov_cone(self, *args, **kwargs) -> None:
                return None

        self.window = QMainWindow()
        self.window.setWindowTitle(f"MAT 点云地图可视化 - {mat_path.name}")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.info = QLabel("正在读取 MAT...")
        self.info.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.info.setStyleSheet(
            "background:#181825;color:#cdd6f4;padding:6px 10px;"
            "font-size:12px;border-bottom:1px solid #313244;"
        )
        layout.addWidget(self.info)

        self.map_view = MatOnlyMapView()
        self.map_view.status_changed.connect(self._on_status)
        self.map_view.geo_changed.connect(self._on_geo)
        layout.addWidget(self.map_view, 1)

        self.window.setCentralWidget(central)
        self.window.resize(1280, 820)

        points, center_lat, center_lon, track, pose = _load_mat_points(mat_path)
        if not np.isfinite(center_lat) or not np.isfinite(center_lon):
            raise ValueError("MAT 中没有有效 GPS 经纬度，无法映射到地图")
        if len(points) == 0:
            raise ValueError("MAT 中没有可显示的 CFAR 点云")

        mid_hdg, mid_lat, mid_lon = _point_cloud_mid_heading(
            points, center_lat, center_lon
        )
        gps_hdg = (
            float(camera_heading) % 360.0
            if camera_heading is not None
            else mid_hdg
        )
        self._base_info = (
            f"MAT: {mat_path} | 点数: {len(points):,} | "
            f"中心: {center_lat:.7f}, {center_lon:.7f} | "
            f"点云范围中心: {mid_lat:.7f}, {mid_lon:.7f} | "
            f"箭头朝向: {gps_hdg:.1f}°"
        )
        self.info.setText(self._base_info)

        self.map_view.set_frame(
            gps_lat=center_lat,
            gps_lon=center_lon,
            gps_hdg=gps_hdg,
            camera_hdg=gps_hdg,
            gps_track=track,
            frame_time=pose.get("frame_time"),
            gps_alt=pose.get("alt"),
            radar_enu_pts=points,
            radar_ref_lat=center_lat,
            radar_ref_lon=center_lon,
        )

    def _on_status(self, text: str) -> None:
        self.info.setText(f"{self._base_info} | {text}")

    def _on_geo(self, text: str) -> None:
        if text:
            self.window.setWindowTitle(f"MAT 点云地图可视化 - {text}")

    def show(self) -> None:
        self.window.show()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="把单个 LH 毫米波雷达 MAT 点云可视化到地图上"
    )
    parser.add_argument(
        "mat",
        nargs="?",
        type=Path,
        help="输入 .mat 文件；不提供时弹出文件选择框",
    )
    parser.add_argument(
        "--camera-heading",
        type=float,
        default=None,
        help="可选：手动覆盖箭头方向角，北为 0° 顺时针；默认指向点云范围中心",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(sys.argv[1:] if argv is None else argv))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox

    app = QApplication(sys.argv[:1])
    mat_path = args.mat
    if mat_path is None:
        selected, _ = QFileDialog.getOpenFileName(
            None,
            "选择毫米波雷达 MAT",
            str(PROJECT_ROOT),
            "MAT files (*.mat);;All files (*.*)",
        )
        if not selected:
            return 0
        mat_path = Path(selected)

    mat_path = mat_path.expanduser().resolve()
    if not mat_path.exists():
        QMessageBox.critical(None, "MAT 点云地图", f"文件不存在:\n{mat_path}")
        return 2
    if mat_path.suffix.lower() != ".mat":
        QMessageBox.critical(None, "MAT 点云地图", f"不是 .mat 文件:\n{mat_path}")
        return 2

    try:
        win = MatMapWindow(mat_path, camera_heading=args.camera_heading)
    except Exception as exc:
        logging.exception("failed to visualize MAT")
        QMessageBox.critical(None, "MAT 点云地图", str(exc))
        return 1
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
