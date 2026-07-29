import numpy as np

from src.fusion.target_image_registration import (
    apply_pixel_registration,
    estimate_pixel_registration,
)


def test_registration_recovers_translation_and_small_scale():
    targets = np.array([[300.0, 500.0], [800.0, 520.0], [1300.0, 480.0]])
    center = np.array([960.0, 600.0])
    expected = (targets - center) * np.array([1.08, 1.0]) + center
    expected += np.array([85.0, -42.0])
    boxes = np.column_stack([expected - 35.0, expected + 35.0])

    registration = estimate_pixel_registration(boxes, targets, (1920, 1200))
    transformed = apply_pixel_registration(targets, registration)

    assert registration.match_count == 3
    assert np.max(np.linalg.norm(transformed - expected, axis=1)) < 2.0


def test_single_anchor_only_estimates_translation():
    targets = np.array([[500.0, 400.0]])
    boxes = np.array([[580.0, 450.0, 660.0, 530.0]])

    registration = estimate_pixel_registration(boxes, targets, (1920, 1200))

    assert registration.match_count == 1
    assert registration.scale_x == 1.0
    assert registration.scale_y == 1.0
    assert np.allclose(
        apply_pixel_registration(targets, registration),
        [[620.0, 490.0]],
    )
