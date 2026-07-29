#!/usr/bin/env python3
"""Audit depth prerequisites and output coverage for every LabelMe frame."""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path


def _walk_json(root: Path) -> tuple[list[Path], list[dict]]:
    paths: list[Path] = []
    errors: list[dict] = []

    def onerror(error: OSError) -> None:
        errors.append({"path": error.filename, "error": str(error)})

    for directory, _subdirs, files in os.walk(root, onerror=onerror):
        for name in files:
            if name.lower().endswith(".json"):
                paths.append(Path(directory) / name)
    return paths, errors


def _capture_parts(path: Path, annotation_root: Path) -> tuple[str, str]:
    relative = path.relative_to(annotation_root)
    parts = relative.parts
    capture_index = next(
        (i for i, part in enumerate(parts) if part.startswith("with_cameras_capture_")),
        -1,
    )
    segment_index = next(
        (i for i, part in enumerate(parts) if part.startswith("segment_")),
        -1,
    )
    capture = "/".join(parts[: capture_index + 1]) if capture_index >= 0 else ""
    segment = "/".join(parts[: segment_index + 1]) if segment_index >= 0 else ""
    return capture, segment


def audit(dataset_root: Path, annotation_root: Path, output: Path) -> dict:
    json_paths, scan_errors = _walk_json(annotation_root)
    captures: dict[str, dict] = defaultdict(
        lambda: {
            "frames": 0,
            "boxes": 0,
            "numeric_depth_boxes": 0,
            "relative_depth_boxes": 0,
            "invalid_json": 0,
            "segments": set(),
        }
    )
    frame_rows = []
    for path in sorted(json_paths):
        capture_key, segment_key = _capture_parts(path, annotation_root)
        if not capture_key:
            continue
        row = captures[capture_key]
        row["frames"] += 1
        row["segments"].add(segment_key)
        boxes = numeric = relative = 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for shape in data.get("shapes", []):
                if len(shape.get("points", [])) < 2:
                    continue
                boxes += 1
                attributes = shape.get("attributes") or {}
                if isinstance(attributes.get("depth_m"), (int, float)):
                    numeric += 1
                if attributes.get("relative_depth_tier") or isinstance(
                    attributes.get("relative_depth_score"), (int, float)
                ):
                    relative += 1
        except Exception as exc:
            row["invalid_json"] += 1
            frame_rows.append(
                {"annotation": str(path), "status": "invalid_json", "error": str(exc)}
            )
            continue
        row["boxes"] += boxes
        row["numeric_depth_boxes"] += numeric
        row["relative_depth_boxes"] += relative
        frame_rows.append(
            {
                "annotation": str(path),
                "capture": capture_key,
                "segment": segment_key,
                "boxes": boxes,
                "numeric_depth_boxes": numeric,
                "relative_depth_boxes": relative,
            }
        )

    capture_rows = []
    for capture_key, values in sorted(captures.items()):
        capture_dir = dataset_root / capture_key
        radar_dirs = list(capture_dir.glob("*_radar"))
        mat_count = sum(1 for directory in radar_dirs for _ in directory.glob("*.mat"))
        bin_count = sum(1 for _ in capture_dir.glob("*_mmwave_udp.bin"))
        target_db = capture_dir / "target_depth_db.json"
        target_count = 0
        if target_db.exists():
            try:
                target_count = len(
                    json.loads(target_db.read_text(encoding="utf-8")).get("targets", [])
                )
            except Exception:
                pass
        nav_segments = 0
        for segment_key in values["segments"]:
            segment_relative = Path(segment_key).relative_to(capture_key)
            segment_dir = capture_dir / segment_relative
            gps = segment_dir / "gps" / "nav100__fix" / "nav100__fix.csv"
            heading = (
                segment_dir
                / "heading"
                / "nav100__heading"
                / "nav100__heading.csv"
            )
            if gps.exists() and heading.exists():
                nav_segments += 1
        capture_rows.append(
            {
                **{k: v for k, v in values.items() if k != "segments"},
                "capture": capture_key,
                "segments": len(values["segments"]),
                "segments_with_nav": nav_segments,
                "mat_files": mat_count,
                "bin_files": bin_count,
                "map_targets": target_count,
                "numeric_coverage": round(
                    values["numeric_depth_boxes"] / max(values["boxes"], 1), 4
                ),
                "has_metric_source": bool(mat_count or target_count),
            }
        )

    report = {
        "dataset_root": str(dataset_root),
        "annotation_root": str(annotation_root),
        "annotation_files": len(json_paths),
        "boxes": sum(row["boxes"] for row in capture_rows),
        "numeric_depth_boxes": sum(
            row["numeric_depth_boxes"] for row in capture_rows
        ),
        "captures": capture_rows,
        "scan_errors": scan_errors,
        "frames": frame_rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--annotation-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.dataset_root, args.annotation_root, args.output)
    summary = {key: value for key, value in report.items() if key not in {"frames", "captures"}}
    summary["capture_count"] = len(report["captures"])
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
