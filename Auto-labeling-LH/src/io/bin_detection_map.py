"""Parse radar-native detections from an LH UDP BIN into a world-map cache."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

PACKET_BYTES = 8624
PACKET_WORDS = 2156
WIRE_WORD = 5776 // 4
EARTH_EQ_M = 6378137.0
EARTH_POL_M = 6356752.3


def _local_to_wgs84(
    xyz: np.ndarray,
    ref_lat: float,
    ref_lon: float,
    ref_alt: float,
    ref_heading_deg: float,
    coordinate_mode: str,
) -> np.ndarray:
    """Convert local detections to ``[lat, lon, absolute_altitude]``."""
    points = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    x, y, z = points.T
    if coordinate_mode == "nwu":
        north, east = x, -y
    elif coordinate_mode == "body":
        heading = math.radians(ref_heading_deg)
        east = x * math.cos(heading) + y * math.sin(heading)
        north = -x * math.sin(heading) + y * math.cos(heading)
    elif coordinate_mode == "lh_body":
        # LH radar detection packets use x=right, y backward, z=up in the
        # checked 20260430/202605 samples. MAT point-cloud conversion uses
        # x=right, y=forward, z=up, so flip Y before rotating by heading.
        heading = math.radians(ref_heading_deg)
        y_forward = -y
        east = x * math.cos(heading) + y_forward * math.sin(heading)
        north = -x * math.sin(heading) + y_forward * math.cos(heading)
    elif coordinate_mode == "enu":
        east, north = x, y
    else:
        raise ValueError(f"unsupported coordinate mode: {coordinate_mode}")
    lat = ref_lat + north / EARTH_POL_M * 180.0 / math.pi
    lon = (
        ref_lon
        + east
        / (EARTH_EQ_M * max(math.cos(math.radians(ref_lat)), 1e-6))
        * 180.0
        / math.pi
    )
    return np.column_stack([lat, lon, ref_alt + z]).astype(np.float64)


def _packet_snapshot(words: np.ndarray, packet_index: int) -> dict | None:
    wire_u = words[WIRE_WORD:]
    wire_f = wire_u.view("<f4")
    n_hv = min(int(wire_u[6]), 60)
    n_seg = min(int(wire_u[7]), 60)
    n_isolated = min(int(wire_u[8]), 40)
    n_dense = min(int(wire_u[9]), 6)
    if n_seg == 0 and n_isolated == 0 and n_dense == 0:
        return None

    dense_counts = np.minimum(wire_u[556:562].astype(np.int32), 8)
    dense_vertices = []
    dense_x = wire_f[562:610].reshape(6, 8)
    dense_y = wire_f[610:658].reshape(6, 8)
    dense_z = wire_f[658:706].reshape(6, 8)
    for index in range(n_dense):
        count = int(dense_counts[index])
        dense_vertices.append(np.column_stack([
            dense_x[index, :count],
            dense_y[index, :count],
            dense_z[index, :count],
        ]).astype(np.float32))

    return {
        "packet_index": int(packet_index),
        "net_send_frame": int(words[3]),
        "timestamp_raw": int(words[11]),
        "ref_lon": float(wire_f[2]),
        "ref_lat": float(wire_f[3]),
        "ref_heading_deg": float(wire_f[4]),
        "ref_alt_m": float(wire_f[5]),
        "n_hv": n_hv,
        "hv_segment_info": wire_u[16:16 + n_seg].copy(),
        "hv_segments_xyz": wire_f[76:76 + n_seg * 6].reshape(
            n_seg, 2, 3
        ).copy(),
        "isolated_xyz": wire_f[436:436 + n_isolated * 3].reshape(
            n_isolated, 3
        ).copy(),
        "dense_vertices_xyz": dense_vertices,
    }


def load_bin_detection_snapshots(bin_path: Path) -> list[dict]:
    """Return one radar detection snapshot per antenna-frame start."""
    bin_path = Path(bin_path)
    packet_count = bin_path.stat().st_size // PACKET_BYTES
    words = np.memmap(
        bin_path, dtype="<u4", mode="r", shape=(packet_count, PACKET_WORDS)
    )
    starts = np.flatnonzero(words[:, 6] == 1)
    snapshots = []
    for packet_index in starts:
        snapshot = _packet_snapshot(words[packet_index], int(packet_index))
        if snapshot is not None:
            snapshots.append(snapshot)
    return snapshots


def build_bin_detection_world_map(
    bin_path: Path,
    *,
    coordinate_mode: str = "nwu",
) -> dict[str, np.ndarray]:
    """Build world-coordinate primitives while retaining snapshot provenance."""
    snapshots = load_bin_detection_snapshots(bin_path)
    isolated_rows = []
    line_rows = []
    dense_rows = []
    reference_altitudes = []
    for snapshot_index, snapshot in enumerate(snapshots):
        reference_altitudes.append(float(snapshot["ref_alt_m"]))
        common = (
            snapshot["ref_lat"],
            snapshot["ref_lon"],
            snapshot["ref_alt_m"],
            snapshot["ref_heading_deg"],
            coordinate_mode,
        )
        isolated = snapshot["isolated_xyz"]
        if len(isolated):
            world = _local_to_wgs84(isolated, *common)
            isolated_rows.append(np.column_stack([
                world,
                np.full(len(world), snapshot_index),
                np.full(len(world), snapshot["packet_index"]),
            ]))
        segments = snapshot["hv_segments_xyz"]
        if len(segments):
            endpoints = _local_to_wgs84(segments.reshape(-1, 3), *common)
            line_rows.append(np.column_stack([
                endpoints.reshape(-1, 6),
                snapshot["hv_segment_info"].astype(np.float64),
                np.full(len(segments), snapshot_index),
                np.full(len(segments), snapshot["packet_index"]),
            ]))
        for dense_index, vertices in enumerate(snapshot["dense_vertices_xyz"]):
            if not len(vertices):
                continue
            world = _local_to_wgs84(vertices, *common)
            dense_rows.append(np.column_stack([
                world,
                np.full(len(world), snapshot_index),
                np.full(len(world), dense_index),
                np.full(len(world), snapshot["packet_index"]),
            ]))

    return {
        "isolated": (
            np.concatenate(isolated_rows).astype(np.float64)
            if isolated_rows else np.empty((0, 5), dtype=np.float64)
        ),
        "powerline_segments": (
            np.concatenate(line_rows).astype(np.float64)
            if line_rows else np.empty((0, 9), dtype=np.float64)
        ),
        "dense_vertices": (
            np.concatenate(dense_rows).astype(np.float64)
            if dense_rows else np.empty((0, 6), dtype=np.float64)
        ),
        "coordinate_mode": np.asarray(coordinate_mode),
        "snapshot_count": np.asarray(len(snapshots), dtype=np.int32),
        "reference_altitude_valid": np.asarray(
            any(abs(value) > 1e-3 for value in reference_altitudes),
            dtype=np.bool_,
        ),
    }


def load_or_build_bin_detection_world_map(
    bin_path: Path,
    cache_dir: Path,
    *,
    coordinate_mode: str = "nwu",
) -> dict[str, np.ndarray]:
    """Load a signature-checked NPZ cache or parse the BIN."""
    bin_path = Path(bin_path)
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    stat = bin_path.stat()
    signature = f"v2:{stat.st_size}:{stat.st_mtime_ns}:{coordinate_mode}"
    key = hashlib.sha1(str(bin_path.resolve()).encode("utf-8")).hexdigest()[:12]
    cache_path = cache_dir / f"{bin_path.stem}_{key}_{coordinate_mode}.npz"
    if cache_path.exists():
        with np.load(cache_path, allow_pickle=False) as cached:
            if str(cached["signature"].item()) == signature:
                return {name: cached[name] for name in cached.files
                        if name != "signature"}
    result = build_bin_detection_world_map(
        bin_path, coordinate_mode=coordinate_mode
    )
    np.savez_compressed(cache_path, signature=signature, **result)
    return result
