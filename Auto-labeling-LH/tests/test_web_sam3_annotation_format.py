import json

import numpy as np

from web_server.routes import browse


def _detection():
    return {
        "x1": 400.0,
        "y1": 300.0,
        "x2": 600.0,
        "y2": 500.0,
        "class_id": "power_transmission_tower",
        "class_name": "Power tower",
        "label_zh": "高压线塔",
        "prompt": "high-voltage electricity transmission tower",
        "score": 0.8123456,
        "image_width": 1000,
        "image_height": 800,
    }


def test_sam3_labelme_document_preserves_pixels_and_adds_center_coordinates():
    document = browse._build_sam3_labelme_document(
        detections=[_detection()],
        camera="037",
        image_file="camera_037_t000012.345.jpg",
        image_width=1000,
        image_height=800,
        seg_path="4_29/capture/part/segment_001",
        ir_file="camera_ir_t000012.300.jpg",
    )

    shape = document["shapes"][0]
    assert shape["label"] == "Power tower"
    assert shape["points"] == [[400.0, 300.0], [600.0, 500.0]]
    assert shape["attributes"]["label_id"] == "power_transmission_tower"
    assert shape["attributes"]["bbox_centered_xyxy"] == [
        -100.0, -100.0, 100.0, 100.0,
    ]
    assert shape["attributes"]["box_center_centered_xy"] == [0.0, 0.0]
    assert shape["attributes"]["depth_m"] is None
    assert shape["attributes"]["relative_depth"] is None
    assert shape["attributes"]["relative_depth_is_metric"] is False
    assert document["depthModel"]["name"] == "DA3-BASE"
    assert document["depthModel"]["isMetric"] is False
    assert document["coordinateSystem"]["bbox_centered_xyxy"] == (
        "image_center_x_right_y_down"
    )


def test_sam3_label_json_is_grouped_by_ir_without_camera_directories(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        browse, "LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT", tmp_path
    )
    document = browse._build_sam3_labelme_document(
        detections=[_detection()],
        camera="038",
        image_file="camera_038_t000012.346.jpg",
        image_width=1000,
        image_height=800,
        seg_path="4_29/capture/part/segment_001",
        ir_file="camera_ir_t000012.300.jpg",
    )

    output = browse._save_sam3_label_document(
        seg_path="4_29/capture/part/segment_001",
        ir_file="camera_ir_t000012.300.jpg",
        camera="038",
        image_file="camera_038_t000012.346.jpg",
        document=document,
    )

    assert output.relative_to(tmp_path).as_posix() == (
        "4_29/capture/part/segment_001/"
        "camera_ir_t000012.300/000012.346_038.json"
    )
    saved = json.loads(output.read_text(encoding="utf-8"))
    assert saved["camera"] == "038"
    assert saved["group"]["ir_timestamp"] == "000012.300"
    assert saved["group"]["visible_timestamp"] == "000012.346"


def test_sam3_taxonomy_contains_all_requested_fine_grained_classes():
    assert {spec["class_id"] for spec in browse.SAM3_CLASS_SPECS} == {
        "power_transmission_tower",
        "wind_turbine",
        "building",
        "chimney",
        "bridge",
        "television_tower",
        "signal_tower",
    }


def test_da3_checkpoint_allows_only_known_tied_layernorm_aliases():
    assert browse.DA3_TIED_AUX_STATE_ALIASES == {
        "model.head.scratch.output_conv2_aux.1.2.weight",
        "model.head.scratch.output_conv2_aux.1.2.bias",
        "model.head.scratch.output_conv2_aux.2.2.weight",
        "model.head.scratch.output_conv2_aux.2.2.bias",
        "model.head.scratch.output_conv2_aux.3.2.weight",
        "model.head.scratch.output_conv2_aux.3.2.bias",
    }


def test_human_edits_are_preserved_in_labelme_attributes():
    detection = _detection()
    detection.update({
        "class_id": "bridge",
        "class_name": "Bridge",
        "label_zh": "大桥",
        "description": "人工复核后改类",
        "annotation_source": "sam3_human_edited",
        "human_modified": True,
        "depth_m": 318.25,
        "depth_method": "manual",
        "depth_confidence": 0.73,
        "depth_support_points": 4,
    })
    document = browse._build_sam3_labelme_document(
        detections=[detection],
        camera="037",
        image_file="camera_037_t000012.345.jpg",
        image_width=1000,
        image_height=800,
        seg_path="4_29/capture/part/segment_001",
        ir_file="camera_ir_t000012.300.jpg",
    )

    shape = document["shapes"][0]
    assert shape["label"] == "Bridge"
    assert shape["description"] == "人工复核后改类"
    assert shape["attributes"]["label_id"] == "bridge"
    assert shape["attributes"]["human_modified"] is True
    assert shape["attributes"]["annotation_source"] == "sam3_human_edited"
    assert shape["attributes"]["depth_m"] == 318.25
    assert shape["attributes"]["depth_method"] == "manual"
    assert shape["attributes"]["depth_confidence"] == 0.73
    assert shape["attributes"]["depth_support_points"] == 4


def test_da3_relative_depth_is_aggregated_inside_sam3_box():
    detection = _detection()
    detection.update({"x1": 2.0, "y1": 2.0, "x2": 8.0, "y2": 8.0})
    depth = np.arange(1, 101, dtype=np.float32).reshape(10, 10)
    confidence = np.full((10, 10), 2.0, dtype=np.float32)

    browse._attach_da3_box_depths(
        {"037": [detection]},
        {"037": depth},
        {"037": confidence},
    )

    assert detection["relative_depth"] > 0
    assert 0 <= detection["relative_depth_normalized"] <= 1
    assert detection["relative_depth_is_metric"] is False
    assert detection["relative_depth_method"] == "da3_inner_box_confident_median"
    assert detection["relative_depth_support_pixels"] > 0

    document = browse._build_sam3_labelme_document(
        detections=[detection],
        camera="037",
        image_file="camera_037_t000012.345.jpg",
        image_width=10,
        image_height=10,
        seg_path="4_29/capture/part/segment_001",
        ir_file="camera_ir_t000012.300.jpg",
    )
    attributes = document["shapes"][0]["attributes"]
    assert attributes["relative_depth"] == round(detection["relative_depth"], 6)
    assert attributes["relative_depth_normalized"] == round(
        detection["relative_depth_normalized"], 6
    )
    assert attributes["relative_depth_is_metric"] is False
