#!/usr/bin/env python3
"""Run the hybrid depth exporter for every annotated capture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.export_labelme_depth import export_capture


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--annotation-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()

    capture_dirs = sorted(
        path
        for path in args.annotation_root.glob("*/*")
        if path.is_dir() and path.name.startswith("with_cameras_capture_")
    )
    summaries = []
    report_path = args.output_root / "depth_dataset_summary.json"

    def write_report() -> dict:
        totals = {
            "captures": len(summaries),
            "failed_captures": sum("error" in row for row in summaries),
            "annotation_files": sum(row.get("annotation_files", 0) for row in summaries),
            "boxes": sum(row.get("boxes", 0) for row in summaries),
            "numeric_depths": sum(row.get("numeric_depths", 0) for row in summaries),
            "null_depths": sum(row.get("null_depths", 0) for row in summaries),
        }
        totals["depth_coverage"] = round(
            totals["numeric_depths"] / max(totals["boxes"], 1), 4
        )
        args.output_root.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(
                {"totals": totals, "captures": summaries},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return totals

    for index, annotation_dir in enumerate(capture_dirs, 1):
        relative = annotation_dir.relative_to(args.annotation_root)
        capture_dir = args.dataset_root / relative
        output_dir = args.output_root / relative
        if not capture_dir.is_dir():
            summaries.append(
                {
                    "capture": relative.as_posix(),
                    "error": "dataset capture directory missing",
                }
            )
            write_report()
            continue
        print(f"[{index}/{len(capture_dirs)}] {relative.as_posix()}")
        try:
            summary_path = output_dir / "depth_export_summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                print("  resume: existing summary")
            else:
                summary = export_capture(capture_dir, annotation_dir, output_dir)
            summaries.append(
                {
                    key: value
                    for key, value in summary.items()
                    if key != "frames"
                }
            )
        except Exception as exc:
            summaries.append(
                {"capture": relative.as_posix(), "error": str(exc)}
            )
        write_report()

    totals = write_report()
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 1 if totals["failed_captures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
