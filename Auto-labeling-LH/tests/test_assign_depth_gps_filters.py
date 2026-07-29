import numpy as np

from tools.assign_depth_gps import assign_depth_gps_ray


def _shape():
    return [{
        "label": "building",
        "points": [[800.0, 400.0], [1120.0, 800.0]],
    }]


def test_rejects_points_below_zero_absolute_height():
    targets = np.array([
        [32.005, 118.0, -1.0, 100.0],
        [32.010, 118.0, -20.0, 110.0],
    ])

    result = assign_depth_gps_ray(
        _shape(),
        1920,
        1200,
        32.0,
        118.0,
        50.0,
        0.0,
        0.0,
        targets,
    )

    assert result == []


def test_rejects_points_inside_range_but_outside_vertical_fov():
    targets = np.array([
        [32.010, 118.0, 500.0, 100.0],
        [32.012, 118.0, 550.0, 100.0],
    ])

    result = assign_depth_gps_ray(
        _shape(),
        1920,
        1200,
        32.0,
        118.0,
        50.0,
        0.0,
        0.0,
        targets,
    )

    assert result == []
