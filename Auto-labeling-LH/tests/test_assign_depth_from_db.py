import math

from tools.assign_depth_from_db import (
    TemporalMatchState,
    _canonical_label,
    _match_boxes_to_targets,
)


def _box(cx, label="Tall building", width=0.08):
    return {
        "label": label,
        "bbox_xyxy": [(cx - width / 2) * 1000, 100, (cx + width / 2) * 1000, 500],
        "img_w": 1000,
        "img_h": 600,
    }


def _target(target_id, rel_az, distance, label="building"):
    radius = 6_371_000.0
    angle = math.radians(rel_az)
    lat = 32.0 + math.degrees(distance * math.cos(angle) / radius)
    lon = 118.0 + math.degrees(
        distance * math.sin(angle) / (radius * math.cos(math.radians(32.0)))
    )
    return {
        "id": target_id,
        "label": label,
        "lat": lat,
        "lon": lon,
        "confidence": 1.0,
    }


def test_label_aliases_match_manual_map_targets():
    assert _canonical_label("Tall building") == "building"
    assert _canonical_label("建筑物") == "building"
    assert _canonical_label("Signal Tower") == "tower"


def test_many_boxes_can_share_three_physical_targets():
    targets = [
        _target("near", -5.0, 500.0),
        _target("middle", 0.0, 1200.0),
        _target("far", 5.0, 2500.0),
    ]
    boxes = [
        _box(0.16), _box(0.21), _box(0.27),
        _box(0.47), _box(0.52),
        _box(0.72), _box(0.78), _box(0.84),
    ]

    result = _match_boxes_to_targets(
        boxes, targets, 32.0, 118.0, 0.0, fov_deg=15.0, az_thresh=4.0
    )

    ids = [row["target_id"] for row in result]
    assert len(result) == 8
    assert set(ids) == {"near", "middle", "far"}
    assert ids.count("near") > 1
    assert ids.count("far") > 1


def test_temporal_hint_stabilizes_target_identity():
    targets = [
        _target("left", -1.0, 900.0),
        _target("right", 1.0, 1300.0),
    ]
    state = TemporalMatchState()
    first = _match_boxes_to_targets(
        [_box(0.43), _box(0.57)],
        targets,
        32.0,
        118.0,
        0.0,
        fov_deg=15.0,
        az_thresh=3.0,
        state=state,
    )
    second = _match_boxes_to_targets(
        [_box(0.45), _box(0.55)],
        targets,
        32.0,
        118.0,
        0.0,
        fov_deg=15.0,
        az_thresh=3.0,
        state=state,
    )

    assert [row["target_id"] for row in first] == ["left", "right"]
    assert [row["target_id"] for row in second] == ["left", "right"]
