import numpy as np

from src.fusion.relative_depth_order import (
    reject_metric_order_conflicts,
    relative_tiers,
    score_boxes,
)


def test_scores_inverse_depth_and_assigns_near_middle_far():
    depth = np.zeros((100, 300), dtype=np.float32)
    depth[:, :100] = 1.0
    depth[:, 100:200] = 3.0
    depth[:, 200:] = 6.0
    boxes = [
        {"bbox_xyxy": [0, 0, 100, 100]},
        {"bbox_xyxy": [100, 0, 200, 100]},
        {"bbox_xyxy": [200, 0, 300, 100]},
    ]

    scores = score_boxes(depth, boxes)
    tiers = relative_tiers(scores)

    assert scores[0] < scores[1] < scores[2]
    assert tiers == ["far", "middle", "near"]


def test_radar_depths_are_removed_when_they_invert_relative_order():
    boxes = [
        {
            "depth_m": 3000.0,
            "relative_depth_tier": "near",
            "method": "capture_radar_map",
        },
        {
            "depth_m": 1000.0,
            "relative_depth_tier": "far",
            "method": "capture_radar_map",
        },
    ]

    result = reject_metric_order_conflicts(boxes)

    assert [box["depth_m"] for box in result] == [None, None]
    assert all(
        box["method"] == "relative_order_conflict_rejected" for box in result
    )


def test_map_anchor_is_kept_when_radar_depth_conflicts():
    boxes = [
        {
            "depth_m": 1500.0,
            "relative_depth_tier": "near",
            "method": "gps_db_temporal",
            "target_id": "tower-near",
        },
        {
            "depth_m": 900.0,
            "relative_depth_tier": "far",
            "method": "capture_radar_map",
        },
    ]

    result = reject_metric_order_conflicts(boxes)

    assert result[0]["depth_m"] == 1500.0
    assert result[1]["depth_m"] is None
