import numpy as np

from src.io.bin_detection_map import _local_to_wgs84


def test_nwu_detection_coordinates_follow_protocol_axes():
    world = _local_to_wgs84(
        np.array([[100.0, 50.0, 10.0]]),
        ref_lat=30.0,
        ref_lon=120.0,
        ref_alt=200.0,
        ref_heading_deg=90.0,
        coordinate_mode="nwu",
    )

    assert world[0, 0] > 30.0
    assert world[0, 1] < 120.0
    assert world[0, 2] == 210.0


def test_enu_detection_coordinates_preserve_altitude_and_direction():
    world = _local_to_wgs84(
        np.array([[100.0, 200.0, 30.0]]),
        ref_lat=32.0,
        ref_lon=118.0,
        ref_alt=50.0,
        ref_heading_deg=90.0,
        coordinate_mode="enu",
    )

    assert world[0, 0] > 32.0
    assert world[0, 1] > 118.0
    assert world[0, 2] == 80.0


def test_body_detection_coordinates_rotate_with_heading():
    world = _local_to_wgs84(
        np.array([[0.0, 100.0, 0.0]]),
        ref_lat=32.0,
        ref_lon=118.0,
        ref_alt=50.0,
        ref_heading_deg=90.0,
        coordinate_mode="body",
    )

    assert abs(world[0, 0] - 32.0) < 1e-8
    assert world[0, 1] > 118.0
