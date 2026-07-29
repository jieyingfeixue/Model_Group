from pathlib import Path

import numpy as np

from src.io.adapters import lh_adapter


def test_capture_depth_map_keeps_only_cross_mat_persistent_voxels(
    tmp_path: Path, monkeypatch,
):
    capture = tmp_path / "capture"
    radar = capture / "capture_radar"
    radar.mkdir(parents=True)
    mats = [radar / "frame_001.mat", radar / "frame_002.mat"]
    for path in mats:
        path.write_bytes(b"mat")

    points_by_name = {
        "frame_001.mat": np.array([
            [32.0000000, 118.0000000, 12.0, 70.0],
            [32.0010000, 118.0010000, 18.0, 90.0],
        ], dtype=np.float32),
        "frame_002.mat": np.array([
            [32.0000010, 118.0000010, 12.5, 74.0],
        ], dtype=np.float32),
    }

    monkeypatch.setattr(
        lh_adapter,
        "_load_mmwave_enu_pts",
        lambda path: (points_by_name[path.name], 32.0, 118.0),
    )
    lh_adapter._CAPTURE_DEPTH_MAP_CACHE.clear()

    result = lh_adapter.load_capture_depth_radar_map(capture)

    assert result.shape == (1, 5)
    assert result[0, 4] == 2
    assert 71.0 < result[0, 3] < 73.0


def test_capture_all_points_preserves_each_mat_point_gps(tmp_path, monkeypatch):
    capture = tmp_path / "capture"
    radar = capture / "capture_radar"
    radar.mkdir(parents=True)
    first = radar / "frame_001.mat"
    second = radar / "frame_002.mat"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    points = {
        first.name: np.array(
            [[32.0, 118.0, 100.0, 60.0]], dtype=np.float32
        ),
        second.name: np.array(
            [[33.0, 119.0, 200.0, 70.0]], dtype=np.float32
        ),
    }
    monkeypatch.setattr(
        lh_adapter,
        "_load_mmwave_enu_pts",
        lambda path: (points[path.name], 0.0, 0.0),
    )
    lh_adapter._CAPTURE_ALL_POINTS_CACHE.clear()

    result = lh_adapter.load_capture_all_enu_pts(capture)

    assert result.tolist() == [
        [32.0, 118.0, 100.0, 60.0],
        [33.0, 119.0, 200.0, 70.0],
    ]
