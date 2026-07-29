"""Image segmentation wrapper.

Backends (priority order, controlled by config['name']):
  1. ``sam2``        — SAM 2.1 Hiera-L via HuggingFace transformers
                       (``facebook/sam2-hiera-large``).  GPU recommended.
                       This is the FULL (highest accuracy) backend.
  2. ``mobile_sam``  — MobileSAM (TinyViT encoder, ~40 MB) via the
                       ``mobile_sam`` package.  ~10-20× faster than SAM2
                       on CPU; quality is comparable for box-prompt mode.
                       This is the FAST backend.
  3. ``sam_v1``      — Legacy SAM ViT-H via segment_anything package.
  4. ``stub``        — Returns None (caller falls back to bbox-only path).

When ``name`` is "fast" we try mobile_sam → sam_v1 → stub.
When ``name`` is "full" or "auto" we try sam2 → mobile_sam → sam_v1 → stub.

Config keys (models.segmentor):
  name: sam2 | sam_v1 | auto | stub
  weights_path:    local checkpoint (sam2: optional .pt; sam_v1: required .pth)
  hf_model_id:     huggingface id (default: "facebook/sam2-hiera-large")
  device:          cuda | cpu (default: cuda when available)
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class Segmentor:
    """SAM2 / SAM-v1 segmentor with bbox-prompt support."""

    def __init__(self, config: dict[str, Any]):
        self.enabled = config.get("enabled", False)
        self.name = (config.get("name") or "auto").lower()
        self.hf_model_id = config.get("hf_model_id", "facebook/sam2-hiera-large")
        self.weights_path = config.get("weights_path", "")
        self.device = config.get("device", "")
        self._model: Any = None
        self._processor: Any = None
        self._backend: str = ""

    # ------------------------------------------------------------------ #
    @property
    def is_loaded(self) -> bool:
        return self._model is not None and self._model != "stub"

    @property
    def backend(self) -> str:
        return self._backend

    # ------------------------------------------------------------------ #
    def _ensure_model(self) -> None:
        if self._model is not None or not self.enabled:
            return
        # Resolve fallback chain by user preference.
        n = self.name
        if n == "fast":
            order = ["mobile_sam", "sam_v1"]
        elif n == "full":
            order = ["sam2", "mobile_sam", "sam_v1"]
        elif n in ("sam2", "mobile_sam", "sam_v1"):
            order = [n]
        else:  # auto / unknown
            order = ["sam2", "mobile_sam", "sam_v1"]
        for backend in order:
            if backend == "sam2" and self._try_load_sam2():
                return
            if backend == "mobile_sam" and self._try_load_mobile_sam():
                return
            if backend == "sam_v1" and self._try_load_sam_v1():
                return
        logger.warning("No segmentor backend available — segment() will return None")
        self._model = "stub"

    # ------------------------------------------------------------------ #
    def _resolve_device(self) -> str:
        if self.device:
            return self.device
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _try_load_sam2(self) -> bool:
        try:
            from transformers import Sam2Model, Sam2Processor   # type: ignore
        except ImportError:
            logger.info("SAM2 (transformers) not available")
            return False
        device = self._resolve_device()
        try:
            self._processor = Sam2Processor.from_pretrained(self.hf_model_id)
            self._model = Sam2Model.from_pretrained(self.hf_model_id).to(device).eval()
            self._backend = "sam2"
            logger.info("Loaded SAM2 (%s) on %s", self.hf_model_id, device)
            return True
        except Exception as exc:
            logger.warning("SAM2 load failed: %s", exc)
            self._processor = None
            self._model = None
            return False

    def _try_load_mobile_sam(self) -> bool:
        """Load MobileSAM (TinyViT encoder, ~40 MB).  Same predict API as SAM v1."""
        try:
            from mobile_sam import sam_model_registry as _reg, SamPredictor as _Pred  # type: ignore
        except ImportError:
            logger.info("mobile_sam not installed")
            return False
        # Resolve weights path: explicit weights_path > auto-discover under ./models
        import os
        weights = self.weights_path
        if not weights or not os.path.isfile(weights):
            for cand in ("models/mobile_sam.pt", "./models/mobile_sam.pt",
                         os.path.expanduser("~/models/mobile_sam.pt")):
                if os.path.isfile(cand):
                    weights = cand
                    break
        if not weights or not os.path.isfile(weights):
            logger.warning(
                "MobileSAM weights not found.  Download mobile_sam.pt from "
                "https://github.com/ChaoningZhang/MobileSAM/raw/master/weights/mobile_sam.pt "
                "and place at models/mobile_sam.pt (or set models.segmentor.weights_path)")
            return False
        device = self._resolve_device()
        try:
            sam = _reg["vit_t"](checkpoint=weights)
            sam.to(device=device).eval()
            self._model = _Pred(sam)
            self._backend = "mobile_sam"
            logger.info("Loaded MobileSAM (vit_t) on %s from %s", device, weights)
            return True
        except Exception as exc:
            logger.warning("MobileSAM load failed: %s", exc)
            self._model = None
            return False

    def _try_load_sam_v1(self) -> bool:
        try:
            from segment_anything import sam_model_registry, SamPredictor   # type: ignore
        except ImportError:
            logger.info("segment_anything not installed")
            return False
        weights = self.weights_path
        try:
            if weights:
                sam = sam_model_registry["vit_h"](checkpoint=weights)
            else:
                sam = sam_model_registry["vit_h"]()
            device = self._resolve_device()
            sam.to(device)
            self._model = SamPredictor(sam)
            self._backend = "sam_v1"
            logger.info("Loaded legacy SAM v1 ViT-H on %s", device)
            return True
        except Exception as exc:
            logger.warning("SAM v1 load failed: %s", exc)
            self._model = None
            return False

    # ------------------------------------------------------------------ #
    def segment(
        self,
        image: np.ndarray,
        bbox: tuple[float, float, float, float] | None = None,
        points: np.ndarray | None = None,
        labels: np.ndarray | None = None,
    ) -> np.ndarray | None:
        """Generate a binary mask given a bbox prompt (and optional points).

        Parameters
        ----------
        image:  HxWx3 RGB uint8.
        bbox:   (x1, y1, x2, y2) in pixel coords.
        points: optional Nx2 prompt points in pixel coords.
        labels: optional length-N int (1=foreground, 0=background).

        Returns HxW bool mask, or None when no backend is available.
        """
        if not self.enabled:
            return None
        self._ensure_model()
        if not self.is_loaded:
            return None
        try:
            if self._backend == "sam2":
                return self._segment_sam2(image, bbox, points, labels)
            if self._backend in ("mobile_sam", "sam_v1"):
                # Both share the SamPredictor.predict() API
                return self._segment_sam_v1(image, bbox, points, labels)
        except Exception as exc:
            logger.error("Segmentation failed (%s): %s", self._backend, exc)
        return None

    def segment_auto(self, image: np.ndarray, max_masks: int = 100) -> list[dict] | None:
        """Generate ALL instance masks for an image (used by B2 pipeline)."""
        if not self.enabled:
            return None
        self._ensure_model()
        if not self.is_loaded:
            return None
        try:
            if self._backend == "sam2":
                return self._segment_auto_sam2(image, max_masks)
            if self._backend == "sam_v1":
                return self._segment_auto_sam_v1(image, max_masks)
        except Exception as exc:
            logger.error("Auto-segment failed (%s): %s", self._backend, exc)
        return None

    # ── SAM2 (HuggingFace transformers) ───────────────────────────────
    def _segment_sam2(self, image, bbox, points, labels):
        import torch
        prompts: dict = {}
        if bbox is not None:
            prompts["input_boxes"] = [[list(bbox)]]
        if points is not None:
            prompts["input_points"] = [[points.tolist()]]
            prompts["input_labels"] = [[(labels.tolist() if labels is not None
                                         else [1] * len(points))]]
        inputs = self._processor(images=image, **prompts, return_tensors="pt")
        device = next(self._model.parameters()).device
        inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}
        with torch.no_grad():
            outputs = self._model(**inputs, multimask_output=False)
        masks = self._processor.image_processor.post_process_masks(
            outputs.pred_masks.cpu(), inputs["original_sizes"].cpu(),
            inputs["reshaped_input_sizes"].cpu(),
        )
        return masks[0][0, 0].numpy().astype(bool)

    def _segment_auto_sam2(self, image, max_masks):
        # Best-effort: prompt SAM2 with a grid of points and dedup.
        return self._auto_grid_prompt(image, max_masks)

    def _auto_grid_prompt(self, image: np.ndarray, max_masks: int) -> list[dict]:
        h, w = image.shape[:2]
        n = max(4, int(np.sqrt(max_masks)))
        ys = np.linspace(h * 0.1, h * 0.9, n).astype(int)
        xs = np.linspace(w * 0.1, w * 0.9, n).astype(int)
        results: list[dict] = []
        seen: list[tuple[int, float, float]] = []
        for y in ys:
            for x in xs:
                pts = np.array([[x, y]], dtype=np.float32)
                m = self.segment(image, bbox=None, points=pts,
                                 labels=np.array([1], dtype=np.int64))
                if m is None:
                    continue
                area = int(m.sum())
                if area < 200 or area > 0.5 * h * w:
                    continue
                ys_idx, xs_idx = np.where(m)
                cx, cy = float(xs_idx.mean()), float(ys_idx.mean())
                if any(abs(area - a) < 50 and (px - cx) ** 2 + (py - cy) ** 2 < 100
                       for a, px, py in seen):
                    continue
                seen.append((area, cx, cy))
                results.append({
                    "mask": m,
                    "bbox": (int(xs_idx.min()), int(ys_idx.min()),
                             int(xs_idx.max()), int(ys_idx.max())),
                    "score": 1.0,
                    "area": area,
                })
                if len(results) >= max_masks:
                    return results
        return results

    # ── SAM v1 (legacy) ───────────────────────────────────────────────
    def _segment_sam_v1(self, image, bbox, points, labels):
        self._model.set_image(image)
        kwargs = {"multimask_output": False}
        if bbox is not None:
            kwargs["box"] = np.array([[bbox[0], bbox[1], bbox[2], bbox[3]]])
        if points is not None:
            kwargs["point_coords"] = points
            kwargs["point_labels"] = (labels if labels is not None
                                      else np.ones(len(points), dtype=np.int64))
        masks, _, _ = self._model.predict(**kwargs)
        return masks[0].astype(bool)

    def _segment_auto_sam_v1(self, image, max_masks):
        try:
            from segment_anything import SamAutomaticMaskGenerator   # type: ignore
            gen = SamAutomaticMaskGenerator(self._model.model)
            anns = gen.generate(image)
            anns = sorted(anns, key=lambda a: a["area"], reverse=True)[:max_masks]
            return [
                {
                    "mask": a["segmentation"].astype(bool),
                    "bbox": tuple(a["bbox"]),  # SAM v1: xywh
                    "score": float(a.get("predicted_iou", 1.0)),
                    "area": int(a["area"]),
                }
                for a in anns
            ]
        except Exception as exc:
            logger.warning("SAM v1 auto-generate failed: %s", exc)
            return []
