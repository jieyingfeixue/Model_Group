"""2D object detector — multiple backends.

Priority:
  1. yolo_onnx        — YOLOv8 / YOLO-World via cv2.dnn (local .onnx file, no torch)
  2. grounding_dino   — Grounding DINO (requires groundingdino + torch)
  3. stub             — returns [] (LiDAR DBSCAN fallback will be used instead)

Usage in config (models.detector):
  name: yolo_onnx
  weights_path: "C:/models/yolov8n.onnx"   # path to ONNX model file
  classes_path: ""                          # optional .txt with class names (one per line)
  conf_threshold: 0.35
  nms_threshold: 0.45
  input_size: 640
  default_prompt: "car . truck . bus . pedestrian . cyclist"
"""

from __future__ import annotations

import logging
import os
from typing import Any

import numpy as np

from src.core.types import Detection2D

logger = logging.getLogger(__name__)

# COCO class names that map to our annotation categories
_COCO_VEHICLE_IDS = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
_COCO_PERSON_ID = 0  # "person" → pedestrian
_COCO_CYCLIST_IDS = {1: "cyclist"}  # bicycle

# Full COCO 80-class list (index = class id)
_COCO80 = [
    "person","bicycle","car","motorcycle","airplane","bus","train","truck","boat",
    "traffic light","fire hydrant","stop sign","parking meter","bench","bird","cat",
    "dog","horse","sheep","cow","elephant","bear","zebra","giraffe","backpack",
    "umbrella","handbag","tie","suitcase","frisbee","skis","snowboard","sports ball",
    "kite","baseball bat","baseball glove","skateboard","surfboard","tennis racket",
    "bottle","wine glass","cup","fork","knife","spoon","bowl","banana","apple",
    "sandwich","orange","broccoli","carrot","hot dog","pizza","donut","cake","chair",
    "couch","potted plant","bed","dining table","toilet","tv","laptop","mouse",
    "remote","keyboard","cell phone","microwave","oven","toaster","sink",
    "refrigerator","book","clock","vase","scissors","teddy bear","hair drier",
    "toothbrush",
]

# Map COCO class name → annotation class name
_COCO_CLASS_MAP: dict[str, str] = {
    "person": "pedestrian",
    "bicycle": "cyclist",
    "car": "car",
    "motorcycle": "cyclist",
    "bus": "truck",
    "truck": "truck",
}


def _filter_ego_vehicle(
    detections: "list[Detection2D]",
    image_shape: "tuple[int, int]",
    bottom_frac: float = 0.88,
    min_width_frac: float = 0.30,
) -> "list[Detection2D]":
    """Remove detections that are likely the ego vehicle (camera car).

    A bounding box is considered ego vehicle when:
      - Its bottom edge reaches into the bottom ``bottom_frac`` fraction of the
        image (i.e. y2 >= h * bottom_frac), AND
      - Its width covers at least ``min_width_frac`` of the image width.

    These large bottom-center boxes almost always correspond to the hood / roof
    of the vehicle carrying the cameras.
    """
    h, w = image_shape
    result = []
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        box_w = x2 - x1
        if y2 >= h * bottom_frac and box_w >= w * min_width_frac:
            logger.debug("Filtered ego-vehicle box: %s", det.bbox)
            continue
        result.append(det)
    return result


def _nms_numpy(boxes_xywh: list, scores: list, iou_threshold: float) -> list[int]:
    """Pure-numpy NMS. boxes_xywh: list of [x,y,w,h]. Returns kept indices."""
    if not boxes_xywh:
        return []
    boxes = np.array(boxes_xywh, dtype=np.float32)
    sc = np.array(scores, dtype=np.float32)
    x1, y1 = boxes[:, 0], boxes[:, 1]
    x2, y2 = x1 + boxes[:, 2], y1 + boxes[:, 3]
    areas = (x2 - x1).clip(0) * (y2 - y1).clip(0)
    order = sc.argsort()[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        ix1 = np.maximum(x1[i], x1[order[1:]])
        iy1 = np.maximum(y1[i], y1[order[1:]])
        ix2 = np.minimum(x2[i], x2[order[1:]])
        iy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (ix2 - ix1).clip(0) * (iy2 - iy1).clip(0)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[1:][iou <= iou_threshold]
    return keep


class Detector2D:
    """Multi-backend 2D open-vocabulary detector."""

    def __init__(self, config: dict[str, Any]):
        self.name = config.get("name", "yolo_onnx")
        self.conf_threshold = config.get("conf_threshold", config.get("box_threshold", 0.35))
        self.nms_threshold = config.get("nms_threshold", 0.45)
        self.input_size = config.get("input_size", 640)
        self.prompt = config.get("default_prompt", "car . truck . bus . pedestrian . cyclist")
        self._config = config
        self._model = None   # cv2.dnn.Net or groundingdino model or "stub"
        self._class_names: list[str] = []
        self._backend: str = ""

    # ------------------------------------------------------------------ #

    def _ensure_model(self) -> None:
        if self._model is not None:
            return
        if self.name == "yolo_pt":
            self._model = self._load_yolo_pt()
        elif self.name == "yolo_onnx":
            self._model = self._load_yolo_onnx()
        elif self.name == "grounding_dino":
            self._model = self._load_grounding_dino()
        else:
            logger.warning("Detector '%s' not recognised, using stub", self.name)
            self._model = "stub"

    # ------------------------------------------------------------------ #
    #  Loaders                                                             #
    # ------------------------------------------------------------------ #

    def _load_yolo_onnx(self):
        """Load a YOLOv8 (or YOLO-World) ONNX model via onnxruntime."""
        weights = self._config.get("weights_path", "")
        if not weights or not os.path.exists(weights):
            logger.warning(
                "YOLOv8 ONNX model not found at '%s'. "
                "Place a yolov8n.onnx (or yolo-world-s.onnx) file there to enable 2D detection. "
                "Using LiDAR-only fallback.", weights,
            )
            return "stub"
        try:
            import onnxruntime as ort
            sess = ort.InferenceSession(weights, providers=["CPUExecutionProvider"])
            # Load class names
            classes_path = self._config.get("classes_path", "")
            if classes_path and os.path.exists(classes_path):
                with open(classes_path) as f:
                    self._class_names = [l.strip() for l in f if l.strip()]
            else:
                self._class_names = _COCO80
            self._backend = "yolo_onnx"
            logger.info("YOLOv8 ONNX model loaded via onnxruntime: %s", weights)
            return sess
        except Exception as exc:
            logger.warning("Failed to load YOLO ONNX model: %s — using stub", exc)
            return "stub"

    def _load_yolo_pt(self):
        """Load a YOLOv8 .pt model via ultralytics."""
        weights = self._config.get("weights_path", "")
        if not weights or not os.path.exists(weights):
            logger.warning("YOLOv8 .pt model not found at '%s', trying stub", weights)
            return "stub"
        try:
            from ultralytics import YOLO
            model = YOLO(weights)
            self._backend = "yolo_pt"
            logger.info("YOLOv8 PT model loaded: %s", weights)
            return model
        except Exception as exc:
            logger.warning("Failed to load YOLO .pt model: %s — using stub", exc)
            return "stub"

    def _load_grounding_dino(self):
        """Load Grounding DINO model (requires groundingdino + torch)."""
        try:
            from groundingdino.util.inference import load_model
            model = load_model(
                self._config.get("config_path", ""),
                self._config.get("weights_path", ""),
            )
            self._backend = "grounding_dino"
            return model
        except ImportError:
            logger.warning("groundingdino not installed — trying yolo_onnx fallback")
            self.name = "yolo_onnx"
            return self._load_yolo_onnx()
        except Exception as exc:
            logger.warning("Grounding DINO load failed: %s — using stub", exc)
            return "stub"

    # ------------------------------------------------------------------ #
    #  Inference                                                           #
    # ------------------------------------------------------------------ #

    def detect(self, image: np.ndarray, prompt: str | None = None) -> list[Detection2D]:
        """Run detection on an RGB image → list[Detection2D]."""
        self._ensure_model()
        if self._model == "stub":
            return []

        if self._backend == "yolo_pt":
            raw = self._detect_yolo_pt(image)
        elif self._backend == "yolo_onnx":
            raw = self._detect_yolo_onnx(image)
        elif self._backend == "grounding_dino":
            raw = self._detect_grounding_dino(image, prompt)
        else:
            return []

        return _filter_ego_vehicle(raw, image.shape[:2])

    # ── YOLOv8 PT (ultralytics) ───────────────────────────────────────────

    def _detect_yolo_pt(self, image: np.ndarray) -> list[Detection2D]:
        h, w = image.shape[:2]
        try:
            results = self._model.predict(
                image, conf=self.conf_threshold, iou=self.nms_threshold,
                verbose=False, device="cpu"
            )
        except Exception as exc:
            logger.error("YOLOv8 PT inference failed: %s", exc)
            return []
        detections = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cid = int(box.cls[0])
                conf = float(box.conf[0])
                raw_name = (self._model.names[cid]
                            if hasattr(self._model, "names") else "unknown")
                ann_name = _COCO_CLASS_MAP.get(raw_name, raw_name)
                if ann_name not in {"car", "truck", "pedestrian", "cyclist"}:
                    continue
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                x1, y1 = max(0.0, x1), max(0.0, y1)
                x2, y2 = min(float(w), x2), min(float(h), y2)
                if x2 <= x1 or y2 <= y1:
                    continue
                detections.append(Detection2D(
                    bbox=(x1, y1, x2, y2),
                    class_name=ann_name,
                    score=conf,
                ))
        return detections

    # ── YOLOv8 ONNX ──────────────────────────────────────────────────────

    def _detect_yolo_onnx(self, image: np.ndarray) -> list[Detection2D]:
        import onnxruntime as ort  # noqa: F401 (already loaded)
        h, w = image.shape[:2]
        sz = self.input_size

        # Letterbox resize (numpy only, no cv2)
        scale = min(sz / h, sz / w)
        new_h, new_w = int(h * scale), int(w * scale)
        # PIL resize
        from PIL import Image as _PIL
        pil = _PIL.fromarray(image[..., ::-1].astype(np.uint8))  # BGR→RGB
        pil = pil.resize((new_w, new_h), _PIL.BILINEAR)
        padded = np.full((sz, sz, 3), 114, dtype=np.uint8)
        top, left = (sz - new_h) // 2, (sz - new_w) // 2
        padded[top:top + new_h, left:left + new_w] = np.array(pil)

        # Normalize + NCHW float32
        blob = padded.astype(np.float32) / 255.0
        blob = blob.transpose(2, 0, 1)[np.newaxis]  # (1,3,sz,sz)

        input_name = self._model.get_inputs()[0].name
        try:
            outputs = self._model.run(None, {input_name: blob})[0]  # (1,84,8400)
        except Exception as exc:
            logger.error("YOLOv8 onnxruntime inference failed: %s", exc)
            return []

        # YOLOv8 output: (1, 84, 8400) → transpose → (8400, 84)
        if outputs.ndim == 3:
            preds = outputs[0].T
        else:
            preds = outputs.T

        boxes_xywh, scores, class_ids = [], [], []
        for row in preds:
            cx, cy, bw, bh = row[:4]
            cls_scores = row[4:]
            cid = int(np.argmax(cls_scores))
            conf = float(cls_scores[cid])
            if conf < self.conf_threshold:
                continue
            x1 = ((cx - bw / 2) - left) / scale
            y1 = ((cy - bh / 2) - top) / scale
            x2 = ((cx + bw / 2) - left) / scale
            y2 = ((cy + bh / 2) - top) / scale
            boxes_xywh.append([x1, y1, x2 - x1, y2 - y1])
            scores.append(conf)
            class_ids.append(cid)

        if not boxes_xywh:
            return []

        # Pure-numpy NMS
        indices = _nms_numpy(boxes_xywh, scores, self.nms_threshold)

        result = []
        for idx in indices:
            x, y, bw, bh = boxes_xywh[idx]
            cid = class_ids[idx]
            raw_name = (self._class_names[cid]
                        if cid < len(self._class_names) else "unknown")
            ann_name = _COCO_CLASS_MAP.get(raw_name, raw_name)
            # Filter: only vehicle/pedestrian/cyclist relevant classes
            if ann_name not in {"car", "truck", "pedestrian", "cyclist", "bus"}:
                continue
            # Clamp to image
            x1 = max(0.0, float(x))
            y1 = max(0.0, float(y))
            x2 = min(float(w), float(x + bw))
            y2 = min(float(h), float(y + bh))
            if x2 <= x1 or y2 <= y1:
                continue
            result.append(Detection2D(
                bbox=(x1, y1, x2, y2),
                class_name=ann_name,
                score=float(scores[idx]),
            ))
        return result

    # ── Grounding DINO ───────────────────────────────────────────────────

    def _detect_grounding_dino(self, image: np.ndarray,
                                prompt: str | None = None) -> list[Detection2D]:
        text = prompt or self.prompt
        h, w = image.shape[:2]
        try:
            import torch
            from groundingdino.util.inference import predict
            from PIL import Image
            import torchvision.transforms as T
            transform = T.Compose([
                T.ToTensor(),
                T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ])
            pil_img = Image.fromarray(image)
            img_tensor = transform(pil_img)
            boxes, logits, phrases = predict(
                model=self._model,
                image=img_tensor,
                caption=text,
                box_threshold=self.conf_threshold,
                text_threshold=self.conf_threshold,
            )
            result = []
            for box, score, phrase in zip(boxes, logits, phrases):
                cx, cy, bw, bh = box.tolist()
                x1 = (cx - bw / 2) * w
                y1 = (cy - bh / 2) * h
                x2 = (cx + bw / 2) * w
                y2 = (cy + bh / 2) * h
                result.append(Detection2D(
                    bbox=(x1, y1, x2, y2),
                    class_name=phrase.strip(),
                    score=float(score),
                ))
            return result
        except Exception as exc:
            logger.error("Grounding DINO detection failed: %s", exc)
            return []
