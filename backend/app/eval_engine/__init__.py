"""Phase3 评测 / 推理支撑包：坐标约定、后续 MetricsEngine 等。"""

from app.eval_engine.coords import (
    enrich_detection_box,
    norm_xywh_to_pixel_xyxy,
    pixel_xyxy_to_norm_xywh,
    project_boxes_for_api,
)

__all__ = [
    "enrich_detection_box",
    "norm_xywh_to_pixel_xyxy",
    "pixel_xyxy_to_norm_xywh",
    "project_boxes_for_api",
]
