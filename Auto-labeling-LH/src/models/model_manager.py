"""Model manager — lazy loading + GPU memory management."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ModelManager:
    """Lazily loads and caches model instances."""

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._detector = None
        self._depth = None
        self._segmentor = None

    def get_detector(self):
        """Return the 2D object detector."""
        if self._detector is None:
            from .detector_2d import Detector2D
            self._detector = Detector2D(self.config.get("models", {}).get("detector", {}))
        return self._detector

    def get_depth_estimator(self):
        """Return the monocular depth estimator."""
        if self._depth is None:
            from .depth_estimator import DepthEstimator
            self._depth = DepthEstimator(self.config.get("models", {}).get("depth", {}))
        return self._depth

    def get_segmentor(self):
        """Return the image segmentor (SAM2)."""
        if self._segmentor is None:
            from .segmentor import Segmentor
            self._segmentor = Segmentor(self.config.get("models", {}).get("segmentor", {}))
        return self._segmentor

    def release_all(self) -> None:
        """Free GPU memory by releasing all models."""
        self._detector = None
        self._depth = None
        self._segmentor = None
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
