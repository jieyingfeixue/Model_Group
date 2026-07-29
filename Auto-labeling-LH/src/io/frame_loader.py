"""Generic frame loader that delegates to dataset-specific adapters."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.core.types import FrameData
from .sensor_profile import SensorProfile
# Import adapters directly so PyInstaller can detect them statically
from src.io.adapters import lh_adapter as _lh_adapter

logger = logging.getLogger(__name__)

# Map dataset name → adapter module (static imports, no importlib)
_ADAPTER_MAP: dict[str, Any] = {
    "lh": _lh_adapter,
    "LH": _lh_adapter,
    "LH-多模态数据库": _lh_adapter,
}


class FrameLoader:
    """Load a single frame's sensors through the sensor profile."""

    def __init__(self, profile: SensorProfile, dataset_root: Path):
        self.profile = profile
        self.dataset_root = dataset_root
        self._adapter = _get_adapter(profile)
        self._prepare_frame_callback = None
        self._prepare_thumbnail_callback = None

    def list_sequences(self) -> list[str]:
        """Return sorted sequence IDs found on disk."""
        return self._adapter.list_sequences(self.dataset_root, self.profile)

    def list_frames(self, seq_id: str) -> list[str]:
        """Return sorted frame IDs within a sequence."""
        return self._adapter.list_frames(self.dataset_root, self.profile, seq_id)

    def load_frame(self, seq_id: str, frame_id: str) -> FrameData:
        """Load all sensor data for one frame."""
        self.prepare_frame(seq_id, frame_id)
        return self._adapter.load_frame(self.dataset_root, self.profile, seq_id, frame_id)

    def set_prepare_frame_callback(self, callback) -> None:
        self._prepare_frame_callback = callback

    def set_prepare_thumbnail_callback(self, callback) -> None:
        self._prepare_thumbnail_callback = callback

    def prepare_frame(self, seq_id: str, frame_id: str) -> None:
        if self._prepare_frame_callback is not None:
            self._prepare_frame_callback(seq_id, frame_id)

    def prepare_thumbnail(self, seq_id: str, frame_id: str) -> None:
        callback = self._prepare_thumbnail_callback or self._prepare_frame_callback
        if callback is not None:
            callback(seq_id, frame_id)


def _get_adapter(profile: SensorProfile) -> Any:
    key = profile.dataset or profile.name
    adapter = _ADAPTER_MAP.get(key)
    if adapter is None:
        raise ValueError(f"No adapter registered for dataset '{key}'")
    return adapter
