import numpy as np

from src.fusion.bin_detection_projection import (
    KIND_DENSE,
    KIND_ISOLATED,
    KIND_POWERLINE,
    filter_body_points_by_camera_frustum,
    match_world_cloud_to_detection_samples,
    sample_bin_detection_map,
    world_samples_to_body,
)


def test_sample_bin_detection_map_densifies_all_detection_types():
    detection_map = {
        "powerline_segments": np.array(
            [[30.0, 120.0, 10.0, 30.001, 120.0, 20.0, 0, 0, 0]]
        ),
        "isolated": np.array([[30.002, 120.0, 5.0, 0, 0]]),
        "dense_vertices": np.array(
            [
                [30.003, 120.0, 0.0, 1, 2, 0],
                [30.003, 120.001, 0.0, 1, 2, 0],
                [30.004, 120.001, 0.0, 1, 2, 0],
            ]
        ),
    }

    samples = sample_bin_detection_map(detection_map, line_spacing_m=25.0)

    assert len(samples) > 10
    assert set(samples[:, 4]) == {KIND_DENSE, KIND_ISOLATED, KIND_POWERLINE}
    assert np.all(np.isfinite(samples))


def test_world_samples_to_body_filters_distance_and_view():
    # With heading offset disabled and heading 0: east is right, north is forward.
    samples = np.array(
        [
            [30.010, 120.000, 20.0, 35.0, KIND_POWERLINE],
            [30.010, 120.100, 20.0, 25.0, KIND_ISOLATED],
            [30.001, 120.000, 20.0, 15.0, KIND_DENSE],
        ]
    )

    body, source = world_samples_to_body(
        samples,
        gps_lat=30.0,
        gps_lon=120.0,
        gps_alt=10.0,
        gps_heading_deg=0.0,
        heading_offset_deg=0.0,
        min_distance_m=400.0,
        max_distance_m=4000.0,
        half_fov_deg=12.0,
    )

    assert body.shape == (1, 4)
    assert source.shape == (1, 5)
    assert abs(float(body[0, 0])) < 1.0
    assert body[0, 1] > 1000.0
    assert body[0, 2] == 10.0


def test_world_samples_to_body_caps_dense_projection():
    samples = np.tile(
        np.array([[30.010, 120.0, 20.0, 35.0, KIND_POWERLINE]]),
        (100, 1),
    )
    body, source = world_samples_to_body(
        samples,
        gps_lat=30.0,
        gps_lon=120.0,
        gps_alt=0.0,
        gps_heading_deg=0.0,
        heading_offset_deg=0.0,
        max_points=12,
    )
    assert body.shape == (12, 4)
    assert source.shape == (12, 5)


def test_projection_cap_preserves_sparse_non_powerline_targets():
    north_step = 0.00001
    powerlines = np.array(
        [
            [30.010 + i * north_step, 120.0, 20.0, 35.0, KIND_POWERLINE]
            for i in range(100)
        ]
    )
    rare = np.array(
        [
            [30.011, 120.0, 20.0, 25.0, KIND_ISOLATED],
            [30.012, 120.0, 20.0, 15.0, KIND_DENSE],
        ]
    )
    _, source = world_samples_to_body(
        np.concatenate([powerlines, rare]),
        gps_lat=30.0,
        gps_lon=120.0,
        gps_alt=0.0,
        gps_heading_deg=0.0,
        heading_offset_deg=0.0,
        max_points=12,
    )
    assert KIND_ISOLATED in source[:, 4]
    assert KIND_DENSE in source[:, 4]


def test_camera_frustum_rejects_points_above_and_outside_image():
    body = np.array(
        [
            [0.0, 1000.0, 0.0, 1.0],
            [0.0, 1000.0, 1000.0, 1.0],
            [1000.0, 1000.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    source = np.column_stack([body[:, :3], np.ones((3, 2))])
    transform = np.array(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, -1.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ]
    )

    kept, kept_source = filter_body_points_by_camera_frustum(
        body,
        source,
        body_to_camera=transform,
        fx=1000.0,
        fy=1000.0,
        cx=960.0,
        cy=600.0,
        image_width=1920,
        image_height=1200,
    )

    assert kept.shape == (1, 4)
    assert kept_source.shape == (1, 5)
    assert np.allclose(kept[0, :3], [0.0, 1000.0, 0.0])


def test_cloud_matching_uses_horizontal_position_not_unreliable_height():
    cloud = np.array(
        [
            [30.0, 120.0, 10.0, 30.0],
            [30.0, 120.01, 10.0, 30.0],
        ]
    )
    targets = np.array([[30.0, 120.0001, 1000.0, 35.0, KIND_POWERLINE]])

    mask = match_world_cloud_to_detection_samples(
        cloud, targets, max_horizontal_distance_m=30.0
    )

    assert mask.tolist() == [True, False]
