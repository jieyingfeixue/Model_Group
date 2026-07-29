from tools.assign_depth_from_db import (
    TemporalMatchState,
    _match_boxes_to_targets,
)


def test_first_map_anchor_can_initialize_large_camera_yaw_offset():
    boxes = [
        {
            "label": "Power tower",
            "bbox_xyxy": [152.9, 0.0, 392.9, 1190.0],
            "img_w": 1920,
            "img_h": 1200,
        },
        {
            "label": "Power tower",
            "bbox_xyxy": [485.7, 92.9, 721.4, 981.4],
            "img_w": 1920,
            "img_h": 1200,
        },
    ]
    targets = [
        {
            "id": "osm_tower_1661526675",
            "label": "Power tower",
            "lat": 31.9629809,
            "lon": 118.6160427,
            "confidence": 1.0,
        },
        {
            "id": "osm_tower_1661526673",
            "label": "Power tower",
            "lat": 31.9531636,
            "lon": 118.6344373,
            "confidence": 1.0,
            "depth_offset_m": 28.6,
        },
    ]

    result = _match_boxes_to_targets(
        boxes,
        targets,
        v_lat=31.9696558,
        v_lon=118.6019764,
        v_hdg=210.9,
        fov_deg=9.8,
        az_thresh=4.0,
        state=TemporalMatchState(),
    )

    assert [round(row["depth_m"]) for row in result] == [1520, 3598]
    assert [row["target_id"] for row in result] == [
        "osm_tower_1661526675",
        "osm_tower_1661526673",
    ]
    assert all(abs(row["camera_yaw_offset_deg"]) > 20.0 for row in result)


def test_one_map_target_is_not_reused_for_two_boxes():
    boxes = [
        {
            "label": "Power tower",
            "bbox_xyxy": [150.0, 0.0, 390.0, 1190.0],
            "img_w": 1920,
            "img_h": 1200,
        },
        {
            "label": "Power tower",
            "bbox_xyxy": [485.0, 90.0, 720.0, 980.0],
            "img_w": 1920,
            "img_h": 1200,
        },
    ]
    targets = [{
        "id": "tower_a",
        "label": "Power tower",
        "lat": 31.9629809,
        "lon": 118.6160427,
        "confidence": 1.0,
    }]

    result = _match_boxes_to_targets(
        boxes, targets, 31.9696558, 118.6019764, 210.9,
        fov_deg=9.8, az_thresh=4.0, state=TemporalMatchState(),
    )

    assert sum(row["depth_m"] is not None for row in result) == 1


def test_tower_identity_ignores_swapped_temporal_pixel_hint():
    boxes = [
        {
            "label": "Power tower",
            "bbox_xyxy": [150.0, 0.0, 390.0, 1190.0],
            "img_w": 1920,
            "img_h": 1200,
        },
        {
            "label": "Power tower",
            "bbox_xyxy": [485.0, 90.0, 720.0, 980.0],
            "img_w": 1920,
            "img_h": 1200,
        },
    ]
    targets = [
        {
            "id": "near",
            "label": "Power tower",
            "lat": 31.9629809,
            "lon": 118.6160427,
            "confidence": 1.0,
        },
        {
            "id": "far",
            "label": "Power tower",
            "lat": 31.9531636,
            "lon": 118.6344373,
            "confidence": 1.0,
            "depth_offset_m": 28.6,
        },
    ]
    state = TemporalMatchState(
        yaw_offset_deg=-88.0,
        previous=[
            {"label": "tower", "cx": 0.14, "target_id": "far"},
            {"label": "tower", "cx": 0.31, "target_id": "near"},
        ],
    )

    result = _match_boxes_to_targets(
        boxes, targets, 31.9696558, 118.6019764, 210.9,
        fov_deg=9.8, az_thresh=4.0, state=state,
    )

    assert [row["target_id"] for row in result] == ["near", "far"]


def test_single_remaining_tower_keeps_previous_target_identity():
    box = {
        "label": "Power tower",
        "bbox_xyxy": [430.0, 0.0, 730.0, 1180.0],
        "img_w": 1920,
        "img_h": 1200,
    }
    targets = [
        {
            "id": "near",
            "label": "Power tower",
            "lat": 31.9629809,
            "lon": 118.6160427,
            "confidence": 1.0,
        },
        {
            "id": "far",
            "label": "Power tower",
            "lat": 31.9531636,
            "lon": 118.6344373,
            "confidence": 1.0,
        },
    ]
    state = TemporalMatchState(
        yaw_offset_deg=-88.0,
        previous=[
            {"label": "tower", "cx": 0.29, "target_id": "near"},
            {"label": "tower", "cx": 0.83, "target_id": "far"},
        ],
    )

    result = _match_boxes_to_targets(
        [box], targets, 31.9696558, 118.6019764, 210.9,
        fov_deg=9.8, az_thresh=4.0, state=state,
    )

    assert result[0]["target_id"] == "near"


def test_101502_single_large_tower_does_not_jump_back_to_far_target():
    box = {
        "label": "Power tower",
        "bbox_xyxy": [929.0, 7.0, 1257.0, 1161.0],
        "img_w": 1920,
        "img_h": 1200,
        "relative_depth_score": 3.372,
    }
    targets = [
        {
            "id": "near",
            "label": "Power tower",
            "lat": 31.9629809,
            "lon": 118.6160427,
            "confidence": 1.0,
        },
        {
            "id": "far",
            "label": "Power tower",
            "lat": 31.9531636,
            "lon": 118.6344373,
            "confidence": 1.0,
            "depth_offset_m": 28.6,
        },
    ]
    state = TemporalMatchState(
        yaw_offset_deg=-83.0,
        previous=[
            {"label": "tower", "cx": 1082 / 1920, "target_id": "near"},
            {"label": "tower", "cx": 417 / 1920, "target_id": "far"},
        ],
    )

    result = _match_boxes_to_targets(
        [box], targets, 31.969574, 118.602076, 210.9,
        fov_deg=9.8, az_thresh=4.0, state=state,
    )

    assert result[0]["target_id"] == "near"
