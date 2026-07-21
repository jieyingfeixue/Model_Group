"""GT / PD → 统一内部检测框，再转 COCO 风格结构。

兼容标注框多种写法：
- {x,y,w,h,category_id} 归一化或像素（靠 image size 与数值范围判断）
- {x1,y1,x2,y2,category_id} / {xyxy:[...]}
- {bbox:[x,y,w,h], category_id|label|class_id}
"""

from __future__ import annotations

from typing import Any

from app.eval_engine.coords import norm_xywh_to_pixel_xyxy, pixel_xyxy_to_norm_xywh


def _category_id(raw: dict[str, Any]) -> int:
    for key in ("category_id", "class_id", "label_id", "cls"):
        if key in raw and raw[key] is not None:
            try:
                return int(raw[key])
            except (TypeError, ValueError):
                continue
    return 1


def _looks_normalized(vals: list[float]) -> bool:
    return all(0.0 <= v <= 1.5 for v in vals)


def box_dict_to_xyxy_pixel(
    raw: dict[str, Any], image_width: int, image_height: int
) -> tuple[float, float, float, float, int] | None:
    """单框 → (x1,y1,x2,y2,category_id)；无法解析返回 None。"""
    cat = _category_id(raw)

    if "xyxy_pixel" in raw and isinstance(raw["xyxy_pixel"], (list, tuple)):
        x1, y1, x2, y2 = map(float, raw["xyxy_pixel"][:4])
        return x1, y1, x2, y2, cat

    if "xyxy" in raw and isinstance(raw["xyxy"], (list, tuple)):
        x1, y1, x2, y2 = map(float, raw["xyxy"][:4])
        if _looks_normalized([x1, y1, x2, y2]):
            x1 *= image_width
            x2 *= image_width
            y1 *= image_height
            y2 *= image_height
        return x1, y1, x2, y2, cat

    if all(k in raw for k in ("x1", "y1", "x2", "y2")):
        x1, y1, x2, y2 = float(raw["x1"]), float(raw["y1"]), float(raw["x2"]), float(raw["y2"])
        if _looks_normalized([x1, y1, x2, y2]):
            x1, x2 = x1 * image_width, x2 * image_width
            y1, y2 = y1 * image_height, y2 * image_height
        return x1, y1, x2, y2, cat

    bbox = raw.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        x, y, w, h = map(float, bbox[:4])
        vals = [x, y, w, h]
        if _looks_normalized(vals):
            x1, y1, x2, y2 = norm_xywh_to_pixel_xyxy(x, y, w, h, image_width, image_height)
        else:
            x1, y1, x2, y2 = x, y, x + w, y + h
        return x1, y1, x2, y2, cat

    if all(k in raw for k in ("x", "y", "w", "h")):
        x, y, w, h = float(raw["x"]), float(raw["y"]), float(raw["w"]), float(raw["h"])
        if _looks_normalized([x, y, w, h]):
            x1, y1, x2, y2 = norm_xywh_to_pixel_xyxy(x, y, w, h, image_width, image_height)
        else:
            x1, y1, x2, y2 = x, y, x + w, y + h
        return x1, y1, x2, y2, cat

    return None


def predictions_from_infer_detection(det: dict[str, Any]) -> list[dict[str, Any]]:
    """infer results 单图 detections 项 → 列表 {category_id,confidence,x1,y1,x2,y2}。"""
    w = int(det.get("image_width") or 0)
    h = int(det.get("image_height") or 0)
    out: list[dict[str, Any]] = []
    for b in det.get("boxes") or []:
        parsed = box_dict_to_xyxy_pixel(b, w or 1, h or 1)
        if parsed is None:
            continue
        x1, y1, x2, y2, cat = parsed
        out.append(
            {
                "category_id": cat,
                "confidence": float(b.get("confidence", 0.0)),
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "image_width": w,
                "image_height": h,
            }
        )
    return out


def gt_from_annotation_bboxes(
    bboxes: list[dict[str, Any]], image_width: int, image_height: int
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for b in bboxes or []:
        parsed = box_dict_to_xyxy_pixel(b, image_width, image_height)
        if parsed is None:
            continue
        x1, y1, x2, y2, cat = parsed
        out.append(
            {
                "category_id": cat,
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "image_width": image_width,
                "image_height": image_height,
            }
        )
    return out


def to_coco_gt(
    images: list[dict[str, Any]],
    annotations: list[dict[str, Any]],
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    """组装 pycocotools 可用的 GT dict。"""
    return {
        "info": {"description": "detection_platform_gt"},
        "licenses": [],
        "images": images,
        "annotations": annotations,
        "categories": categories,
    }


def xyxy_to_coco_bbox(x1: float, y1: float, x2: float, y2: float) -> list[float]:
    return [float(x1), float(y1), float(max(0.0, x2 - x1)), float(max(0.0, y2 - y1))]


def enrich_norm_fields(box: dict[str, Any]) -> dict[str, Any]:
    """给内部框补上 xywh_norm，便于错题本展示。"""
    w = int(box.get("image_width") or 0)
    h = int(box.get("image_height") or 0)
    if w > 0 and h > 0:
        nx, ny, nw, nh = pixel_xyxy_to_norm_xywh(
            box["x1"], box["y1"], box["x2"], box["y2"], w, h
        )
        box = {**box, "xywh_norm": [nx, ny, nw, nh]}
    return box
