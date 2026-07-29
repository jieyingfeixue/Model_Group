"""Export camera-frame to mmWave MAT matches.

Fast path: use existing per-segment ``radar_camera_match_ts.csv`` or capture
level ``match_mat_camera.csv``. This script does not read BIN files.

Output CSV columns:
    camera_abs_path, mat_abs_path
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from pathlib import Path

import numpy as np


THIS_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = Path(r"L:\LH_data_all_sensor")
DEFAULT_OUTPUT = Path(r"L:\camera_mat_matches.csv")

_RE_CAM_T = re.compile(r"_t([\d.]+)\.jpg$", re.IGNORECASE)
_RE_FZ = re.compile(r"_FZ(\d+)-(\d+)\.mat$", re.IGNORECASE)
_CAM_SUBDIR = "hikrobot_camera__DA8679037__image_raw"
_MATCH_CSV = "radar_camera_match_ts.csv"
_CAPTURE_MATCH_CSV = "match_mat_camera.csv"


def _progress(index: int, total: int, text: str) -> None:
    width = 28
    done = int(width * index / max(total, 1))
    bar = "#" * done + "-" * (width - done)
    pct = 100.0 * index / max(total, 1)
    print(f"[{bar}] {index}/{total} {pct:5.1f}%  {text}", flush=True)


def _find_radar_dir(capture_dir: Path) -> Path | None:
    for child in sorted(capture_dir.iterdir()):
        if child.is_dir() and child.name.endswith("_radar") and any(child.glob("*.mat")):
            return child
    fallback = capture_dir / "mmwave_mat_1218style"
    if fallback.exists() and any(fallback.glob("*.mat")):
        return fallback
    return None


def _iter_captures(root: Path) -> list[Path]:
    captures: list[Path] = []
    for bin_path in root.rglob("*_mmwave_udp.bin"):
        captures.append(bin_path.parent)
    return sorted(set(captures))


def _camera_records_by_part(cap_dir: Path) -> dict[str, list[tuple[float, Path]]]:
    result: dict[str, list[tuple[float, Path]]] = {}
    for part_dir in sorted(cap_dir.iterdir()):
        if not part_dir.is_dir() or "_part" not in part_dir.name:
            continue
        rows: list[tuple[float, Path]] = []
        for seg_dir in sorted(part_dir.iterdir()):
            if not seg_dir.is_dir() or not seg_dir.name.startswith("segment_"):
                continue
            cam_dir = seg_dir / "images" / _CAM_SUBDIR
            if not cam_dir.exists():
                continue
            for image_path in sorted(cam_dir.glob("*.jpg")):
                match = _RE_CAM_T.search(image_path.name)
                if match:
                    rows.append((float(match.group(1)), image_path.resolve()))
        rows.sort(key=lambda item: item[0])
        if rows:
            result[part_dir.name] = rows
    return result


def _nearest_indices(
    camera_times: np.ndarray,
    candidate_times: np.ndarray,
    candidate_indices: np.ndarray,
) -> np.ndarray:
    if camera_times.size == 0 or candidate_times.size == 0:
        return np.empty(0, dtype=np.int64)
    right = np.searchsorted(candidate_times, camera_times, side="left")
    right = np.clip(right, 0, len(candidate_times) - 1)
    left = np.clip(right - 1, 0, len(candidate_times) - 1)
    choose_left = (
        np.abs(candidate_times[left] - camera_times)
        <= np.abs(candidate_times[right] - camera_times)
    )
    nearest = np.where(choose_left, left, right)
    return candidate_indices[nearest].astype(np.int64)


def _load_segment_csv_rows(seg_dir: Path, radar_dir: Path) -> list[tuple[float, str, Path]]:
    rows: list[dict[str, str]] = []
    csv_path = seg_dir / _MATCH_CSV
    if not csv_path.exists():
        return []
    out: list[tuple[float, str, Path]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mat_name = (row.get("mat_filename") or row.get("mat_name") or "").strip()
            if not mat_name:
                continue
            raw_time = (
                row.get("camera_rel_time_sec")
                or row.get("camera_rel_time")
                or row.get("mat_rel_time_sec")
                or ""
            )
            try:
                t = float(raw_time)
            except (TypeError, ValueError):
                t = float("nan")
            cam_name = (row.get("camera_filename") or row.get("camera_name") or "").strip()
            mat_path = radar_dir / mat_name
            if mat_path.exists():
                out.append((t, cam_name, mat_path.resolve()))
    return out


def _load_capture_mat_times(cap_dir: Path, radar_dir: Path) -> list[tuple[float, Path]]:
    csv_path = cap_dir / _CAPTURE_MATCH_CSV
    if not csv_path.exists():
        return []
    out: list[tuple[float, Path]] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            mat_name = (row.get("mat_name") or row.get("mat_filename") or "").strip()
            raw_time = (
                row.get("camera_rel_time")
                or row.get("mat_rel_time_sec")
                or row.get("nav100_rel_time")
                or ""
            )
            try:
                t = float(raw_time)
            except (TypeError, ValueError):
                continue
            mat_path = radar_dir / mat_name
            if mat_path.exists():
                out.append((t, mat_path.resolve()))
    out.sort(key=lambda item: item[0])
    return out


def _fallback_mat_times_from_names(radar_dir: Path) -> list[tuple[float, Path]]:
    out: list[tuple[float, Path]] = []
    for index, mat_path in enumerate(sorted(radar_dir.glob("*.mat"))):
        match = _RE_FZ.search(mat_path.name)
        if match:
            start, end = map(int, match.groups())
            t = (start + end) * 0.5
        else:
            t = float(index)
        out.append((float(t), mat_path.resolve()))
    return out


def process_capture(cap_dir: Path) -> list[dict[str, str]]:
    radar_dir = _find_radar_dir(cap_dir)
    if radar_dir is None:
        return []

    out: list[dict[str, str]] = []
    capture_mat_times = _load_capture_mat_times(cap_dir, radar_dir)

    for part_dir in sorted(cap_dir.iterdir()):
        if not part_dir.is_dir() or "_part" not in part_dir.name:
            continue
        for seg_dir in sorted(part_dir.iterdir()):
            if not seg_dir.is_dir() or not seg_dir.name.startswith("segment_"):
                continue
            cam_dir = seg_dir / "images" / _CAM_SUBDIR
            if not cam_dir.exists():
                continue
            images = []
            for image_path in sorted(cam_dir.glob("*.jpg")):
                match = _RE_CAM_T.search(image_path.name)
                if match:
                    images.append((float(match.group(1)), image_path.resolve()))
            if not images:
                continue

            seg_rows = _load_segment_csv_rows(seg_dir, radar_dir)
            exact: dict[str, Path] = {
                cam_name: mat_path
                for _t, cam_name, mat_path in seg_rows
                if cam_name
            }
            if exact:
                for _t, image_path in images:
                    mat_path = exact.get(image_path.name)
                    if mat_path is not None:
                        out.append(
                            {
                                "camera_abs_path": str(image_path),
                                "mat_abs_path": str(mat_path),
                            }
                        )
                continue

            timed = [(t, mat_path) for t, _cam, mat_path in seg_rows if np.isfinite(t)]
            if not timed:
                timed = capture_mat_times
            if not timed:
                timed = _fallback_mat_times_from_names(radar_dir)
            if not timed:
                continue
            timed.sort(key=lambda item: item[0])
            candidate_times = np.asarray([item[0] for item in timed], dtype=np.float64)
            candidate_indices = np.arange(len(timed), dtype=np.int64)
            camera_times = np.asarray([item[0] for item in images], dtype=np.float64)
            nearest = _nearest_indices(camera_times, candidate_times, candidate_indices)
            for (_t, image_path), mat_index in zip(images, nearest):
                mat_path = timed[int(mat_index)][1]
                out.append(
                    {
                        "camera_abs_path": str(image_path),
                        "mat_abs_path": str(mat_path),
                    }
                )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Export LH camera to MAT CSV.")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    root = args.root.resolve()
    output = args.output.resolve()
    lock_path = output.with_suffix(output.suffix + ".lock")
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode("ascii", errors="ignore"))
        os.close(fd)
    except FileExistsError:
        raise SystemExit(f"another export appears to be running: {lock_path}")

    t0 = time.time()
    captures = _iter_captures(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "camera_abs_path",
        "mat_abs_path",
    ]

    total_rows = 0
    processed = 0
    skipped = 0
    print(f"found {len(captures)} captures in {time.time() - t0:.1f}s", flush=True)
    try:
        with output.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            handle.flush()
            os.fsync(handle.fileno())
            for index, cap_dir in enumerate(captures, 1):
                try:
                    rows = process_capture(cap_dir)
                except Exception as exc:
                    skipped += 1
                    _progress(index, len(captures), f"skip {cap_dir}: {exc}")
                    continue
                if not rows:
                    skipped += 1
                    _progress(index, len(captures), f"no rows: {cap_dir}")
                    continue
                writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
                total_rows += len(rows)
                processed += 1
                _progress(
                    index,
                    len(captures),
                    f"{cap_dir.name}: {len(rows)} rows, total={total_rows}, "
                    f"size={output.stat().st_size:,} bytes",
                )

        print(
            f"done: captures={len(captures)}, processed={processed}, "
            f"skipped={skipped}, rows={total_rows}, output={output}",
            flush=True,
        )
        return 0
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
