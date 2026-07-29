"""Export one ERAD-style NPZ per camera image directly from LH mmWave BIN.

The output format matches a template NPZ with keys:
    erad, range_m, azimuth_deg, elevation_deg, doppler

Rules:
    * Each camera image is matched to the nearest AntFrame using the same
      W12/nav100/camera-anchor timing logic as match_radar_camera_anchor.py.
    * No angular interpolation is performed. For each target az/el bin in the
      template, the nearest raw BIN beam in the selected AntFrame is copied.
    * BIN has no Doppler dimension, so the same energy cube is copied into all
      Doppler bins.
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np


THIS_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(r"L:\LH_Dataset\LH_data_all_sensor")
DEFAULT_OUT_ROOT = Path(r"L:\LH_Dataset\LH_radar_npz")
DEFAULT_TEMPLATE = Path(r"D:\Documents\lhui\erad.npz")

PKT = 8624
PKT_WORDS = PKT // 4
CAM_SUBDIR = "hikrobot_camera__DA8679037__image_raw"
RE_CAM_T = re.compile(r"_t([\d.]+)\.jpg$", re.IGNORECASE)


@dataclass(frozen=True)
class ImageRecord:
    path: Path
    segment_dir: Path
    part_name: str
    time_sec: float


@dataclass
class SegmentPose:
    state_time: np.ndarray
    pitch_deg: np.ndarray
    heading_time: np.ndarray
    heading_deg: np.ndarray


@dataclass
class AntFrameData:
    start: int
    end: int
    ant_az: np.ndarray
    ant_el: np.ndarray
    heading: np.ndarray
    sum_db: np.ndarray


def _load_anchor_module():
    path = THIS_DIR / "match_radar_camera_anchor.py"
    spec = importlib.util.spec_from_file_location("match_radar_camera_anchor", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _angle_diff_deg(a: np.ndarray | float, b: np.ndarray | float) -> np.ndarray:
    return (np.asarray(a, dtype=np.float64) - np.asarray(b, dtype=np.float64) + 180.0) % 360.0 - 180.0


def _progress(index: int, total: int, text: str) -> None:
    width = 30
    done = int(width * index / max(total, 1))
    bar = "#" * done + "-" * (width - done)
    pct = 100.0 * index / max(total, 1)
    print(f"[{bar}] {index}/{total} {pct:5.1f}%  {text}", flush=True)


def _power_to_db(x: np.ndarray) -> np.ndarray:
    return (10.0 * np.log10(np.maximum(x, 1e-3))).astype(np.float32)


def _read_csv_columns(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _load_segment_pose(seg_dir: Path) -> SegmentPose | None:
    state_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
    state_rows = _read_csv_columns(state_csv)
    if not state_rows:
        return None

    state_t: list[float] = []
    pitch: list[float] = []
    true_heading: list[float] = []
    for row in state_rows:
        try:
            state_t.append(float(row["relative_time_sec"]))
            pitch.append(float(row.get("pitch", "nan")))
            true_heading.append(float(row.get("true_heading_deg", row.get("yaw", "nan"))))
        except (KeyError, ValueError):
            continue
    if not state_t:
        return None

    state_time = np.asarray(state_t, dtype=np.float64)
    order = np.argsort(state_time)
    state_time = state_time[order]
    pitch_arr = np.asarray(pitch, dtype=np.float64)[order]
    if np.nanmedian(np.abs(pitch_arr)) < math.tau:
        pitch_arr = np.rad2deg(pitch_arr)

    heading_csv = seg_dir / "heading" / "nav100__heading" / "nav100__heading.csv"
    heading_rows = _read_csv_columns(heading_csv)
    heading_t: list[float] = []
    heading: list[float] = []
    for row in heading_rows:
        try:
            heading_t.append(float(row["relative_time_sec"]))
            heading.append(float(row.get("value", "")))
        except (KeyError, ValueError):
            continue
    if heading_t:
        heading_time = np.asarray(heading_t, dtype=np.float64)
        h_order = np.argsort(heading_time)
        heading_time = heading_time[h_order]
        heading_arr = np.asarray(heading, dtype=np.float64)[h_order]
    else:
        heading_time = state_time
        heading_arr = np.asarray(true_heading, dtype=np.float64)[order]

    return SegmentPose(
        state_time=state_time,
        pitch_deg=pitch_arr,
        heading_time=heading_time,
        heading_deg=heading_arr,
    )


def _pose_at(pose: SegmentPose, t: float) -> tuple[float, float]:
    pitch = float(np.interp(t, pose.state_time, pose.pitch_deg))
    heading = float(np.interp(t, pose.heading_time, pose.heading_deg)) % 360.0
    return pitch, heading


def _iter_images(capture_dir: Path) -> list[ImageRecord]:
    out: list[ImageRecord] = []
    for part_dir in sorted(capture_dir.iterdir()):
        if not part_dir.is_dir() or "_part" not in part_dir.name:
            continue
        for seg_dir in sorted(part_dir.iterdir()):
            if not seg_dir.is_dir() or not seg_dir.name.startswith("segment_"):
                continue
            cam_dir = seg_dir / "images" / CAM_SUBDIR
            if not cam_dir.exists():
                continue
            for image_path in sorted(cam_dir.glob("*.jpg")):
                match = RE_CAM_T.search(image_path.name)
                if not match:
                    continue
                out.append(
                    ImageRecord(
                        path=image_path,
                        segment_dir=seg_dir,
                        part_name=part_dir.name,
                        time_sec=float(match.group(1)),
                    )
                )
    return out


def _packet_timeline(anchor, bin_path: Path, parts) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n_pkts = bin_path.stat().st_size // PKT
    if n_pkts <= 0:
        empty_f = np.empty(0, dtype=np.float64)
        empty_i = np.empty(0, dtype=np.int32)
        return empty_f, empty_i, empty_i, empty_i

    mm = np.memmap(str(bin_path), dtype="<u4", mode="r", shape=(n_pkts, PKT_WORDS))
    start_mask = (mm[:, 6] == 1).astype(np.int32)
    antframe_arr = np.maximum(np.cumsum(start_mask) - 1, 0).astype(np.int32)
    gps_cst_all = anchor.decode_w12(mm[:, 11])
    del mm

    w12_sec = gps_cst_all.astype(np.int64)
    diff = np.concatenate([[1], np.diff(w12_sec)])
    trans_idx = np.where(diff != 0)[0]
    trans_gps = w12_sec[trans_idx].astype(np.float64)

    anchor_rel, anchor_part_idx = anchor.build_anchor_rel_times(trans_idx, trans_gps, parts)
    dense_idx, dense_rel, dense_pi = anchor.densify_with_camera_anchors(
        n_pkts, trans_idx, anchor_rel, anchor_part_idx, parts
    )
    rel_time, pkt_part = anchor.interpolate_rel_times(n_pkts, dense_idx, dense_rel, dense_pi)
    return rel_time, pkt_part, antframe_arr, start_mask


def _antframe_candidates_by_part(
    rel_time: np.ndarray,
    pkt_part: np.ndarray,
    antframe_arr: np.ndarray,
) -> tuple[dict[int, tuple[np.ndarray, np.ndarray]], dict[int, tuple[int, int]]]:
    ranges: dict[int, tuple[int, int]] = {}
    for antframe in np.unique(antframe_arr):
        idx = np.flatnonzero(antframe_arr == antframe)
        if idx.size:
            ranges[int(antframe)] = (int(idx[0]), int(idx[-1]))

    by_part: dict[int, list[tuple[float, int]]] = {}
    for antframe, (start, end) in ranges.items():
        idx = np.arange(start, end + 1, dtype=np.int64)
        valid = np.isfinite(rel_time[idx]) & (pkt_part[idx] >= 0)
        if not valid.any():
            continue
        valid_idx = idx[valid]
        part_values = pkt_part[valid_idx]
        part = int(np.bincount(part_values.astype(np.int64)).argmax())
        center_t = float(np.nanmedian(rel_time[valid_idx]))
        by_part.setdefault(part, []).append((center_t, antframe))

    packed: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    for part, rows in by_part.items():
        rows.sort(key=lambda item: item[0])
        packed[part] = (
            np.asarray([r[0] for r in rows], dtype=np.float64),
            np.asarray([r[1] for r in rows], dtype=np.int32),
        )
    return packed, ranges


def _antframe_ranges_from_bin(bin_path: Path) -> dict[int, tuple[int, int]]:
    n_pkts = bin_path.stat().st_size // PKT
    if n_pkts <= 0:
        return {}
    mm = np.memmap(str(bin_path), dtype="<u4", mode="r", shape=(n_pkts, PKT_WORDS))
    start_mask = (mm[:, 6] == 1).astype(np.int32)
    antframe_arr = np.maximum(np.cumsum(start_mask) - 1, 0).astype(np.int32)
    del mm

    ranges: dict[int, tuple[int, int]] = {}
    for antframe in np.unique(antframe_arr):
        idx = np.flatnonzero(antframe_arr == antframe)
        if idx.size:
            ranges[int(antframe)] = (int(idx[0]), int(idx[-1]))
    return ranges


def _fallback_antframe_map(images: list[ImageRecord], antframe_ids: np.ndarray) -> dict[Path, int]:
    if len(images) == 0 or len(antframe_ids) == 0:
        return {}
    ordered = sorted(images, key=lambda rec: (rec.part_name, rec.time_sec, rec.path.name))
    if len(ordered) == 1 or len(antframe_ids) == 1:
        return {ordered[0].path: int(antframe_ids[0])}
    pos = np.linspace(0, len(antframe_ids) - 1, num=len(ordered))
    nearest = np.rint(pos).astype(np.int64)
    return {rec.path: int(antframe_ids[idx]) for rec, idx in zip(ordered, nearest)}


def _nearest_antframes(times: np.ndarray, candidates: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    cand_t, cand_ids = candidates
    right = np.searchsorted(cand_t, times, side="left")
    right = np.clip(right, 0, len(cand_t) - 1)
    left = np.clip(right - 1, 0, len(cand_t) - 1)
    choose_left = np.abs(cand_t[left] - times) <= np.abs(cand_t[right] - times)
    nearest = np.where(choose_left, left, right)
    return cand_ids[nearest].astype(np.int32)


def _load_antframe_data(bin_path: Path, start: int, end: int) -> AntFrameData:
    n_pkts = end - start + 1
    with bin_path.open("rb") as handle:
        handle.seek(start * PKT)
        buf = handle.read(n_pkts * PKT)
    arr = np.frombuffer(buf, dtype=np.uint8).reshape(n_pkts, PKT)

    ant_az = arr[:, 80:84].copy().view("<f4").ravel().astype(np.float64)
    ant_el = arr[:, 84:88].copy().view("<f4").ravel().astype(np.float64)
    heading = arr[:, 56:60].copy().view("<f4").ravel().astype(np.float64)
    body = arr[:, 256:5632]
    sum_lin = np.frombuffer(body[:, 8:8 + 668 * 4].tobytes(), dtype="<f4").reshape(n_pkts, 668)
    sum_db = _power_to_db(sum_lin)
    return AntFrameData(start=start, end=end, ant_az=ant_az, ant_el=ant_el, heading=heading, sum_db=sum_db)


def _make_erad(
    frame: AntFrameData,
    camera_pitch_deg: float,
    camera_heading_deg: float,
    azimuth_axis: np.ndarray,
    elevation_axis: np.ndarray,
    doppler_count: int,
) -> np.ndarray:
    n_range = frame.sum_db.shape[1]
    grid = np.zeros((n_range, len(azimuth_axis), len(elevation_axis)), dtype=np.float32)

    beam_abs_az = (frame.heading + frame.ant_az) % 360.0
    beam_el = frame.ant_el
    if len(beam_abs_az) == 0:
        return np.repeat(grid[:, :, :, None], doppler_count, axis=3)

    for ia, az_rel in enumerate(azimuth_axis):
        desired_az = (camera_heading_deg + float(az_rel)) % 360.0
        az_err = np.abs(_angle_diff_deg(beam_abs_az, desired_az))
        for ie, el_rel in enumerate(elevation_axis):
            desired_el = camera_pitch_deg + float(el_rel)
            el_err = np.abs(beam_el - desired_el)
            # Nearest-neighbour in the raw beam set. Az/el resolutions are
            # intentionally ignored after choosing the nearest beam.
            score = az_err + el_err * 2.0
            beam_index = int(np.argmin(score))
            grid[:, ia, ie] = frame.sum_db[beam_index]

    return np.repeat(grid[:, :, :, None], doppler_count, axis=3)


def _output_path(out_root: Path, root: Path, image_path: Path) -> Path:
    rel = image_path.relative_to(root)
    return (out_root / rel).with_suffix(".npz")


def _discover_captures(root: Path, capture_dir: Path | None = None) -> list[Path]:
    if capture_dir is not None:
        capture_dir = capture_dir.resolve()
        if list(capture_dir.glob("*_mmwave_udp.bin")):
            return [capture_dir]
        return []

    captures: list[Path] = []
    if list(root.glob("*_mmwave_udp.bin")):
        captures.append(root)

    day_dirs = [p for p in sorted(root.iterdir()) if p.is_dir()] if root.exists() else []
    for day_dir in day_dirs:
        for cap_dir in sorted(day_dir.glob("with_cameras_capture*")):
            if cap_dir.is_dir() and list(cap_dir.glob("*_mmwave_udp.bin")):
                captures.append(cap_dir)
    return captures


def process_capture(
    *,
    anchor,
    capture_dir: Path,
    root: Path,
    out_root: Path,
    template: dict[str, np.ndarray],
    skip_existing: bool,
    limit: int | None,
    progress_every: int,
) -> tuple[int, int]:
    bins = sorted(capture_dir.glob("*_mmwave_udp.bin"))
    if not bins:
        return 0, 0
    bin_path = bins[0]
    print(f"  {capture_dir.name}: loading parts", flush=True)
    parts = anchor.load_capture(capture_dir)
    print(f"  {capture_dir.name}: parts={len(parts)} loading images", flush=True)
    images = _iter_images(capture_dir)
    print(f"  {capture_dir.name}: images={len(images)} bin={bin_path.name}", flush=True)
    if not images:
        return 0, 0

    candidates_by_part: dict[int, tuple[np.ndarray, np.ndarray]] = {}
    if parts:
        print(f"  {capture_dir.name}: building packet timeline", flush=True)
        rel_time, pkt_part, antframe_arr, _start_mask = _packet_timeline(anchor, bin_path, parts)
        print(f"  {capture_dir.name}: building AntFrame candidates", flush=True)
        candidates_by_part, ranges = _antframe_candidates_by_part(rel_time, pkt_part, antframe_arr)
    else:
        print(f"  {capture_dir.name}: no parts, using fallback AntFrame ranges", flush=True)
        ranges = _antframe_ranges_from_bin(bin_path)
    print(f"  {capture_dir.name}: antframes={len(ranges)} candidate_parts={len(candidates_by_part)}", flush=True)
    if not ranges:
        return 0, 0

    if parts:
        part_index = {part.name: index for index, part in enumerate(parts)}
    else:
        part_index = {}
    for name in sorted({img.part_name for img in images}):
        if name not in part_index:
            part_index[name] = len(part_index)
    fallback_map = _fallback_antframe_map(images, np.asarray(sorted(ranges), dtype=np.int32))
    poses: dict[Path, SegmentPose | None] = {}
    antframe_cache: dict[int, AntFrameData] = {}

    written = 0
    skipped = 0
    seen = 0
    by_part: dict[int, list[ImageRecord]] = {}
    for image in images:
        pi = part_index.get(image.part_name)
        if pi is not None:
            by_part.setdefault(pi, []).append(image)

    for pi, records in by_part.items():
        candidates = candidates_by_part.get(pi)
        if candidates is not None:
            image_times = np.asarray([rec.time_sec for rec in records], dtype=np.float64)
            antframes = _nearest_antframes(image_times, candidates)
        else:
            antframes = np.asarray([fallback_map.get(rec.path, -1) for rec in records], dtype=np.int32)
        for rec, antframe in zip(records, antframes):
            seen += 1
            if limit is not None and written >= limit:
                return written, skipped
            out_path = _output_path(out_root, root, rec.path)
            if skip_existing and out_path.exists():
                skipped += 1
                if progress_every > 0 and seen % progress_every == 0:
                    print(
                        f"  {capture_dir.name}: seen={seen}/{len(images)} written={written} skipped={skipped}",
                        flush=True,
                    )
                continue
            pose = poses.get(rec.segment_dir)
            if rec.segment_dir not in poses:
                pose = _load_segment_pose(rec.segment_dir)
                poses[rec.segment_dir] = pose
            if int(antframe) < 0:
                skipped += 1
                continue
            packet_range = ranges.get(int(antframe))
            if packet_range is None:
                skipped += 1
                continue
            frame = antframe_cache.get(int(antframe))
            if frame is None:
                frame = _load_antframe_data(bin_path, packet_range[0], packet_range[1])
                antframe_cache[int(antframe)] = frame
                if len(antframe_cache) > 8:
                    antframe_cache.pop(next(iter(antframe_cache)))

            if pose is None:
                pitch_deg = 0.0
                heading_deg = float(np.nanmedian(frame.heading)) % 360.0
            else:
                pitch_deg, heading_deg = _pose_at(pose, rec.time_sec)
            erad = _make_erad(
                frame,
                pitch_deg,
                heading_deg,
                template["azimuth_deg"],
                template["elevation_deg"],
                len(template["doppler"]),
            )
            out_path.parent.mkdir(parents=True, exist_ok=True)
            np.savez_compressed(
                out_path,
                erad=erad.astype(np.float32, copy=False),
                range_m=template["range_m"],
                azimuth_deg=template["azimuth_deg"],
                elevation_deg=template["elevation_deg"],
                doppler=template["doppler"],
            )
            written += 1
            if progress_every > 0 and seen % progress_every == 0:
                print(
                    f"  {capture_dir.name}: seen={seen}/{len(images)} written={written} skipped={skipped}",
                    flush=True,
                )

    return written, skipped


def main() -> int:
    parser = argparse.ArgumentParser(description="Export camera-aligned ERAD NPZ files from LH BIN data.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--capture-dir", type=Path, default=None, help="Process one capture directory directly.")
    parser.add_argument("--skip-existing", action="store_true", default=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="Optional total image limit for testing.")
    parser.add_argument("--capture-limit", type=int, default=None, help="Optional capture limit for testing.")
    parser.add_argument("--progress-every", type=int, default=1000, help="Print image progress every N images.")
    args = parser.parse_args()

    root = args.root.resolve()
    out_root = args.out_root.resolve()
    skip_existing = bool(args.skip_existing and not args.overwrite)

    tmpl = np.load(args.template)
    template = {key: tmpl[key].astype(np.float32, copy=False) for key in ["range_m", "azimuth_deg", "elevation_deg", "doppler"]}

    anchor = _load_anchor_module()
    captures = _discover_captures(root, args.capture_dir)
    if args.capture_limit is not None:
        captures = captures[: args.capture_limit]

    print(f"captures={len(captures)} root={root} out={out_root}", flush=True)
    total_written = 0
    total_skipped = 0
    t0 = time.time()
    for index, capture_dir in enumerate(captures, 1):
        remaining = None if args.limit is None else max(0, args.limit - total_written)
        if remaining == 0:
            break
        written, skipped = process_capture(
            anchor=anchor,
            capture_dir=capture_dir,
            root=root,
            out_root=out_root,
            template=template,
            skip_existing=skip_existing,
            limit=remaining,
            progress_every=args.progress_every,
        )
        total_written += written
        total_skipped += skipped
        _progress(
            index,
            len(captures),
            f"{capture_dir.name}: wrote={written}, skipped={skipped}, total={total_written}",
        )

    print(
        f"done written={total_written} skipped={total_skipped} elapsed={time.time() - t0:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
