"""Label I/O — read and write annotation files."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np

from src.core.types import Label3D

logger = logging.getLogger(__name__)


def load_labels(path: Path, fmt: str = "json") -> list[Label3D]:
    """Load labels from a file in the specified format."""
    if fmt == "kitti":
        return _load_kitti_labels(path)
    elif fmt == "json":
        return _load_json_labels(path)
    raise ValueError(f"Unknown label format: {fmt}")


def save_labels(labels: list[Label3D], path: Path, fmt: str = "json") -> None:
    """Save labels in the specified format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        _save_json_labels(labels, path)
    elif fmt == "kitti":
        _save_kitti_labels(labels, path)
    else:
        raise ValueError(f"Unknown label format: {fmt}")


# ---- KITTI format ----------------------------------------------------------

def _load_kitti_labels(path: Path) -> list[Label3D]:
    if not path.exists():
        return []
    labels: list[Label3D] = []
    for i, line in enumerate(path.read_text(encoding="utf-8").strip().splitlines()):
        parts = line.split()
        if len(parts) < 15:
            continue
        labels.append(Label3D(
            object_id=f"gt_{i:03d}",
            class_name=parts[0],
            dimensions=np.array([float(parts[10]), float(parts[9]), float(parts[8])]),  # l,w,h
            center=np.array([float(parts[11]), float(parts[12]), float(parts[13])]),
            rotation=float(parts[14]),
            source="gt",
        ))
    return labels


def _save_kitti_labels(labels: list[Label3D], path: Path) -> None:
    lines = []
    for b in labels:
        h, w, l = b.dimensions[2], b.dimensions[1], b.dimensions[0]
        x, y, z = b.center
        ry = b.rotation
        lines.append(
            f"{b.class_name} 0 0 0 0 0 0 0 {h:.4f} {w:.4f} {l:.4f} {x:.4f} {y:.4f} {z:.4f} {ry:.4f}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---- JSON format -----------------------------------------------------------

def _load_json_labels(path: Path) -> list[Label3D]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = []
    for d in data:
        labels.append(Label3D(
            object_id=d.get("object_id", ""),
            class_name=d.get("class_name", ""),
            center=np.array(d["center"]),
            dimensions=np.array(d["dimensions"]),
            rotation=d.get("rotation", 0.0),
            score=d.get("score", 1.0),
            source=d.get("source", ""),
            track_id=d.get("track_id", -1),
        ))
    return labels


def _save_json_labels(labels: list[Label3D], path: Path) -> None:
    data = []
    for b in labels:
        data.append({
            "object_id": b.object_id,
            "class_name": b.class_name,
            "center": b.center.tolist(),
            "dimensions": b.dimensions.tolist(),
            "rotation": b.rotation,
            "score": b.score,
            "source": b.source,
            "track_id": b.track_id,
        })
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
