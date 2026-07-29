#!/usr/bin/env python3
"""Read LabelMe boxes and their exported depth attributes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Iterable


def read_depth_annotation(path: str | Path) -> dict[str, Any]:
    """Return the original LabelMe document with depth attributes intact."""
    annotation_path = Path(path)
    return json.loads(annotation_path.read_text(encoding="utf-8"))


def iter_depth_boxes(path: str | Path) -> Iterable[dict[str, Any]]:
    """Yield normalized rectangle/polygon records from one LabelMe JSON."""
    annotation_path = Path(path)
    document = read_depth_annotation(annotation_path)
    for index, shape in enumerate(document.get("shapes", [])):
        points = shape.get("points", [])
        if len(points) < 2:
            continue
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        attributes = shape.get("attributes", {})
        depth = attributes.get("depth_m")
        yield {
            "annotation_path": str(annotation_path),
            "shape_index": index,
            "label": shape.get("label", ""),
            "bbox_xyxy": [min(xs), min(ys), max(xs), max(ys)],
            "depth_m": float(depth) if isinstance(depth, (int, float)) else None,
            "depth_method": attributes.get("depth_method"),
            "depth_confidence": attributes.get("depth_confidence"),
            "depth_support_points": attributes.get("depth_support_points"),
            "depth_target_id": attributes.get("depth_target_id"),
        }


def read_depth_tree(root: str | Path) -> list[dict[str, Any]]:
    """Read all depth-augmented LabelMe JSON files below a directory."""
    root_path = Path(root)
    return [
        box
        for annotation_path in sorted(root_path.rglob("*.json"))
        if annotation_path.name != "depth_export_summary.json"
        for box in iter_depth_boxes(annotation_path)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="读取带深度的 LabelMe 标注。")
    parser.add_argument("path", type=Path, help="单个 JSON 或标注根目录")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    rows = (
        list(iter_depth_boxes(args.path))
        if args.path.is_file()
        else read_depth_tree(args.path)
    )
    print(json.dumps(rows[: args.limit], ensure_ascii=False, indent=2))
    print(f"boxes={len(rows)} numeric={sum(row['depth_m'] is not None for row in rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
