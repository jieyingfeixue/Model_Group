#!/usr/bin/env python3
"""Export LabelMe annotations with per-shape metric depth attributes."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.fusion.bin_detection_projection import sample_bin_detection_map
from src.fusion.depth_forward_sync import horizontal_distance_m
from src.io.adapters.lh_adapter import load_capture_bin_detection_map
from tools.assign_depth_from_db import TemporalMatchState, _match_boxes_to_targets


TIMESTAMP_MARKER = "_t"
TIMESTAMP_RE = re.compile(r"_t(\d+(?:\.\d+)?)")
# 从 oST 双目标定结果读取（已去畸变）
FX = 12342.233207       # 左相机 fx
FY = 12338.268051       # 左相机 fy
CX = 959.500000         # 主点 x（图像中心）
CY = 599.500000         # 主点 y（图像中心）
IMAGE_WIDTH = 1920
IMAGE_HEIGHT = 1200
HEADING_OFFSET_DEG = -90.0

# BIN kind → label keyword mapping (bin_detection_projection.py constants):
#   KIND_DENSE = 1.0     — polygon vertex clusters (large structures)
#   KIND_ISOLATED = 2.0  — isolated point targets (towers/chimneys)
#   KIND_POWERLINE = 3.0 — power line segments
# Each tuple: (keyword_group, acceptable_kinds)
_LABEL_KIND_MAP = [
    (("tower", "power"),      {3.0, 2.0}),    # tower类: powerline + isolated
    (("turbine",),             {2.0}),          # 风机: isolated
    (("chimney", "smokestack"), {2.0}),         # 烟囱: isolated
    (("building",),            {1.0, 2.0}),     # 楼房: dense + isolated
    (("bridge",),              {1.0, 2.0}),     # 大桥: dense + isolated
    (("signal", "television"), {2.0, 3.0}),     # 信号/电视塔: isolated + powerline
]
MIN_DEPTH_M = 400.0
MAX_DEPTH_M = 4000.0
TEMPORAL_PROPAGATION_SEC = 1.5
TEMPORAL_PROPAGATION_MAX_DX = 0.12


@dataclass
class SegmentNav:
    gps_t: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    altitude: np.ndarray
    heading_t: np.ndarray
    heading: np.ndarray

    def pose(self, timestamp: float) -> tuple[float, float, float, float]:
        return (
            float(np.interp(timestamp, self.gps_t, self.latitude)),
            float(np.interp(timestamp, self.gps_t, self.longitude)),
            float(np.interp(timestamp, self.gps_t, self.altitude)),
            float(np.interp(timestamp, self.heading_t, self.heading)),
        )


def parse_timestamp(stem: str) -> float:
    matches = list(TIMESTAMP_RE.finditer(stem))
    if not matches:
        raise ValueError(f"timestamp not found in {stem}")
    return float(matches[-1].group(1))


def load_segment_nav(segment_dir: Path) -> SegmentNav:
    gps_path = segment_dir / "gps" / "nav100__fix" / "nav100__fix.csv"
    heading_path = (
        segment_dir / "heading" / "nav100__heading" / "nav100__heading.csv"
    )
    with gps_path.open(newline="", encoding="utf-8") as handle:
        gps_rows = list(csv.DictReader(handle))
    with heading_path.open(newline="", encoding="utf-8") as handle:
        heading_rows = list(csv.DictReader(handle))
    return SegmentNav(
        gps_t=np.asarray(
            [float(row["relative_time_sec"]) for row in gps_rows], dtype=np.float64
        ),
        latitude=np.asarray(
            [float(row["latitude"]) for row in gps_rows], dtype=np.float64
        ),
        longitude=np.asarray(
            [float(row["longitude"]) for row in gps_rows], dtype=np.float64
        ),
        altitude=np.asarray(
            [float(row.get("altitude", 0.0)) for row in gps_rows],
            dtype=np.float64,
        ),
        heading_t=np.asarray(
            [float(row["relative_time_sec"]) for row in heading_rows],
            dtype=np.float64,
        ),
        heading=np.asarray(
            [float(row["value"]) for row in heading_rows], dtype=np.float64
        ),
    )


def shape_bbox(shape: dict[str, Any]) -> list[float] | None:
    points = shape.get("points", [])
    if len(points) < 2:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return [min(xs), min(ys), max(xs), max(ys)]


def project_detection_candidates(
    samples: np.ndarray,
    latitude: float,
    longitude: float,
    heading_deg: float,
    vehicle_altitude: float = 0.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return candidate pixel positions and metric horizontal ranges.

    Returns (pixel_x, pixel_y, distance_m, kinds).
    """
    lat = samples[:, 0]
    lon = samples[:, 1]
    alt = samples[:, 2]
    kinds = samples[:, 4]
    east = (
        (lon - longitude)
        * math.pi
        / 180.0
        * 6378137.0
        * math.cos(math.radians(latitude))
    )
    north = (lat - latitude) * math.pi / 180.0 * 6356752.3
    heading = math.radians(heading_deg + HEADING_OFFSET_DEG)
    right = east * math.cos(heading) - north * math.sin(heading)
    forward = east * math.sin(heading) + north * math.cos(heading)
    up = alt - vehicle_altitude
    distance = np.hypot(right, forward)
    valid = (
        (forward > 0.1)
        & (distance >= MIN_DEPTH_M)
        & (distance <= MAX_DEPTH_M)
    )
    right = right[valid]
    forward = forward[valid]
    up = up[valid]
    distance = distance[valid]
    kinds = kinds[valid]
    pixel_x = FX * right / forward + CX
    # camera y=down, so a positive up in body → negative y in camera.
    # Only used as soft weight (no reliable pitch for hard Y filtering).
    pixel_y_norm = (CY - FY * up / forward) / IMAGE_HEIGHT * 2.0 - 1.0
    in_image = (pixel_x >= 0.0) & (pixel_x < IMAGE_WIDTH)
    return pixel_x[in_image], pixel_y_norm[in_image], distance[in_image], kinds[in_image]


def assign_bin_depths(
    boxes: list[dict[str, Any]],
    pixel_x: np.ndarray,
    pixel_y_norm: np.ndarray,
    ranges: np.ndarray,
    kinds: np.ndarray,
) -> list[dict[str, Any]]:
    rows = []
    for box in boxes:
        x0, _y0, x1, _y1 = box["bbox_xyxy"]
        label_lower = " ".join(str(box.get("label", "")).lower().split())

        # ── 语义门：BIN kind → label keyword 映射 ──
        acceptable_kinds: set[float] = set()
        for keywords, kinds_set in _LABEL_KIND_MAP:
            if any(kw in label_lower for kw in keywords):
                acceptable_kinds.update(kinds_set)
        if not acceptable_kinds:
            acceptable_kinds = {1.0, 2.0, 3.0}
        semantic = np.isin(kinds, list(acceptable_kinds))

        # ── X轴硬过滤 + Y 轴软加权 ──
        mask = (pixel_x >= x0) & (pixel_x <= x1) & semantic
        if mask.any():
            values = ranges[mask]
            depth = float(np.median(values))
            spread = float(np.percentile(values, 75) - np.percentile(values, 25))
            # Y-deviation soft weight (dead centre=1.0, off-screen→0.3)
            dev_w = max(0.3, 1.0 - abs(float(np.median(pixel_y_norm[mask]))))
            confidence = max(0.30, min(0.90, 1.0 - spread / max(depth, 1.0))) * dev_w
            rows.append(
                {
                    **box,
                    "depth_m": round(depth, 1),
                    "method": "bin_semantic_target_camera_fov",
                    "confidence": round(confidence, 3),
                    "support_points": int(mask.sum()),
                    "depth_iqr_m": round(spread, 1),
                }
            )
        else:
            rows.append(
                {
                    **box,
                    "depth_m": None,
                    "method": "no_semantic_bin_target_in_box_fov",
                    "confidence": 0.0,
                    "support_points": 0,
                }
            )
    return rows


def merge_map_and_bin_depths(
    map_rows: list[dict[str, Any]],
    bin_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = []
    for map_row, bin_row in zip(map_rows, bin_rows):
        if isinstance(map_row.get("depth_m"), (int, float)):
            merged.append(map_row)
        else:
            merged.append(bin_row)
    return merged


def update_labelme(
    source_path: Path,
    destination_path: Path,
    depth_rows: list[dict[str, Any]],
) -> tuple[int, int]:
    data = json.loads(source_path.read_text(encoding="utf-8"))
    depth_index = 0
    numeric = 0
    total = 0
    for shape in data.get("shapes", []):
        if shape_bbox(shape) is None:
            continue
        row = depth_rows[depth_index]
        depth_index += 1
        total += 1
        attributes = shape.get("attributes")
        if not isinstance(attributes, dict):
            attributes = {}
            shape["attributes"] = attributes
        depth = row.get("depth_m")
        attributes["depth_m"] = (
            round(float(depth), 1) if isinstance(depth, (int, float)) else None
        )
        attributes["depth_method"] = row.get("method", "unknown")
        attributes["depth_confidence"] = round(
            float(row.get("confidence", 0.0)), 3
        )
        attributes["depth_support_points"] = int(row.get("support_points", 0))
        if row.get("target_id") is not None:
            attributes["depth_target_id"] = row["target_id"]
        if isinstance(depth, (int, float)):
            numeric += 1
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    destination_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return total, numeric


def _canonical_label(label: str) -> str:
    text = " ".join(str(label).strip().lower().replace("_", " ").split())
    if "building" in text or "建筑" in text or "楼" in text:
        return "building"
    if "tower" in text or "pylon" in text or "铁塔" in text or "电塔" in text:
        return "tower"
    return text


def propagate_temporal_depths(output_dir: Path, capture_dir: Path) -> int:
    """Fill short dropouts only when a world anchor allows pose compensation."""
    target_db_path = capture_dir / "target_depth_db.json"
    target_by_id = {}
    if target_db_path.exists():
        target_data = json.loads(target_db_path.read_text(encoding="utf-8"))
        target_by_id = {
            str(target["id"]): target for target in target_data.get("targets", [])
        }
    nav_cache: dict[Path, SegmentNav] = {}

    def frame_pose(path: Path, timestamp: float) -> tuple[float, float] | None:
        relative = path.relative_to(output_dir)
        segment_parts = []
        for part in relative.parts:
            segment_parts.append(part)
            if part.lower().startswith("segment_"):
                break
        else:
            return None
        segment_dir = capture_dir.joinpath(*segment_parts)
        try:
            nav = nav_cache.get(segment_dir)
            if nav is None:
                nav = load_segment_nav(segment_dir)
                nav_cache[segment_dir] = nav
            latitude, longitude, _altitude, _heading = nav.pose(timestamp)
            return latitude, longitude
        except (OSError, ValueError, KeyError):
            return None

    grouped: dict[Path, list[tuple[float, Path]]] = {}
    for path in output_dir.rglob("*.json"):
        if path.name == "depth_export_summary.json":
            continue
        try:
            timestamp = parse_timestamp(path.stem)
        except ValueError:
            continue
        grouped.setdefault(path.parent, []).append((timestamp, path))

    propagated = 0
    for entries in grouped.values():
        entries.sort()
        documents = [
            json.loads(path.read_text(encoding="utf-8"))
            for _timestamp, path in entries
        ]
        candidates: list[list[dict[str, Any]]] = []
        for (timestamp, _path), data in zip(entries, documents):
            image_width = float(data.get("imageWidth", IMAGE_WIDTH) or IMAGE_WIDTH)
            frame_candidates = []
            for index, shape in enumerate(data.get("shapes", [])):
                bbox = shape_bbox(shape)
                if bbox is None:
                    continue
                attributes = shape.get("attributes") or {}
                depth = attributes.get("depth_m")
                if not isinstance(depth, (int, float)):
                    continue
                frame_candidates.append(
                    {
                        "index": index,
                        "label": _canonical_label(shape.get("label", "")),
                        "cx": (bbox[0] + bbox[2]) * 0.5 / max(image_width, 1.0),
                        "depth_m": float(depth),
                        "confidence": float(attributes.get("depth_confidence", 0.5)),
                        "time": timestamp,
                        "target_id": attributes.get("depth_target_id"),
                        "anchor_lat": attributes.get("depth_anchor_lat"),
                        "anchor_lon": attributes.get("depth_anchor_lon"),
                        "anchor_bias_m": float(
                            attributes.get("depth_anchor_bias_m", 0.0) or 0.0
                        ),
                    }
                )
            candidates.append(frame_candidates)

        for frame_index, ((timestamp, path), data) in enumerate(
            zip(entries, documents)
        ):
            image_width = float(data.get("imageWidth", IMAGE_WIDTH) or IMAGE_WIDTH)
            changed = False
            for shape in data.get("shapes", []):
                bbox = shape_bbox(shape)
                if bbox is None:
                    continue
                attributes = shape.get("attributes")
                if not isinstance(attributes, dict):
                    attributes = {}
                    shape["attributes"] = attributes
                if isinstance(attributes.get("depth_m"), (int, float)):
                    continue
                label = _canonical_label(shape.get("label", ""))
                cx = (bbox[0] + bbox[2]) * 0.5 / max(image_width, 1.0)
                nearest = []
                for other_index, frame_candidates in enumerate(candidates):
                    dt = abs(entries[other_index][0] - timestamp)
                    if dt <= 0.0 or dt > TEMPORAL_PROPAGATION_SEC:
                        continue
                    for candidate in frame_candidates:
                        if candidate["label"] != label:
                            continue
                        dx = abs(candidate["cx"] - cx)
                        if dx <= TEMPORAL_PROPAGATION_MAX_DX:
                            nearest.append((dt, dx, candidate))
                if not nearest:
                    attributes.setdefault("depth_method", "no_metric_anchor")
                    continue
                dt, dx, candidate = min(nearest, key=lambda item: (item[0], item[1]))
                anchor_lat = candidate.get("anchor_lat")
                anchor_lon = candidate.get("anchor_lon")
                anchor_bias = float(candidate.get("anchor_bias_m", 0.0))
                target_id = candidate.get("target_id")
                target = target_by_id.get(str(target_id)) if target_id is not None else None
                if target is not None:
                    anchor_lat = target.get("lat")
                    anchor_lon = target.get("lon")
                    anchor_bias = float(target.get("depth_offset_m", 0.0) or 0.0)
                pose = frame_pose(path, timestamp)
                if (
                    pose is None
                    or not isinstance(anchor_lat, (int, float))
                    or not isinstance(anchor_lon, (int, float))
                ):
                    attributes.setdefault("depth_method", "no_pose_aware_metric_anchor")
                    continue
                confidence = candidate["confidence"] * max(
                    0.2, 1.0 - dt / (TEMPORAL_PROPAGATION_SEC * 1.25)
                )
                attributes["depth_m"] = round(
                    horizontal_distance_m(
                        pose[0], pose[1], float(anchor_lat), float(anchor_lon)
                    )
                    + anchor_bias,
                    1,
                )
                attributes["depth_method"] = "temporal_world_anchor_pose_compensated"
                attributes["depth_confidence"] = round(min(confidence, 0.45), 3)
                attributes["depth_support_points"] = 0
                attributes["depth_source_dt_sec"] = round(dt, 3)
                attributes["depth_source_dx_norm"] = round(dx, 4)
                attributes["depth_anchor_lat"] = float(anchor_lat)
                attributes["depth_anchor_lon"] = float(anchor_lon)
                attributes["depth_anchor_bias_m"] = round(anchor_bias, 3)
                propagated += 1
                changed = True
            if changed:
                path.write_text(
                    json.dumps(data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
    return propagated


def export_capture(
    capture_dir: Path,
    annotation_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    for source_directory in annotation_dir.rglob("*"):
        if source_directory.is_dir():
            (output_dir / source_directory.relative_to(annotation_dir)).mkdir(
                parents=True, exist_ok=True
            )
    detection_map = load_capture_bin_detection_map(capture_dir)
    samples = sample_bin_detection_map(detection_map)
    target_db_path = capture_dir / "target_depth_db.json"
    targets = (
        json.loads(target_db_path.read_text(encoding="utf-8")).get("targets", [])
        if target_db_path.exists()
        else []
    )
    json_paths = sorted(annotation_dir.rglob("*.json"))
    # Cloud-sync conflict copies represent the same camera timestamp. Keep the
    # canonical filename when available, otherwise keep the first readable copy.
    unique_paths: dict[tuple[Path, float], Path] = {}
    for path in json_paths:
        try:
            key = (path.parent, parse_timestamp(path.stem))
        except ValueError:
            continue
        previous = unique_paths.get(key)
        if previous is None or (
            "__conflict_" in previous.stem and "__conflict_" not in path.stem
        ):
            unique_paths[key] = path
    json_paths = sorted(unique_paths.values())
    nav_cache: dict[Path, SegmentNav] = {}
    state_cache: dict[Path, TemporalMatchState] = {}
    summary_rows = []
    box_count = numeric_count = 0

    for index, source_path in enumerate(json_paths, 1):
        relative = source_path.relative_to(annotation_dir)
        parts = relative.parts
        segment_index = next(
            i for i, part in enumerate(parts) if part.startswith("segment_")
        )
        relative_segment = Path(*parts[: segment_index + 1])
        data_segment = capture_dir / relative_segment
        nav = nav_cache.get(data_segment)
        if nav is None:
            try:
                nav = load_segment_nav(data_segment)
            except (FileNotFoundError, OSError, KeyError, ValueError):
                nav = None
            nav_cache[data_segment] = nav
        if nav is None:
            labelme = json.loads(source_path.read_text(encoding="utf-8"))
            rows = []
            for shape in labelme.get("shapes", []):
                bbox = shape_bbox(shape)
                if bbox is not None:
                    rows.append(
                        {
                            "label": shape.get("label", ""),
                            "bbox_xyxy": bbox,
                            "depth_m": None,
                            "method": "missing_navigation",
                            "confidence": 0.0,
                            "support_points": 0,
                        }
                    )
            frame_boxes, frame_numeric = update_labelme(
                source_path, output_dir / relative, rows
            )
            box_count += frame_boxes
            numeric_count += frame_numeric
            summary_rows.append(
                {
                    "annotation": relative.as_posix(),
                    "boxes": frame_boxes,
                    "numeric_depths": frame_numeric,
                    "null_depths": frame_boxes,
                    "reason": "missing_navigation",
                }
            )
            continue
        state = state_cache.setdefault(data_segment, TemporalMatchState())
        timestamp = parse_timestamp(source_path.stem)
        latitude, longitude, altitude, heading = nav.pose(timestamp)

        labelme = json.loads(source_path.read_text(encoding="utf-8"))
        image_width = int(labelme.get("imageWidth", IMAGE_WIDTH) or IMAGE_WIDTH)
        boxes = []
        for shape in labelme.get("shapes", []):
            bbox = shape_bbox(shape)
            if bbox is None:
                continue
            boxes.append(
                {
                    "label": shape.get("label", ""),
                    "bbox_xyxy": bbox,
                    "img_w": image_width,
                    "img_h": int(labelme.get("imageHeight", 1200) or 1200),
                }
            )

        pixel_x, pixel_y, ranges, kinds = project_detection_candidates(
            samples, latitude, longitude, heading, vehicle_altitude=altitude,
        )
        bin_rows = assign_bin_depths(boxes, pixel_x, pixel_y, ranges, kinds)
        map_rows = _match_boxes_to_targets(
            boxes,
            targets,
            latitude,
            longitude,
            heading,
            fov_deg=8.78,  # from fx=12503.99 calibration
            az_thresh=4.0,
            state=state,
            frame_time=timestamp,
        )
        depth_rows = merge_map_and_bin_depths(map_rows, bin_rows)
        frame_boxes, frame_numeric = update_labelme(
            source_path, output_dir / relative, depth_rows
        )
        box_count += frame_boxes
        numeric_count += frame_numeric
        summary_rows.append(
            {
                "annotation": relative.as_posix(),
                "boxes": frame_boxes,
                "numeric_depths": frame_numeric,
                "null_depths": frame_boxes - frame_numeric,
            }
        )
        if index % 50 == 0 or index == len(json_paths):
            print(f"[{index}/{len(json_paths)}] boxes={box_count} numeric={numeric_count}")

    summary = {
        "source_annotations": str(annotation_dir),
        "source_capture": str(capture_dir),
        "output": str(output_dir),
        "annotation_files": len(json_paths),
        "boxes": box_count,
        "numeric_depths": numeric_count,
        "null_depths": box_count - numeric_count,
        "depth_coverage": round(numeric_count / max(box_count, 1), 4),
        "shape_attributes": [
            "depth_m",
            "depth_method",
            "depth_confidence",
            "depth_support_points",
            "depth_target_id (map matches only)",
        ],
        "frames": summary_rows,
    }
    propagated = propagate_temporal_depths(output_dir, capture_dir)
    if propagated:
        numeric_count += propagated
        summary["numeric_depths"] = numeric_count
        summary["null_depths"] = box_count - numeric_count
        summary["depth_coverage"] = round(numeric_count / max(box_count, 1), 4)
    summary["temporal_propagated_depths"] = propagated
    (output_dir / "depth_export_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 BIN/地图深度写入原结构一致的 LabelMe 标注副本。"
    )
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--annotation-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.capture_dir.is_dir() or not args.annotation_dir.is_dir():
        print("输入 capture 或 annotation 目录不存在", file=sys.stderr)
        return 2
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = export_capture(
        args.capture_dir, args.annotation_dir, args.output_dir
    )
    print(json.dumps({k: v for k, v in summary.items() if k != "frames"},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
