#!/usr/bin/env python3
"""Inspect and export LH millimeter-wave radar BIN recordings."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy.io import savemat


PACKET_SIZE = 8624
WORDS_PER_PACKET = PACKET_SIZE // 4
HEADER_WORDS = 64
ECHO_SAMPLES = 668
TERRAIN_OFFSET_WORDS = 1408
DETECTION_OFFSET_WORDS = 1444

HEADER_DTYPE = np.dtype(
    [
        ("sync_head_1", "<u4"),
        ("sync_head_2", "<u4"),
        ("low_power_frame", "<u4"),
        ("net_send_frame", "<u4"),
        ("data_dwords", "<u4"),
        ("working_mode", "<u4"),
        ("antenna_frame_start", "<u4"),
        ("antenna_frame_end", "<u4"),
        # The DOCX says Uint32, but real recordings store IEEE-754 (4.0 km).
        ("range_km", "<f4"),
        ("valid_sample_count", "<u4"),
        ("timestamp_year", "<u2"),
        ("timestamp_month", "u1"),
        ("timestamp_day", "u1"),
        ("timestamp_hmsm", "<u4"),
        ("plane_longitude_deg", "<f4"),
        ("plane_latitude_deg", "<f4"),
        ("true_heading_deg", "<f4"),
        ("gps_altitude_m", "<f4"),
        ("ground_speed_mps", "<f4"),
        ("east_velocity_mps", "<f4"),
        ("north_velocity_mps", "<f4"),
        ("up_velocity_mps", "<f4"),
        ("antenna_azimuth_deg", "<f4"),
        ("antenna_elevation_deg", "<f4"),
        ("scan_speed_dps", "<f4"),
        ("scan_range_deg", "<f4"),
        ("scan_direction", "<u4"),
        ("install_azimuth_error_deg", "<f4"),
        ("install_elevation_error_deg", "<f4"),
        ("install_roll_error_deg", "<f4"),
        ("backup", "<u4", (34,)),
        ("sync_tail_1", "<u4"),
        ("sync_tail_2", "<u4"),
    ],
    align=False,
)
assert HEADER_DTYPE.itemsize == 256, HEADER_DTYPE.itemsize


def _json_default(value: Any) -> Any:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Unsupported JSON type: {type(value)!r}")


def _local_to_wgs84(
    x_m: float,
    y_m: float,
    z_m: float,
    ref_lon: float,
    ref_lat: float,
    ref_alt: float,
    ref_heading_deg: float,
    mode: str,
) -> tuple[float | None, float | None, float | None]:
    if mode == "local" or not (-180 <= ref_lon <= 180 and -90 <= ref_lat <= 90):
        return None, None, None

    if mode == "nwu":
        north, east = x_m, -y_m
    elif mode == "body":
        heading = math.radians(ref_heading_deg)
        east = x_m * math.cos(heading) + y_m * math.sin(heading)
        north = -x_m * math.sin(heading) + y_m * math.cos(heading)
    else:
        east, north = x_m, y_m

    earth_radius = 6378137.0
    lat = ref_lat + math.degrees(north / earth_radius)
    cos_lat = max(abs(math.cos(math.radians(ref_lat))), 1e-8)
    lon = ref_lon + math.degrees(east / (earth_radius * cos_lat))
    alt = ref_alt + z_m if math.isfinite(ref_alt) else None
    return lat, lon, alt


class BinReader:
    def __init__(self, path: Path, max_packets: int | None = None) -> None:
        self.path = path
        size = path.stat().st_size
        self.trailing_bytes = size % PACKET_SIZE
        available = size // PACKET_SIZE
        self.packet_count = min(available, max_packets) if max_packets else available
        self.words = np.memmap(
            path, dtype="<u4", mode="r", shape=(available, WORDS_PER_PACKET)
        )[: self.packet_count]
        self.headers = self.words[:, :HEADER_WORDS].view(HEADER_DTYPE).reshape(-1)

    def ant_frame_ranges(self, max_frames: int | None = None) -> list[tuple[int, int]]:
        starts = np.flatnonzero(self.headers["antenna_frame_start"] != 0).tolist()
        if not starts and self.packet_count:
            starts = [0]
        if max_frames:
            starts = starts[:max_frames]
        ranges: list[tuple[int, int]] = []
        for index, start in enumerate(starts):
            if index + 1 < len(starts):
                end = starts[index + 1]
            else:
                following = np.flatnonzero(
                    self.headers["antenna_frame_start"][start + 1 :] != 0
                )
                end = start + 1 + int(following[0]) if following.size else self.packet_count
            ranges.append((start, end))
        return ranges

    def echo(self, packet_slice: slice | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        words = self.words[packet_slice]
        sum_echo = words[:, 66 : 66 + ECHO_SAMPLES].view("<f4")
        diff_echo = words[:, 738 : 738 + ECHO_SAMPLES].view("<f4")
        return sum_echo, diff_echo

    def terrain(self, packet_index: int) -> list[dict[str, Any]]:
        words = self.words[packet_index]
        base = TERRAIN_OFFSET_WORDS
        count = min(int(words[base + 2]), 5)
        values = words[base + 4 : base + 34].view("<f4").reshape(5, 6)
        rows = []
        for index in range(count):
            az, el, el_err, distance, power, target_type = values[index]
            rows.append(
                {
                    "terrain_index": index,
                    "azimuth_deg": float(az),
                    "elevation_deg": float(el),
                    "elevation_error_deg": float(el_err),
                    "range_m": float(distance),
                    "power": float(power),
                    "type": float(target_type),
                }
            )
        return rows

    def detection(self, packet_index: int) -> dict[str, Any]:
        words = self.words[packet_index]
        base = DETECTION_OFFSET_WORDS
        ref = words[base + 2 : base + 6].view("<f4")
        counts = words[base + 6 : base + 10]
        n_hv = min(int(counts[0]), 60)
        n_seg = min(int(counts[1]), 60)
        n_isolated = min(int(counts[2]), 40)
        n_dense = min(int(counts[3]), 6)
        leading_backup = words[base + 10 : base + 16].copy()
        segment_info = words[base + 16 : base + 76].copy()
        segments = words[base + 76 : base + 436].view("<f4").reshape(60, 6).copy()
        isolated = words[base + 436 : base + 556].view("<f4").reshape(40, 3).copy()
        vertex_counts = words[base + 556 : base + 562].copy()
        dense_x = words[base + 562 : base + 610].view("<f4").reshape(6, 8).copy()
        dense_y = words[base + 610 : base + 658].view("<f4").reshape(6, 8).copy()
        dense_z = words[base + 658 : base + 706].view("<f4").reshape(6, 8).copy()
        trailing_backup = words[base + 706 : base + 710].copy()
        return {
            "sync_start": [int(words[base]), int(words[base + 1])],
            "ref_lon": float(ref[0]),
            "ref_lat": float(ref[1]),
            "ref_heading_deg": float(ref[2]),
            "ref_alt_m": float(ref[3]),
            "n_high_voltage": n_hv,
            "n_powerline_segments": n_seg,
            "n_isolated_objects": n_isolated,
            "n_dense_regions": n_dense,
            "leading_backup": leading_backup,
            "high_voltage_info": segment_info[:n_seg],
            "powerline_segments_xyz": segments[:n_seg],
            "isolated_objects_xyz": isolated[:n_isolated],
            "dense_vertex_counts": vertex_counts[:n_dense],
            "dense_x": dense_x[:n_dense],
            "dense_y": dense_y[:n_dense],
            "dense_z": dense_z[:n_dense],
            "trailing_backup": trailing_backup,
            "sync_end": [int(words[base + 710]), int(words[base + 711])],
        }


def _header_dict(header: np.void, packet_index: int) -> dict[str, Any]:
    row: dict[str, Any] = {"packet_index": packet_index}
    for name in HEADER_DTYPE.names or ():
        if name == "backup":
            for index, value in enumerate(header[name]):
                row[f"backup_{index:02d}"] = int(value)
        else:
            value = header[name]
            row[name] = value.item() if isinstance(value, np.generic) else value
    return row


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def export_headers(reader: BinReader, output: Path) -> int:
    fields = ["packet_index"]
    for name in HEADER_DTYPE.names or ():
        if name == "backup":
            fields.extend(f"backup_{index:02d}" for index in range(34))
        else:
            fields.append(name)
    return write_csv(
        output / "packet_headers.csv",
        (_header_dict(header, index) for index, header in enumerate(reader.headers)),
        fields,
    )


def export_terrain(reader: BinReader, output: Path) -> int:
    fields = [
        "packet_index",
        "net_send_frame",
        "timestamp_hmsm",
        "terrain_index",
        "azimuth_deg",
        "elevation_deg",
        "elevation_error_deg",
        "range_m",
        "power",
        "type",
    ]

    def rows() -> Iterable[dict[str, Any]]:
        for packet_index, header in enumerate(reader.headers):
            common = {
                "packet_index": packet_index,
                "net_send_frame": int(header["net_send_frame"]),
                "timestamp_hmsm": int(header["timestamp_hmsm"]),
            }
            for item in reader.terrain(packet_index):
                yield {**common, **item}

    return write_csv(output / "terrain_targets.csv", rows(), fields)


def _detection_objects(
    detection: dict[str, Any],
    common: dict[str, Any],
    coordinate_mode: str,
) -> Iterable[dict[str, Any]]:
    ref = (
        detection["ref_lon"],
        detection["ref_lat"],
        detection["ref_alt_m"],
        detection["ref_heading_deg"],
    )

    def make_row(
        category: str, object_index: int, points: np.ndarray, details: dict[str, Any]
    ) -> dict[str, Any]:
        points = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        center = np.mean(points, axis=0)
        minimum = np.min(points, axis=0)
        maximum = np.max(points, axis=0)
        world = _local_to_wgs84(
            float(center[0]),
            float(center[1]),
            float(center[2]),
            ref[0],
            ref[1],
            ref[2],
            ref[3],
            coordinate_mode,
        )
        return {
            **common,
            "category": category,
            "object_index": object_index,
            "position_x_m": center[0],
            "position_y_m": center[1],
            "position_z_m": center[2],
            "bbox_min_x_m": minimum[0],
            "bbox_min_y_m": minimum[1],
            "bbox_min_z_m": minimum[2],
            "bbox_max_x_m": maximum[0],
            "bbox_max_y_m": maximum[1],
            "bbox_max_z_m": maximum[2],
            "world_latitude_deg": world[0],
            "world_longitude_deg": world[1],
            "world_altitude_m": world[2],
            "details_json": json.dumps(details, ensure_ascii=False, default=_json_default),
        }

    for index, segment in enumerate(detection["powerline_segments_xyz"]):
        points = np.asarray(segment).reshape(2, 3)
        info = (
            int(detection["high_voltage_info"][index])
            if index < len(detection["high_voltage_info"])
            else None
        )
        decoded_info = None
        if info is not None:
            decoded_info = {
                "segment_id": info & 0xFFFF,
                "endpoint_flag": (info >> 16) & 0xFF,
                "segment_count": (info >> 24) & 0xFF,
            }
        yield make_row(
            "powerline_segment",
            index,
            points,
            {
                "segment_info_raw": info,
                "segment_info": decoded_info,
                "start_xyz": points[0],
                "end_xyz": points[1],
            },
        )

    for index, point in enumerate(detection["isolated_objects_xyz"]):
        yield make_row(
            "isolated_object", index, np.asarray(point), {"point_xyz": point}
        )

    for index in range(detection["n_dense_regions"]):
        count = min(int(detection["dense_vertex_counts"][index]), 8)
        if count <= 0:
            continue
        points = np.column_stack(
            (
                detection["dense_x"][index, :count],
                detection["dense_y"][index, :count],
                detection["dense_z"][index, :count],
            )
        )
        yield make_row(
            "dense_region",
            index,
            points,
            {"vertex_count": count, "vertices_xyz": points},
        )


DETECTION_FIELDS = [
    "ant_frame_index",
    "packet_index",
    "net_send_frame",
    "timestamp_hmsm",
    "category",
    "object_index",
    "ref_longitude_deg",
    "ref_latitude_deg",
    "ref_heading_deg",
    "ref_altitude_m",
    "position_x_m",
    "position_y_m",
    "position_z_m",
    "bbox_min_x_m",
    "bbox_min_y_m",
    "bbox_min_z_m",
    "bbox_max_x_m",
    "bbox_max_y_m",
    "bbox_max_z_m",
    "world_latitude_deg",
    "world_longitude_deg",
    "world_altitude_m",
    "details_json",
]


def export_detections(
    reader: BinReader,
    output: Path,
    coordinate_mode: str,
    max_frames: int | None,
) -> tuple[int, int]:
    frames = reader.ant_frame_ranges(max_frames)
    json_path = output / "detections.json"
    csv_path = output / "detections.csv"
    summary_fields = [
        "ant_frame_index",
        "packet_index",
        "net_send_frame",
        "timestamp_hmsm",
        "ref_longitude_deg",
        "ref_latitude_deg",
        "ref_heading_deg",
        "ref_altitude_m",
        "n_high_voltage",
        "n_powerline_segments",
        "n_isolated_objects",
        "n_dense_regions",
    ]
    frame_rows: list[dict[str, Any]] = []
    objects: list[dict[str, Any]] = []
    for ant_index, (start, _) in enumerate(frames):
        header = reader.headers[start]
        detection = reader.detection(start)
        common = {
            "ant_frame_index": ant_index,
            "packet_index": start,
            "net_send_frame": int(header["net_send_frame"]),
            "timestamp_hmsm": int(header["timestamp_hmsm"]),
            "ref_longitude_deg": detection["ref_lon"],
            "ref_latitude_deg": detection["ref_lat"],
            "ref_heading_deg": detection["ref_heading_deg"],
            "ref_altitude_m": detection["ref_alt_m"],
        }
        frame_rows.append(
            {
                **common,
                "n_high_voltage": detection["n_high_voltage"],
                "n_powerline_segments": detection["n_powerline_segments"],
                "n_isolated_objects": detection["n_isolated_objects"],
                "n_dense_regions": detection["n_dense_regions"],
            }
        )
        objects.extend(_detection_objects(detection, common, coordinate_mode))

    write_csv(output / "detection_frames.csv", frame_rows, summary_fields)
    write_csv(csv_path, objects, DETECTION_FIELDS)
    json_path.write_text(
        json.dumps(objects, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    return len(frames), len(objects)


def export_echo(reader: BinReader, output: Path, chunk_size: int = 4096) -> None:
    echo_dir = output / "echo"
    echo_dir.mkdir(parents=True, exist_ok=True)
    sum_file = np.lib.format.open_memmap(
        echo_dir / "sum_echo.npy",
        mode="w+",
        dtype="<f4",
        shape=(reader.packet_count, ECHO_SAMPLES),
    )
    diff_file = np.lib.format.open_memmap(
        echo_dir / "diff_echo.npy",
        mode="w+",
        dtype="<f4",
        shape=(reader.packet_count, ECHO_SAMPLES),
    )
    for start in range(0, reader.packet_count, chunk_size):
        end = min(start + chunk_size, reader.packet_count)
        sum_echo, diff_echo = reader.echo(slice(start, end))
        sum_file[start:end] = sum_echo
        diff_file[start:end] = diff_echo
    del sum_file, diff_file


def _to_db(values: np.ndarray) -> np.ndarray:
    return (10.0 * np.log10(np.maximum(values, 1e-30))).astype(np.float32)


def export_mat(reader: BinReader, output: Path, max_frames: int | None) -> int:
    mat_dir = output / "mat"
    mat_dir.mkdir(parents=True, exist_ok=True)
    frames = reader.ant_frame_ranges(max_frames)
    stem = reader.path.stem.removesuffix("_mmwave_udp")

    for ant_index, (start, end) in enumerate(frames):
        headers = reader.headers[start:end]
        sum_echo, diff_echo = reader.echo(slice(start, end))
        sum_db = _to_db(sum_echo[:, 1:-1])
        diff_db = _to_db(diff_echo[:, 1:-1])
        elevation_keys = (
            np.round(headers["antenna_elevation_deg"].astype(float) * 2.0) / 2.0
        )
        levels = np.unique(elevation_keys)
        data_ori = np.empty((len(levels), 1), dtype=object)
        beam_pose = np.empty((len(levels), 1), dtype=object)

        for level_index, level in enumerate(levels):
            indices = np.flatnonzero(elevation_keys == level)
            order = np.argsort(
                headers["antenna_azimuth_deg"][indices], kind="stable"
            )
            indices = indices[order]
            layer_headers = headers[indices]
            sub = np.empty((1, 5), dtype=object)
            sub[0, 0] = np.asarray([[level]], dtype=np.float32)
            sub[0, 1] = layer_headers["antenna_azimuth_deg"].astype(np.float64)[
                None, :
            ]
            sub[0, 2] = diff_db[indices].T
            sub[0, 3] = sum_db[indices].T
            metadata = np.column_stack(
                (
                    np.zeros(len(indices)),
                    layer_headers["plane_latitude_deg"],
                    layer_headers["plane_longitude_deg"],
                    layer_headers["true_heading_deg"],
                    layer_headers["gps_altitude_m"],
                    np.zeros(len(indices)),
                    layer_headers["antenna_elevation_deg"],
                )
            ).astype(np.float64)
            sub[0, 4] = metadata
            data_ori[level_index, 0] = sub
            beam_pose[level_index, 0] = np.column_stack(
                (
                    layer_headers["antenna_azimuth_deg"],
                    layer_headers["antenna_elevation_deg"],
                    layer_headers["plane_latitude_deg"],
                    layer_headers["plane_longitude_deg"],
                    layer_headers["gps_altitude_m"],
                    layer_headers["true_heading_deg"],
                    layer_headers["timestamp_hmsm"],
                )
            ).astype(np.float64)

        detection = reader.detection(start)
        detection_mat = {
            key: value
            for key, value in detection.items()
            if key not in {"sync_start", "sync_end"}
        }
        net_start = int(headers[0]["net_send_frame"])
        net_end = int(headers[-1]["net_send_frame"])
        filename = f"{stem}_AntFrame{ant_index:03d}_FZ{net_start:06d}-{net_end:06d}.mat"
        savemat(
            mat_dir / filename,
            {
                "Data_Ori": data_ori,
                "BeamPose": beam_pose,
                "RadarDetections": detection_mat,
                "PacketIndexRange": np.asarray([[start, end - 1]], dtype=np.int64),
            },
            do_compression=True,
        )
    return len(frames)


def validate(reader: BinReader) -> dict[str, Any]:
    words = reader.words
    checks = {
        "header_start_ABAB": int(np.count_nonzero(words[:, 0] != 0xABABABAB)),
        "header_start_2_ABAB": int(np.count_nonzero(words[:, 1] != 0xABABABAB)),
        "header_end_BCBC": int(np.count_nonzero(words[:, 62] != 0xBCBCBCBC)),
        "header_end_2_BCBC": int(np.count_nonzero(words[:, 63] != 0xBCBCBCBC)),
        "sum_start_1122": int(np.count_nonzero(words[:, 64] != 0x11221122)),
        "sum_start_2_1122": int(np.count_nonzero(words[:, 65] != 0x11221122)),
        "sum_end_1_2233": int(np.count_nonzero(words[:, 734] != 0x22332233)),
        "sum_end_2233": int(np.count_nonzero(words[:, 735] != 0x22332233)),
        "diff_start_3344": int(np.count_nonzero(words[:, 736] != 0x33443344)),
        "diff_start_2_3344": int(np.count_nonzero(words[:, 737] != 0x33443344)),
        "diff_end_1_4455": int(np.count_nonzero(words[:, 1406] != 0x44554455)),
        "diff_end_4455": int(np.count_nonzero(words[:, 1407] != 0x44554455)),
        "terrain_start_CDCD": int(
            np.count_nonzero(words[:, TERRAIN_OFFSET_WORDS] != 0xCDCDCDCD)
        ),
        "terrain_start_2_CDCD": int(
            np.count_nonzero(words[:, TERRAIN_OFFSET_WORDS + 1] != 0xCDCDCDCD)
        ),
        "terrain_end_1_DEDE": int(
            np.count_nonzero(words[:, TERRAIN_OFFSET_WORDS + 34] != 0xDEDEDEDE)
        ),
        "terrain_end_DEDE": int(
            np.count_nonzero(words[:, TERRAIN_OFFSET_WORDS + 35] != 0xDEDEDEDE)
        ),
        "detection_start_ACAC": int(
            np.count_nonzero(words[:, DETECTION_OFFSET_WORDS] != 0xACACACAC)
        ),
        "detection_start_2_ACAC": int(
            np.count_nonzero(words[:, DETECTION_OFFSET_WORDS + 1] != 0xACACACAC)
        ),
        "detection_end_1_BDBD": int(
            np.count_nonzero(words[:, DETECTION_OFFSET_WORDS + 710] != 0xBDBDBDBD)
        ),
        "detection_end_BDBD": int(
            np.count_nonzero(words[:, DETECTION_OFFSET_WORDS + 711] != 0xBDBDBDBD)
        ),
    }
    return {
        "input_file": str(reader.path.resolve()),
        "packet_size_bytes": PACKET_SIZE,
        "packet_count": reader.packet_count,
        "trailing_bytes": reader.trailing_bytes,
        "antenna_frame_count": len(reader.ant_frame_ranges()),
        "sync_mismatch_counts": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="读取 LH 毫米波雷达 BIN，并导出接口数据、MAT 和目标检测列表。"
    )
    parser.add_argument("bin_file", type=Path, help="输入 *_mmwave_udp.bin")
    parser.add_argument(
        "-o", "--output", type=Path, help="输出目录，默认在 BIN 同级生成 <文件名>_export"
    )
    parser.add_argument("--mat", action="store_true", help="按天线帧导出兼容 MAT")
    parser.add_argument("--detections", action="store_true", help="导出检测目标 CSV/JSON")
    parser.add_argument("--headers", action="store_true", help="导出全部包头 CSV")
    parser.add_argument("--terrain", action="store_true", help="导出地杂波目标 CSV")
    parser.add_argument("--echo", action="store_true", help="导出全部和/差回波 NPY")
    parser.add_argument("--all", action="store_true", help="启用以上所有导出")
    parser.add_argument(
        "--coordinate-mode",
        choices=("nwu", "enu", "body", "local"),
        default="nwu",
        help="检测局部坐标转 GPS 的轴定义，接口规定为 nwu",
    )
    parser.add_argument("--max-packets", type=int, help="仅处理前 N 个数据包，调试用")
    parser.add_argument("--max-ant-frames", type=int, help="仅处理前 N 个天线帧")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.bin_file.is_file():
        print(f"错误：BIN 文件不存在：{args.bin_file}", file=sys.stderr)
        return 2

    output = args.output or args.bin_file.with_name(f"{args.bin_file.stem}_export")
    output.mkdir(parents=True, exist_ok=True)
    reader = BinReader(args.bin_file, args.max_packets)
    summary = validate(reader)
    exports: dict[str, Any] = {}

    requested = any(
        (args.mat, args.detections, args.headers, args.terrain, args.echo, args.all)
    )
    do_detections = args.detections or args.all or not requested
    if args.headers or args.all:
        exports["header_rows"] = export_headers(reader, output)
    if args.terrain or args.all:
        exports["terrain_rows"] = export_terrain(reader, output)
    if do_detections:
        frame_count, object_count = export_detections(
            reader, output, args.coordinate_mode, args.max_ant_frames
        )
        exports["detection_frames"] = frame_count
        exports["detection_objects"] = object_count
    if args.echo or args.all:
        export_echo(reader, output)
        exports["echo_packets"] = reader.packet_count
    if args.mat or args.all:
        exports["mat_files"] = export_mat(reader, output, args.max_ant_frames)

    summary["coordinate_mode"] = args.coordinate_mode
    summary["exports"] = exports
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
