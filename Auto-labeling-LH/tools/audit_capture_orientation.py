#!/usr/bin/env python3
"""Audit nav heading against GPS trajectory direction for every capture."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np


def _angle_diff(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    return (a - b + 180.0) % 360.0 - 180.0


def _read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def audit_segment(segment: Path) -> dict | None:
    gps_path = segment / "gps" / "nav100__fix" / "nav100__fix.csv"
    heading_path = (
        segment / "heading" / "nav100__heading" / "nav100__heading.csv"
    )
    if not gps_path.exists() or not heading_path.exists():
        return None
    gps_rows = _read_csv(gps_path)
    heading_rows = _read_csv(heading_path)
    if len(gps_rows) < 3 or not heading_rows:
        return None
    t = np.asarray([float(row["relative_time_sec"]) for row in gps_rows])
    lat = np.asarray([float(row["latitude"]) for row in gps_rows])
    lon = np.asarray([float(row["longitude"]) for row in gps_rows])
    heading_t = np.asarray(
        [float(row["relative_time_sec"]) for row in heading_rows]
    )
    heading = np.asarray([float(row["value"]) for row in heading_rows])

    # Collapse high-rate duplicate positions to a one-second trajectory.
    start = math.ceil(float(t.min()))
    end = math.floor(float(t.max()))
    sample_t = np.arange(start, end + 0.01, 1.0)
    if len(sample_t) < 3:
        return None
    sample_lat = np.interp(sample_t, t, lat)
    sample_lon = np.interp(sample_t, t, lon)
    # Interpolate on an unwrapped circle. Direct interpolation turns a
    # 359 -> 0 degree transition into a false 180-degree heading.
    heading_unwrapped = np.unwrap(np.radians(heading))
    sample_heading = (
        np.degrees(np.interp(sample_t, heading_t, heading_unwrapped)) % 360.0
    )
    mean_lat = math.radians(float(np.mean(sample_lat)))
    east = sample_lon * math.pi / 180.0 * 6378137.0 * math.cos(mean_lat)
    north = sample_lat * math.pi / 180.0 * 6356752.3
    delta_e = east[2:] - east[:-2]
    delta_n = north[2:] - north[:-2]
    distance = np.hypot(delta_e, delta_n)
    course = (
        np.degrees(np.arctan2(delta_e, delta_n)) + 360.0
    ) % 360.0
    nav = sample_heading[1:-1]
    moving = distance >= 4.0
    if moving.sum() < 5:
        return {
            "segment": str(segment),
            "samples": int(moving.sum()),
            "status": "insufficient_motion",
        }
    diff = _angle_diff(nav[moving], course[moving])
    abs_zero = np.abs(diff)
    abs_flip = np.abs(_angle_diff(nav[moving] + 180.0, course[moving]))
    return {
        "segment": str(segment),
        "samples": int(moving.sum()),
        "median_nav_minus_course_deg": round(float(np.median(diff)), 1),
        "median_error_as_recorded_deg": round(float(np.median(abs_zero)), 1),
        "median_error_if_flipped_deg": round(float(np.median(abs_flip)), 1),
        "flip_votes": int(np.sum(abs_flip + 20.0 < abs_zero)),
        "normal_votes": int(np.sum(abs_zero + 20.0 < abs_flip)),
        "status": "ok",
    }


def audit(dataset_root: Path) -> dict:
    captures = []
    for capture in sorted(dataset_root.glob("*/*")):
        if not capture.is_dir() or not capture.name.startswith(
            "with_cameras_capture_"
        ):
            continue
        segments = sorted(capture.rglob("segment_*"))
        rows = [
            row for row in (audit_segment(segment) for segment in segments)
            if row is not None
        ]
        usable = [row for row in rows if row.get("status") == "ok"]
        flip_votes = sum(row["flip_votes"] for row in usable)
        normal_votes = sum(row["normal_votes"] for row in usable)
        samples = sum(row["samples"] for row in usable)
        if samples < 10:
            orientation = "unknown"
        elif flip_votes > max(10, normal_votes * 1.5):
            orientation = "likely_180_flipped"
        elif normal_votes > max(10, flip_votes * 1.5):
            orientation = "normal"
        else:
            orientation = "ambiguous_or_sideways_flight"
        mat_count = sum(1 for _ in capture.rglob("*.mat"))
        bin_count = sum(1 for _ in capture.glob("*_mmwave_udp.bin"))
        captures.append(
            {
                "capture": str(capture.relative_to(dataset_root)).replace("\\", "/"),
                "orientation": orientation,
                "trajectory_samples": samples,
                "flip_votes": flip_votes,
                "normal_votes": normal_votes,
                "mat_files": mat_count,
                "bin_files": bin_count,
                "segments": rows,
            }
        )
    return {"dataset_root": str(dataset_root), "captures": captures}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.dataset_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for row in report["captures"]:
        print(
            row["capture"],
            row["orientation"],
            f"votes={row['normal_votes']}/{row['flip_votes']}",
            f"mat={row['mat_files']} bin={row['bin_files']}",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
