"""Export writer — dispatch to format-specific writers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.core.types import Label3D

logger = logging.getLogger(__name__)


class ExportWriter:
    """Export annotation results in various formats."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.default_format = cfg.get("default_format", "json")
        self.output_root = Path(cfg.get("output_root", "./outputs"))

    def export(
        self,
        labels: list[Label3D],
        seq_id: str,
        frame_id: str,
        fmt: str | None = None,
    ) -> Path:
        """Export labels for a single frame."""
        fmt = fmt or self.default_format
        out_dir = self.output_root / seq_id
        out_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "kitti":
            from .formats.kitti_writer import write_kitti
            path = out_dir / f"{frame_id}.txt"
            write_kitti(labels, path)
        elif fmt == "json":
            from src.io.label_io import save_labels
            path = out_dir / f"{frame_id}.json"
            save_labels(labels, path, "json")
        else:
            raise ValueError(f"Unknown export format: {fmt}")

        logger.info("Exported %d labels to %s", len(labels), path)
        return path

    def export_sequence(
        self,
        frames: dict[str, list[Label3D]],
        seq_id: str,
        fmt: str | None = None,
    ) -> Path:
        """Export all frames in a sequence."""
        for frame_id, labels in frames.items():
            self.export(labels, seq_id, frame_id, fmt)
        out_dir = self.output_root / seq_id
        logger.info("Exported sequence %s (%d frames)", seq_id, len(frames))
        return out_dir
