"""检测框坐标约定（Phase3 兼容方案）。

内部 / 评测：原图像素 xyxy = (x1, y1, x2, y2)
对外默认：归一化 xywh（相对原图宽高，x/y 为左上角）
API 可选：coord=norm | pixel | both（默认 both）
"""

from __future__ import annotations

from typing import Any, Literal

CoordMode = Literal["norm", "pixel", "both"]


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def pixel_xyxy_to_norm_xywh(
    x1: float, y1: float, x2: float, y2: float, image_width: int, image_height: int
) -> tuple[float, float, float, float]:
    """像素 xyxy → 归一化 xywh（左上角 + 宽高）。"""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image_width/height must be positive")
    x1, x2 = sorted((float(x1), float(x2)))
    y1, y2 = sorted((float(y1), float(y2)))
    w = max(0.0, x2 - x1)
    h = max(0.0, y2 - y1)
    return (
        clamp(x1 / image_width, 0.0, 1.0),
        clamp(y1 / image_height, 0.0, 1.0),
        clamp(w / image_width, 0.0, 1.0),
        clamp(h / image_height, 0.0, 1.0),
    )


def norm_xywh_to_pixel_xyxy(
    x: float, y: float, w: float, h: float, image_width: int, image_height: int
) -> tuple[float, float, float, float]:
    """归一化 xywh（左上角）→ 像素 xyxy。"""
    if image_width <= 0 or image_height <= 0:
        raise ValueError("image_width/height must be positive")
    x1 = float(x) * image_width
    y1 = float(y) * image_height
    x2 = x1 + float(w) * image_width
    y2 = y1 + float(h) * image_height
    return (
        clamp(x1, 0.0, float(image_width)),
        clamp(y1, 0.0, float(image_height)),
        clamp(x2, 0.0, float(image_width)),
        clamp(y2, 0.0, float(image_height)),
    )


def enrich_detection_box(
    *,
    category_id: int,
    confidence: float,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    image_width: int,
    image_height: int,
    depth: float | None = None,
) -> dict[str, Any]:
    """由内部像素 xyxy 生成 API 友好框（同时含 norm / pixel）。"""
    nx, ny, nw, nh = pixel_xyxy_to_norm_xywh(x1, y1, x2, y2, image_width, image_height)
    box: dict[str, Any] = {
        "category_id": int(category_id),
        "confidence": float(confidence),
        # 兼容契约旧字段：归一化 xywh
        "x": nx,
        "y": ny,
        "w": nw,
        "h": nh,
        "xywh_norm": [nx, ny, nw, nh],
        "xyxy_pixel": [float(x1), float(y1), float(x2), float(y2)],
    }
    if depth is not None:
        box["depth"] = float(depth)
    return box


def project_boxes_for_api(
    boxes: list[dict[str, Any]],
    coord: CoordMode = "both",
) -> list[dict[str, Any]]:
    """按 coord 投影框字段，供 GET /infer/.../results 使用。"""
    if coord == "both":
        return boxes

    projected: list[dict[str, Any]] = []
    for raw in boxes:
        b = dict(raw)
        if coord == "norm":
            if "xywh_norm" in b and isinstance(b["xywh_norm"], (list, tuple)):
                nx, ny, nw, nh = b["xywh_norm"]
                b["x"], b["y"], b["w"], b["h"] = nx, ny, nw, nh
            b.pop("xyxy_pixel", None)
        elif coord == "pixel":
            b.pop("xywh_norm", None)
            # 旧字段在 pixel 模式下不再表示归一化，避免误用
            for k in ("x", "y", "w", "h"):
                b.pop(k, None)
        projected.append(b)
    return projected
