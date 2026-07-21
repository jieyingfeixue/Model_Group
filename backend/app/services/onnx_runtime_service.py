"""ONNX Runtime 推理服务 — Phase3 Step1：加载 + 单图前向。

约定：
- 评测/推理运行时统一 ONNX Runtime；.pt 转换下一步再做。
- 内部框：原图像素 xyxy；输出经 coords.enrich_detection_box 带上 norm/pixel。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image

from app.eval_engine.coords import enrich_detection_box

logger = logging.getLogger(__name__)

# 进程内简单缓存：path/key → session
_SESSION_CACHE: dict[str, Any] = {}


@dataclass
class DetectedBox:
    category_id: int
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


def clear_session_cache() -> None:
    _SESSION_CACHE.clear()


def load_onnx_session(model_bytes: bytes, cache_key: str):
    """从字节加载 InferenceSession；非法/占位文件会抛 ValueError。"""
    if cache_key in _SESSION_CACHE:
        return _SESSION_CACHE[cache_key]

    if not model_bytes or len(model_bytes) < 32:
        raise ValueError("ONNX 文件过短或为空，无法加载")
    # 我们自己的假权重头
    if model_bytes.startswith(b"DEMO_ONNX") or model_bytes.startswith(b"DEMO_PYTORCH"):
        raise ValueError(
            "当前权重是联调占位文件，不是合法 ONNX。"
            "请上传真实 .onnx 模型后再推理。"
        )

    try:
        import onnxruntime as ort
    except ImportError as exc:
        raise RuntimeError(
            "未安装 onnxruntime，请在环境中 pip install onnxruntime"
        ) from exc

    try:
        session = ort.InferenceSession(
            model_bytes, providers=["CPUExecutionProvider"]
        )
    except Exception as exc:
        raise ValueError(f"ONNX 加载失败: {exc}") from exc

    _SESSION_CACHE[cache_key] = session
    return session


def _letterbox_resize(
    image: Image.Image, input_w: int, input_h: int
) -> tuple[np.ndarray, float, int, int]:
    """等比缩放 + padding 到 input，返回 NCHW float32、scale、pad_x、pad_y。"""
    im = image.convert("RGB")
    orig_w, orig_h = im.size
    scale = min(input_w / orig_w, input_h / orig_h)
    new_w = int(round(orig_w * scale))
    new_h = int(round(orig_h * scale))
    resized = im.resize((new_w, new_h), Image.BILINEAR)
    canvas = Image.new("RGB", (input_w, input_h), (114, 114, 114))
    pad_x = (input_w - new_w) // 2
    pad_y = (input_h - new_h) // 2
    canvas.paste(resized, (pad_x, pad_y))
    arr = np.asarray(canvas).astype(np.float32) / 255.0
    arr = np.transpose(arr, (2, 0, 1))[None, ...]  # 1,3,H,W
    return arr, scale, pad_x, pad_y


def _parse_yolo_like_output(
    output: np.ndarray,
    *,
    conf_thres: float,
    num_classes_hint: int | None,
) -> list[tuple[float, float, float, float, int, float]]:
    """解析常见 YOLO ONNX 输出为 (cx,cy,w,h,cls,conf)（仍在 letterbox 坐标系）。

    支持形状大致为:
    - (1, 4+nc, N)  — YOLOv8 导出常见
    - (1, N, 4+nc)
    - (N, 4+nc)
    """
    arr = np.squeeze(output)
    if arr.ndim != 2:
        raise ValueError(f"暂不支持的输出维度: {output.shape}")

    # 让第二维是 4+nc
    if arr.shape[0] < arr.shape[1] and arr.shape[0] <= 512:
        # (4+nc, N) → (N, 4+nc)
        arr = arr.T

    if arr.shape[1] < 6:
        raise ValueError(f"输出通道过少，无法解析检测框: {arr.shape}")

    boxes: list[tuple[float, float, float, float, int, float]] = []
    for row in arr:
        cx, cy, w, h = map(float, row[:4])
        scores = row[4:]
        if scores.size == 0:
            continue
        # 有的导出是 objectness + classes
        if num_classes_hint and scores.size == num_classes_hint + 1:
            obj = float(scores[0])
            cls_scores = scores[1:] * obj
        else:
            cls_scores = scores
        cls_id = int(np.argmax(cls_scores))
        conf = float(cls_scores[cls_id])
        if conf < conf_thres:
            continue
        boxes.append((cx, cy, w, h, cls_id, conf))
    return boxes


def _xywh_center_to_xyxy(
    cx: float, cy: float, w: float, h: float
) -> tuple[float, float, float, float]:
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def map_letterbox_box_to_original(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    scale: float,
    pad_x: int,
    pad_y: int,
    orig_w: int,
    orig_h: int,
) -> tuple[float, float, float, float]:
    """letterbox 坐标系框映射回原图像素 xyxy。"""
    x1 = (x1 - pad_x) / scale
    x2 = (x2 - pad_x) / scale
    y1 = (y1 - pad_y) / scale
    y2 = (y2 - pad_y) / scale
    x1 = max(0.0, min(float(orig_w), x1))
    x2 = max(0.0, min(float(orig_w), x2))
    y1 = max(0.0, min(float(orig_h), y1))
    y2 = max(0.0, min(float(orig_h), y2))
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    return x1, y1, x2, y2


def run_detection_on_image(
    session,
    image_bytes: bytes,
    *,
    input_size: tuple[int, int] = (640, 640),
    conf_thres: float = 0.25,
    num_classes: int | None = None,
) -> tuple[list[DetectedBox], int, int]:
    """对单张图片跑检测，返回 (boxes, orig_w, orig_h)。"""
    image = Image.open(BytesIO(image_bytes)).convert("RGB")
    orig_w, orig_h = image.size
    input_h, input_w = int(input_size[0]), int(input_size[1])
    # meta 里常写 [H,W]
    if input_w < 32 or input_h < 32:
        input_w, input_h = 640, 640

    tensor, scale, pad_x, pad_y = _letterbox_resize(image, input_w, input_h)
    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: tensor})
    if not outputs:
        return [], orig_w, orig_h

    raw_boxes = _parse_yolo_like_output(
        np.asarray(outputs[0]),
        conf_thres=conf_thres,
        num_classes_hint=num_classes,
    )

    detected: list[DetectedBox] = []
    for cx, cy, w, h, cls_id, conf in raw_boxes:
        x1, y1, x2, y2 = _xywh_center_to_xyxy(cx, cy, w, h)
        x1, y1, x2, y2 = map_letterbox_box_to_original(
            x1,
            y1,
            x2,
            y2,
            scale=scale,
            pad_x=pad_x,
            pad_y=pad_y,
            orig_w=orig_w,
            orig_h=orig_h,
        )
        if x2 - x1 < 1 or y2 - y1 < 1:
            continue
        detected.append(
            DetectedBox(
                category_id=cls_id + 1,  # 平台类别习惯从 1 起；后续可按 schema 映射
                confidence=conf,
                x1=x1,
                y1=y1,
                x2=x2,
                y2=y2,
            )
        )
    return detected, orig_w, orig_h


def detections_to_api_boxes(
    detected: list[DetectedBox], image_width: int, image_height: int
) -> list[dict[str, Any]]:
    return [
        enrich_detection_box(
            category_id=d.category_id,
            confidence=d.confidence,
            x1=d.x1,
            y1=d.y1,
            x2=d.x2,
            y2=d.y2,
            image_width=image_width,
            image_height=image_height,
        )
        for d in detected
    ]


def resolve_input_size(meta_info: dict[str, Any] | None) -> tuple[int, int]:
    meta = meta_info or {}
    size = meta.get("input_size") or [640, 640]
    if isinstance(size, (list, tuple)) and len(size) >= 2:
        return int(size[0]), int(size[1])
    return 640, 640
