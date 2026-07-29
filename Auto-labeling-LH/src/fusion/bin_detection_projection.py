"""Prepare capture-wide BIN detections for camera projection."""

from __future__ import annotations

import math

import numpy as np

EARTH_EQ_M = 6378137.0
EARTH_POL_M = 6356752.3

# Pseudo intensity values keep the existing point overlay colour mapping useful.
KIND_DENSE = 1.0
KIND_ISOLATED = 2.0
KIND_POWERLINE = 3.0


def _interpolate_segment(start: np.ndarray, end: np.ndarray, spacing_m: float) -> np.ndarray:
    """Interpolate a WGS-84 segment using its local horizontal length."""
    lat0 = math.radians(float((start[0] + end[0]) * 0.5))
    east = (end[1] - start[1]) * math.pi / 180.0 * EARTH_EQ_M * math.cos(lat0)
    north = (end[0] - start[0]) * math.pi / 180.0 * EARTH_POL_M
    up = end[2] - start[2]
    length = float(math.sqrt(east * east + north * north + up * up))
    count = max(2, min(256, int(math.ceil(length / max(spacing_m, 1.0))) + 1))
    t = np.linspace(0.0, 1.0, count, dtype=np.float64)[:, None]
    return start[None, :] * (1.0 - t) + end[None, :] * t


def sample_bin_detection_map(
    detection_map: dict,
    *,
    line_spacing_m: float = 20.0,
    dense_spacing_m: float = 20.0,
) -> np.ndarray:
    """Return ``[lat, lon, altitude, intensity, kind]`` projection samples."""
    chunks: list[np.ndarray] = []

    segments = np.asarray(
        detection_map.get("powerline_segments", np.empty((0, 9))),
        dtype=np.float64,
    )
    for row in segments:
        points = _interpolate_segment(row[:3], row[3:6], line_spacing_m)
        chunks.append(
            np.column_stack(
                [
                    points,
                    np.full(len(points), 35.0),
                    np.full(len(points), KIND_POWERLINE),
                ]
            )
        )

    isolated = np.asarray(
        detection_map.get("isolated", np.empty((0, 5))), dtype=np.float64
    )
    if len(isolated):
        chunks.append(
            np.column_stack(
                [
                    isolated[:, :3],
                    np.full(len(isolated), 25.0),
                    np.full(len(isolated), KIND_ISOLATED),
                ]
            )
        )

    dense = np.asarray(
        detection_map.get("dense_vertices", np.empty((0, 6))), dtype=np.float64
    )
    if len(dense):
        # Columns 3/4 identify snapshot and region. Preserve polygon boundaries.
        for key in np.unique(dense[:, 3:5], axis=0):
            vertices = dense[np.all(dense[:, 3:5] == key, axis=1), :3]
            if not len(vertices):
                continue
            samples = []
            if len(vertices) == 1:
                samples.append(vertices)
            else:
                for index in range(len(vertices)):
                    samples.append(
                        _interpolate_segment(
                            vertices[index],
                            vertices[(index + 1) % len(vertices)],
                            dense_spacing_m,
                        )
                    )
            points = np.concatenate(samples)
            chunks.append(
                np.column_stack(
                    [
                        points,
                        np.full(len(points), 15.0),
                        np.full(len(points), KIND_DENSE),
                    ]
                )
            )

    if not chunks:
        return np.empty((0, 5), dtype=np.float64)
    result = np.concatenate(chunks)
    valid = np.all(np.isfinite(result[:, :4]), axis=1)
    return result[valid]


def sample_bin_detection_targets(
    detection_map: dict,
    *,
    line_spacing_m: float = 20.0,
) -> tuple[np.ndarray, list[dict]]:
    """Return display points and target provenance for the map view."""
    point_chunks: list[np.ndarray] = []
    metadata: list[dict] = []

    segments = np.asarray(
        detection_map.get("powerline_segments", np.empty((0, 9))),
        dtype=np.float64,
    )
    for target_id, row in enumerate(segments):
        points = _interpolate_segment(row[:3], row[3:6], line_spacing_m)
        point_chunks.append(
            np.column_stack([points, np.full(len(points), 35.0)])
        )
        metadata.extend(
            {
                "target_type_text": "\u9ad8\u538b\u7ebf\u6bb5",
                "target_id": int(target_id),
                "segment_info": int(row[6]),
                "snapshot_index": int(row[7]),
                "packet_index": int(row[8]),
            }
            for _ in range(len(points))
        )

    isolated = np.asarray(
        detection_map.get("isolated", np.empty((0, 5))),
        dtype=np.float64,
    )
    if len(isolated):
        point_chunks.append(
            np.column_stack([isolated[:, :3], np.full(len(isolated), 25.0)])
        )
        metadata.extend(
            {
                "target_type_text": "\u5b64\u7acb\u76ee\u6807",
                "target_id": int(target_id),
                "snapshot_index": int(row[3]),
                "packet_index": int(row[4]),
            }
            for target_id, row in enumerate(isolated)
        )

    dense = np.asarray(
        detection_map.get("dense_vertices", np.empty((0, 6))),
        dtype=np.float64,
    )
    if len(dense):
        point_chunks.append(
            np.column_stack([dense[:, :3], np.full(len(dense), 15.0)])
        )
        metadata.extend(
            {
                "target_type_text": "\u5bc6\u96c6\u533a\u57df",
                "target_id": int(row[4]),
                "snapshot_index": int(row[3]),
                "packet_index": int(row[5]),
            }
            for row in dense
        )

    if not point_chunks:
        return np.empty((0, 4), dtype=np.float64), []
    points = np.concatenate(point_chunks)
    valid = np.all(np.isfinite(points), axis=1)
    if valid.all():
        return points, metadata
    keep = np.flatnonzero(valid)
    return points[keep], [metadata[index] for index in keep]


def sample_bin_detection_target_objects(
    detection_map: dict,
) -> tuple[np.ndarray, list[dict]]:
    """Return one or few representative points per native BIN target object.

    This is meant for inspection displays.  It keeps every native detection
    object but does not interpolate long line segments or dense-region edges,
    so the map view does not create visual target points that were not present
    as object primitives in the BIN interface.
    """
    point_chunks: list[np.ndarray] = []
    metadata: list[dict] = []

    segments = np.asarray(
        detection_map.get("powerline_segments", np.empty((0, 9))),
        dtype=np.float64,
    )
    for target_id, row in enumerate(segments):
        start = row[:3]
        end = row[3:6]
        midpoint = (start + end) * 0.5
        points = np.vstack([midpoint, start, end])
        labels = ("center", "start", "end")
        point_chunks.append(np.column_stack([points, np.full(3, 35.0)]))
        metadata.extend(
            {
                "target_type_text": "高压线段",
                "target_id": int(target_id),
                "target_point": labels[index],
                "segment_info": int(row[6]),
                "snapshot_index": int(row[7]),
                "packet_index": int(row[8]),
            }
            for index in range(3)
        )

    isolated = np.asarray(
        detection_map.get("isolated", np.empty((0, 5))),
        dtype=np.float64,
    )
    if len(isolated):
        point_chunks.append(
            np.column_stack([isolated[:, :3], np.full(len(isolated), 25.0)])
        )
        metadata.extend(
            {
                "target_type_text": "孤立目标",
                "target_id": int(target_id),
                "target_point": "point",
                "snapshot_index": int(row[3]),
                "packet_index": int(row[4]),
            }
            for target_id, row in enumerate(isolated)
        )

    dense = np.asarray(
        detection_map.get("dense_vertices", np.empty((0, 6))),
        dtype=np.float64,
    )
    if len(dense):
        for key in np.unique(dense[:, 3:5], axis=0):
            rows = dense[np.all(dense[:, 3:5] == key, axis=1)]
            if not len(rows):
                continue
            centroid = np.median(rows[:, :3], axis=0)
            point_chunks.append(
                np.column_stack([centroid[None, :], np.full(1, 15.0)])
            )
            metadata.append(
                {
                    "target_type_text": "密集区域",
                    "target_id": int(key[1]),
                    "target_point": "center",
                    "snapshot_index": int(key[0]),
                    "packet_index": int(rows[0, 5]),
                }
            )

    if not point_chunks:
        return np.empty((0, 4), dtype=np.float64), []
    points = np.concatenate(point_chunks)
    valid = np.all(np.isfinite(points), axis=1)
    if valid.all():
        return points, metadata
    keep = np.flatnonzero(valid)
    return points[keep], [metadata[index] for index in keep]


def detection_map_anchor_samples(detection_map: dict) -> np.ndarray:
    """Return one world-coordinate anchor per detected radar obstacle."""
    chunks: list[np.ndarray] = []

    segments = np.asarray(
        detection_map.get("powerline_segments", np.empty((0, 9))),
        dtype=np.float64,
    )
    if len(segments):
        midpoint = (segments[:, :3] + segments[:, 3:6]) * 0.5
        chunks.append(
            np.column_stack(
                [
                    midpoint,
                    np.full(len(midpoint), 35.0),
                    np.full(len(midpoint), KIND_POWERLINE),
                ]
            )
        )

    isolated = np.asarray(
        detection_map.get("isolated", np.empty((0, 5))), dtype=np.float64
    )
    if len(isolated):
        chunks.append(
            np.column_stack(
                [
                    isolated[:, :3],
                    np.full(len(isolated), 25.0),
                    np.full(len(isolated), KIND_ISOLATED),
                ]
            )
        )

    dense = np.asarray(
        detection_map.get("dense_vertices", np.empty((0, 6))), dtype=np.float64
    )
    if len(dense):
        centroids = []
        for key in np.unique(dense[:, 3:5], axis=0):
            vertices = dense[np.all(dense[:, 3:5] == key, axis=1), :3]
            if len(vertices):
                centroids.append(np.median(vertices, axis=0))
        if centroids:
            centroids_array = np.asarray(centroids, dtype=np.float64)
            chunks.append(
                np.column_stack(
                    [
                        centroids_array,
                        np.full(len(centroids_array), 15.0),
                        np.full(len(centroids_array), KIND_DENSE),
                    ]
                )
            )

    if not chunks:
        return np.empty((0, 5), dtype=np.float64)
    result = np.concatenate(chunks)
    return result[np.all(np.isfinite(result), axis=1)]


def filter_detection_map_by_packet_range(
    detection_map: dict,
    packet_start: int,
    packet_end: int,
) -> dict:
    """Keep only BIN detections whose source packet belongs to one MAT."""
    result = dict(detection_map)
    column_by_name = {
        "isolated": 4,
        "powerline_segments": 8,
        "dense_vertices": 5,
    }
    for name, packet_column in column_by_name.items():
        rows = np.asarray(detection_map.get(name, np.empty((0, 0))))
        if rows.ndim != 2 or not len(rows) or rows.shape[1] <= packet_column:
            result[name] = rows[:0]
            continue
        packets = rows[:, packet_column]
        result[name] = rows[
            (packets >= int(packet_start)) & (packets <= int(packet_end))
        ]
    return result


def world_samples_to_body(
    samples: np.ndarray,
    *,
    gps_lat: float,
    gps_lon: float,
    gps_alt: float | None,
    gps_heading_deg: float,
    heading_offset_deg: float = -90.0,
    min_distance_m: float = 400.0,
    max_distance_m: float = 4000.0,
    half_fov_deg: float = 12.0,
    altitude_is_relative: bool = False,
    max_points: int = 6000,
) -> tuple[np.ndarray, np.ndarray]:
    """Convert world samples to body ``[right, forward, up, intensity]``."""
    points = np.asarray(samples, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 4 or not len(points):
        return np.empty((0, 4), dtype=np.float32), np.empty((0, 5), dtype=np.float64)

    lat = points[:, 0]
    lon = points[:, 1]
    altitude = points[:, 2]
    east = (
        (lon - float(gps_lon))
        * math.pi
        / 180.0
        * EARTH_EQ_M
        * math.cos(math.radians(float(gps_lat)))
    )
    north = (lat - float(gps_lat)) * math.pi / 180.0 * EARTH_POL_M

    heading = math.radians(float(gps_heading_deg) + float(heading_offset_deg))
    cos_h, sin_h = math.cos(heading), math.sin(heading)
    right = east * cos_h - north * sin_h
    forward = east * sin_h + north * cos_h
    if altitude_is_relative or gps_alt is None or not math.isfinite(float(gps_alt)):
        up = altitude
    else:
        up = altitude - float(gps_alt)

    distance = np.hypot(right, forward)
    azimuth = np.degrees(np.arctan2(right, forward))
    mask = (
        (forward > 0.0)
        & (distance >= float(min_distance_m))
        & (distance <= float(max_distance_m))
        & (np.abs(azimuth) <= float(half_fov_deg))
        & (altitude >= 0.0)
        & np.isfinite(up)
    )
    source = points[mask]
    body = np.column_stack([right[mask], forward[mask], up[mask], source[:, 3]])
    if max_points > 0 and len(body) > max_points:
        # Keep sparse isolated/dense targets, then evenly sample the abundant
        # powerline geometry with the remaining display budget.
        rare = np.flatnonzero(source[:, 4] != KIND_POWERLINE)
        if len(rare) >= max_points:
            keep = rare[
                np.linspace(0, len(rare) - 1, max_points, dtype=np.int64)
            ]
        else:
            common = np.flatnonzero(source[:, 4] == KIND_POWERLINE)
            budget = max_points - len(rare)
            selected_common = common[
                np.linspace(0, len(common) - 1, budget, dtype=np.int64)
            ]
            keep = np.sort(np.concatenate([rare, selected_common]))
        body = body[keep]
        source = source[keep]
    return body.astype(np.float32), source


def filter_body_points_by_camera_frustum(
    body_points: np.ndarray,
    source_points: np.ndarray,
    *,
    body_to_camera: np.ndarray,
    fx: float,
    fy: float,
    cx: float,
    cy: float,
    image_width: int,
    image_height: int,
    margin_px: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Keep only points inside the current camera's true pinhole frustum."""
    body = np.asarray(body_points, dtype=np.float64)
    source = np.asarray(source_points)
    if body.ndim != 2 or body.shape[1] < 3 or not len(body):
        return body_points[:0], source_points[:0]
    transform = np.asarray(body_to_camera, dtype=np.float64).reshape(4, 4)
    homogeneous = np.column_stack([body[:, :3], np.ones(len(body))])
    camera = (transform @ homogeneous.T).T[:, :3]
    depth = camera[:, 2]
    valid_depth = depth > 0.1
    safe_depth = np.where(valid_depth, depth, 1.0)
    pixel_x = float(fx) * camera[:, 0] / safe_depth + float(cx)
    pixel_y = float(fy) * camera[:, 1] / safe_depth + float(cy)
    mask = (
        valid_depth
        & (pixel_x >= -float(margin_px))
        & (pixel_x < float(image_width) + float(margin_px))
        & (pixel_y >= -float(margin_px))
        & (pixel_y < float(image_height) + float(margin_px))
    )
    return body_points[mask], source_points[mask]


def match_world_cloud_to_detection_samples(
    cloud_points: np.ndarray,
    detection_samples: np.ndarray,
    *,
    max_horizontal_distance_m: float = 60.0,
    max_vertical_distance_m: float | None = None,
    align_vertical_offset: bool = False,
) -> np.ndarray:
    """Return cloud rows close to a BIN target in horizontal and height axes."""
    cloud = np.asarray(cloud_points, dtype=np.float64)
    targets = np.asarray(detection_samples, dtype=np.float64)
    if not len(cloud) or not len(targets):
        return np.zeros(len(cloud), dtype=bool)

    lat0 = float(np.median(cloud[:, 0]))
    cos_lat = math.cos(math.radians(lat0))

    def to_horizontal(points: np.ndarray) -> np.ndarray:
        east = (
            (points[:, 1] - float(np.median(cloud[:, 1])))
            * math.pi
            / 180.0
            * EARTH_EQ_M
            * cos_lat
        )
        north = (
            (points[:, 0] - lat0)
            * math.pi
            / 180.0
            * EARTH_POL_M
        )
        return np.column_stack([east, north])

    cloud_xy = to_horizontal(cloud)
    target_xy = to_horizontal(targets)
    try:
        from scipy.spatial import cKDTree

        distances, nearest = cKDTree(target_xy).query(cloud_xy, k=1)
    except Exception:
        # Small fallback for environments without scipy.spatial.
        distances = np.full(len(cloud_xy), np.inf)
        nearest = np.full(len(cloud_xy), -1, dtype=np.int64)
        chunk = 512
        for start in range(0, len(cloud_xy), chunk):
            delta = cloud_xy[start : start + chunk, None, :] - target_xy[None, :, :]
            dist2 = np.sum(delta * delta, axis=2)
            nearest_chunk = np.argmin(dist2, axis=1)
            nearest[start : start + chunk] = nearest_chunk
            distances[start : start + chunk] = np.sqrt(
                dist2[np.arange(len(nearest_chunk)), nearest_chunk]
            )
    matched = distances <= float(max_horizontal_distance_m)
    if max_vertical_distance_m is not None and cloud.shape[1] >= 3 and targets.shape[1] >= 3:
        valid_nearest = nearest >= 0
        vertical_offset = 0.0
        if align_vertical_offset:
            offset_rows = valid_nearest & matched
            if offset_rows.any():
                vertical_offset = float(np.median(
                    cloud[offset_rows, 2]
                    - targets[nearest[offset_rows], 2]
                ))
        vertical = np.full(len(cloud), np.inf, dtype=np.float64)
        vertical[valid_nearest] = np.abs(
            cloud[valid_nearest, 2]
            - (targets[nearest[valid_nearest], 2] + vertical_offset)
        )
        matched &= vertical <= float(max_vertical_distance_m)
    return matched
