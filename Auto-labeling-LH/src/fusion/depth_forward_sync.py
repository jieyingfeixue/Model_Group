"""Fast pose-aware forward propagation for manually corrected box depths."""

from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np


EARTH_RADIUS_M = 6371008.8
CAMERA_HFOV_DEG = 8.78     # 75mm telephoto, fx=12503.99 → 2*atan(1920/(2*12504))≈8.78°
CAMERA_HEADING_OFFSET_DEG = -90.0
TIMESTAMP_RE = re.compile(r"_t(\d+(?:\.\d+)?)")


@dataclass(frozen=True)
class WorldDepthAnchor:
    latitude: float
    longitude: float
    depth_bias_m: float = 0.0
    source: str = "manual_camera_ray"


@dataclass(frozen=True)
class ForwardSyncRequest:
    source_path: Path
    output_path: Path
    source_root: Path
    depth_root: Path
    dataset_root: Path
    shape_index: int
    anchor: WorldDepthAnchor
    source_frame: str
    annotation_roots: tuple[Path, ...] = ()
    max_consecutive_misses: int = 8


@dataclass(frozen=True)
class ForwardSyncResult:
    updated_frames: int
    inspected_frames: int
    stopped_reason: str


@dataclass
class _SegmentNav:
    gps_t: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    heading_t: np.ndarray
    heading: np.ndarray

    def pose(self, timestamp: float) -> tuple[float, float, float]:
        return (
            float(np.interp(timestamp, self.gps_t, self.latitude)),
            float(np.interp(timestamp, self.gps_t, self.longitude)),
            float(np.interp(timestamp, self.heading_t, self.heading)),
        )


def parse_timestamp(path: Path) -> float:
    matches = list(TIMESTAMP_RE.finditer(path.stem))
    if not matches:
        raise ValueError(f"timestamp not found in {path.name}")
    return float(matches[-1].group(1))


def canonical_label(label: str) -> str:
    text = " ".join(str(label).strip().lower().replace("_", " ").split())
    if "building" in text:
        return "building"
    if "tower" in text or "pylon" in text:
        return "tower"
    return text


def shape_bbox(shape: dict) -> tuple[float, float, float, float] | None:
    points = shape.get("points") or []
    if len(points) < 2:
        return None
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def horizontal_distance_m(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = lat2_rad - lat1_rad
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat * 0.5) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon * 0.5) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = (
        math.cos(lat1_rad) * math.sin(lat2_rad)
        - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    )
    return math.degrees(math.atan2(y, x)) % 360.0


def destination_point(
    latitude: float, longitude: float, distance_m: float, bearing: float
) -> tuple[float, float]:
    angular = distance_m / EARTH_RADIUS_M
    lat1 = math.radians(latitude)
    lon1 = math.radians(longitude)
    angle = math.radians(bearing)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(angle)
    )
    lon2 = lon1 + math.atan2(
        math.sin(angle) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def build_world_anchor(
    *,
    depth_m: float,
    vehicle_lat: float,
    vehicle_lon: float,
    camera_heading_deg: float,
    bbox: tuple[float, float, float, float],
    image_width: float,
    target: dict | None = None,
) -> WorldDepthAnchor:
    if target is not None:
        target_lat = float(target["lat"])
        target_lon = float(target["lon"])
        map_distance = horizontal_distance_m(
            vehicle_lat, vehicle_lon, target_lat, target_lon
        )
        return WorldDepthAnchor(
            latitude=target_lat,
            longitude=target_lon,
            depth_bias_m=float(depth_m) - map_distance,
            source="target_depth_db",
        )

    center_x = (bbox[0] + bbox[2]) * 0.5
    normalized_x = center_x / max(float(image_width), 1.0)
    object_bearing = (
        float(camera_heading_deg)
        + (normalized_x - 0.5) * CAMERA_HFOV_DEG
    ) % 360.0
    target_lat, target_lon = destination_point(
        vehicle_lat, vehicle_lon, float(depth_m), object_bearing
    )
    return WorldDepthAnchor(
        latitude=target_lat,
        longitude=target_lon,
        source="manual_camera_ray",
    )


def load_target(capture_dir: Path, target_id: object) -> dict | None:
    if target_id in (None, ""):
        return None
    path = Path(capture_dir) / "target_depth_db.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    wanted = str(target_id)
    for target in data.get("targets", []):
        if str(target.get("id")) == wanted:
            return target
    return None


def _load_nav(segment_dir: Path) -> _SegmentNav:
    gps_path = segment_dir / "gps" / "nav100__fix" / "nav100__fix.csv"
    heading_path = (
        segment_dir / "heading" / "nav100__heading" / "nav100__heading.csv"
    )
    with gps_path.open(newline="", encoding="utf-8") as handle:
        gps_rows = list(csv.DictReader(handle))
    with heading_path.open(newline="", encoding="utf-8") as handle:
        heading_rows = list(csv.DictReader(handle))
    return _SegmentNav(
        gps_t=np.asarray(
            [float(row["relative_time_sec"]) for row in gps_rows], dtype=np.float64
        ),
        latitude=np.asarray(
            [float(row["latitude"]) for row in gps_rows], dtype=np.float64
        ),
        longitude=np.asarray(
            [float(row["longitude"]) for row in gps_rows], dtype=np.float64
        ),
        heading_t=np.asarray(
            [float(row["relative_time_sec"]) for row in heading_rows],
            dtype=np.float64,
        ),
        heading=np.asarray(
            [float(row["value"]) for row in heading_rows], dtype=np.float64
        ),
    )


def _part_directory(source_path: Path, source_root: Path) -> Path:
    relative = source_path.relative_to(source_root)
    for index, part in enumerate(relative.parts):
        if "_part" in part.lower():
            return source_root.joinpath(*relative.parts[: index + 1])
    raise ValueError(f"part directory not found for {source_path}")


def _part_relative_prefix(source_path: Path, source_root: Path) -> Path:
    relative = source_path.relative_to(source_root)
    for index, part in enumerate(relative.parts):
        if "_part" in part.lower():
            return Path(*relative.parts[: index + 1])
    raise ValueError(f"part directory not found for {source_path}")


def _collect_part_entries(
    request: ForwardSyncRequest,
    source_time: float,
) -> tuple[list[tuple[float, Path, Path]], list[tuple[float, Path, Path]]]:
    roots = request.annotation_roots or (request.source_root,)
    part_prefix = _part_relative_prefix(request.source_path, request.source_root)
    before: list[tuple[float, Path, Path]] = []
    after: list[tuple[float, Path, Path]] = []
    seen: set[tuple[float, str]] = set()
    for root in roots:
        part_dir = root / part_prefix
        if not part_dir.exists():
            continue
        for path in part_dir.rglob("*.json"):
            if path == request.source_path:
                continue
            try:
                timestamp = parse_timestamp(path)
            except ValueError:
                continue
            key = (timestamp, str(path))
            if key in seen:
                continue
            seen.add(key)
            entry = (timestamp, path, root)
            if timestamp > source_time:
                after.append(entry)
            elif timestamp < source_time:
                before.append(entry)
    after.sort(key=lambda item: (item[0], str(item[1])))
    before.sort(key=lambda item: (-item[0], str(item[1])))
    return before, after


def _segment_directory(
    source_path: Path, source_root: Path, dataset_root: Path
) -> Path:
    relative = source_path.relative_to(source_root)
    for index, part in enumerate(relative.parts):
        if part.lower().startswith("segment_"):
            return dataset_root.joinpath(*relative.parts[: index + 1])
    raise ValueError(f"segment directory not found for {source_path}")


def _normalized_geometry(
    bbox: tuple[float, float, float, float], width: float, height: float
) -> tuple[float, float, float, float]:
    width = max(width, 1.0)
    height = max(height, 1.0)
    return (
        (bbox[0] + bbox[2]) * 0.5 / width,
        (bbox[1] + bbox[3]) * 0.5 / height,
        max(bbox[2] - bbox[0], 1.0) / width,
        max(bbox[3] - bbox[1], 1.0) / height,
    )


def _angle_delta_deg(value: float, reference: float) -> float:
    return (value - reference + 180.0) % 360.0 - 180.0


def _match_shape(
    shapes: list[dict],
    label: str,
    previous_geometry: tuple[float, float, float, float],
    expected_x: float | None,
    image_width: float,
    image_height: float,
) -> tuple[int, tuple[float, float, float, float], float] | None:
    best = None
    for index, shape in enumerate(shapes):
        if canonical_label(shape.get("label", "")) != label:
            continue
        bbox = shape_bbox(shape)
        if bbox is None:
            continue
        geometry = _normalized_geometry(
            bbox, float(image_width), float(image_height)
        )
        cx, cy, width, height = geometry
        prev_x, prev_y, prev_w, prev_h = previous_geometry
        dx = abs(cx - prev_x)
        dy = abs(cy - prev_y)
        size_delta = abs(math.log(width / prev_w)) + abs(math.log(height / prev_h))
        anchor_dx = abs(cx - expected_x) if expected_x is not None else dx
        score = dx * 2.4 + dy * 0.8 + size_delta * 0.12 + anchor_dx * 1.6
        if dx > 0.24 or dy > 0.25 or size_delta > 2.4:
            continue
        if expected_x is not None and anchor_dx > 0.3:
            continue
        if best is None or score < best[0]:
            best = score, index, geometry
    if best is None:
        return None
    score, index, geometry = best
    confidence = max(0.2, min(0.95, 1.0 - score))
    return index, geometry, confidence


def forward_sync_depth(
    request: ForwardSyncRequest,
    *,
    should_stop: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> ForwardSyncResult:
    should_stop = should_stop or (lambda: False)
    source_document = json.loads(request.source_path.read_text(encoding="utf-8"))
    source_shapes = source_document.get("shapes") or []
    if not 0 <= request.shape_index < len(source_shapes):
        raise IndexError("source shape index is out of range")
    source_shape = source_shapes[request.shape_index]
    source_bbox = shape_bbox(source_shape)
    if source_bbox is None:
        raise ValueError("source shape has no rectangle geometry")
    label = canonical_label(source_shape.get("label", ""))
    initial_geometry = _normalized_geometry(
        source_bbox,
        float(source_document.get("imageWidth", 1920) or 1920),
        float(source_document.get("imageHeight", 1200) or 1200),
    )
    source_time = parse_timestamp(request.source_path)
    before_entries, after_entries = _collect_part_entries(request, source_time)

    nav_cache: dict[Path, _SegmentNav] = {}
    updated = 0
    inspected = 0
    stopped_reason = "end_of_part"

    def _run_direction(
        entries: list[tuple[float, Path, Path]],
        direction_name: str,
    ) -> tuple[int, int, str]:
        direction_geometry = initial_geometry
        misses = 0
        direction_updated = 0
        direction_inspected = 0
        reason = f"end_of_{direction_name}"
        for timestamp, source_path, source_root in entries:
            if should_stop():
                return direction_updated, direction_inspected, "cancelled"
            direction_inspected += 1
            segment_dir = _segment_directory(
                source_path, source_root, request.dataset_root
            )
            try:
                nav = nav_cache.get(segment_dir)
                if nav is None:
                    nav = _load_nav(segment_dir)
                    nav_cache[segment_dir] = nav
                vehicle_lat, vehicle_lon, body_heading = nav.pose(timestamp)
            except (OSError, ValueError, KeyError):
                misses += 1
                if misses >= request.max_consecutive_misses:
                    return direction_updated, direction_inspected, "navigation_unavailable"
                continue

            camera_heading = (body_heading + CAMERA_HEADING_OFFSET_DEG) % 360.0
            target_bearing = bearing_deg(
                vehicle_lat,
                vehicle_lon,
                request.anchor.latitude,
                request.anchor.longitude,
            )
            angle_delta = _angle_delta_deg(target_bearing, camera_heading)
            expected_x = 0.5 + angle_delta / CAMERA_HFOV_DEG
            if not -0.35 <= expected_x <= 1.35:
                misses += 1
                if misses >= request.max_consecutive_misses:
                    return direction_updated, direction_inspected, "target_left_camera_view"
                continue

            relative = source_path.relative_to(source_root)
            output_path = request.depth_root / relative
            base_path = output_path if output_path.exists() else source_path
            try:
                document = json.loads(base_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                misses += 1
                continue
            match = _match_shape(
                document.get("shapes") or [],
                label,
                direction_geometry,
                expected_x,
                float(document.get("imageWidth", 1920) or 1920),
                float(document.get("imageHeight", 1200) or 1200),
            )
            if match is None:
                misses += 1
                if misses >= request.max_consecutive_misses:
                    return direction_updated, direction_inspected, "object_track_lost"
                continue

            shape_index, direction_geometry, confidence = match
            misses = 0
            shape = document["shapes"][shape_index]
            matched_bbox = shape_bbox(shape)
            attributes = dict(shape.get("attributes") or {})
            distance_m = horizontal_distance_m(
                vehicle_lat,
                vehicle_lon,
                request.anchor.latitude,
                request.anchor.longitude,
            )
            attributes.update(
                {
                    "depth_m": round(
                        max(0.0, distance_m + request.anchor.depth_bias_m), 1
                    ),
                    "depth_method": "manual_anchor_pose_bidirectional",
                    "depth_confidence": round(confidence, 3),
                    "depth_support_points": 0,
                    "depth_anchor_lat": request.anchor.latitude,
                    "depth_anchor_lon": request.anchor.longitude,
                    "depth_anchor_bias_m": round(request.anchor.depth_bias_m, 3),
                    "depth_anchor_source": request.anchor.source,
                    "depth_source_frame": request.source_frame,
                    "depth_sync_direction": direction_name,
                }
            )
            for candidate in document["shapes"]:
                candidate_bbox = shape_bbox(candidate)
                if (
                    matched_bbox is not None
                    and candidate_bbox is not None
                    and canonical_label(candidate.get("label", "")) == label
                    and max(
                        abs(candidate_bbox[index] - matched_bbox[index])
                        for index in range(4)
                    )
                    <= 1.0
                ):
                    candidate["attributes"] = dict(attributes)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
            temp_path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp_path.replace(output_path)
            direction_updated += 1
            total_updated = updated + direction_updated
            total_inspected = inspected + direction_inspected
            if progress is not None and (total_updated == 1 or total_updated % 25 == 0):
                progress(total_updated, total_inspected)
        return direction_updated, direction_inspected, reason

    for entries, direction_name in (
        (before_entries, "backward"),
        (after_entries, "forward"),
    ):
        direction_updated, direction_inspected, reason = _run_direction(
            entries, direction_name
        )
        updated += direction_updated
        inspected += direction_inspected
        stopped_reason = reason
        if reason == "cancelled":
            break

    return ForwardSyncResult(updated, inspected, stopped_reason)
