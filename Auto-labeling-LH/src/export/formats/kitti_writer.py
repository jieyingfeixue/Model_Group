"""KITTI label format writer."""

from __future__ import annotations

from pathlib import Path

from src.core.types import Label3D


def write_kitti(labels: list[Label3D], path: Path) -> None:
    """Write labels in KITTI format."""
    lines = []
    for b in labels:
        h, w, l = b.dimensions[2], b.dimensions[1], b.dimensions[0]
        x, y, z = b.center
        ry = b.rotation
        # KITTI: type truncated occluded alpha bbox(4) dimensions(3) location(3) rotation_y
        lines.append(
            f"{b.class_name} 0.00 0 0.00 "
            f"0.00 0.00 0.00 0.00 "
            f"{h:.4f} {w:.4f} {l:.4f} "
            f"{x:.4f} {y:.4f} {z:.4f} {ry:.4f}"
        )
    path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
