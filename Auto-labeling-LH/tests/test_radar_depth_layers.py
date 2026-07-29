import numpy as np

from src.fusion.radar_depth_layers import cluster_depth_layers, select_depth_layer


def test_filters_all_points_below_400m():
    result = select_depth_layer(
        np.array([80.0, 150.0, 399.9]),
        np.array([100.0, 95.0, 90.0]),
    )
    assert result is None


def test_clusters_near_middle_far_and_ignores_near_clutter():
    distances = np.array([100, 150, 390, 810, 820, 835, 1510, 1530, 2490, 2520])
    strengths = np.array([120, 115, 110, 70, 72, 71, 68, 69, 65, 66])
    layers = cluster_depth_layers(distances, strengths)

    assert len(layers) == 3
    assert [round(x["depth_m"]) for x in layers] == [820, 1520, 2505]


def test_previous_frame_prefers_consistent_layer():
    distances = np.array([805, 815, 825, 1480, 1500, 1520, 1540])
    strengths = np.array([72, 73, 71, 68, 69, 67, 70])
    selected = select_depth_layer(
        distances,
        strengths,
        previous_depth_m=820.0,
    )

    assert selected is not None
    assert selected["depth_m"] < 900.0
