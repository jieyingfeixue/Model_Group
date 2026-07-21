"""坐标换算单元测试 — 不依赖数据库 / ONNX。"""

from app.eval_engine.coords import (
    enrich_detection_box,
    norm_xywh_to_pixel_xyxy,
    pixel_xyxy_to_norm_xywh,
    project_boxes_for_api,
)


def test_roundtrip_norm_pixel():
    w, h = 200, 100
    nx, ny, nw, nh = pixel_xyxy_to_norm_xywh(20, 10, 60, 50, w, h)
    assert abs(nx - 0.1) < 1e-6
    assert abs(ny - 0.1) < 1e-6
    assert abs(nw - 0.2) < 1e-6
    assert abs(nh - 0.4) < 1e-6
    x1, y1, x2, y2 = norm_xywh_to_pixel_xyxy(nx, ny, nw, nh, w, h)
    assert abs(x1 - 20) < 1e-4
    assert abs(y1 - 10) < 1e-4
    assert abs(x2 - 60) < 1e-4
    assert abs(y2 - 50) < 1e-4


def test_enrich_and_project():
    box = enrich_detection_box(
        category_id=1,
        confidence=0.9,
        x1=10,
        y1=20,
        x2=110,
        y2=220,
        image_width=1000,
        image_height=1000,
    )
    assert "xywh_norm" in box and "xyxy_pixel" in box
    assert box["x"] == box["xywh_norm"][0]

    only_norm = project_boxes_for_api([box], "norm")[0]
    assert "xyxy_pixel" not in only_norm
    assert "x" in only_norm

    only_pixel = project_boxes_for_api([box], "pixel")[0]
    assert "xyxy_pixel" in only_pixel
    assert "x" not in only_pixel
