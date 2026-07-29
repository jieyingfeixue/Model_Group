"""
雷达–相机时间匹配工具。

原理
----
1. 扫描数据集根目录下的所有 capture 目录, 找到已转换的 `{bin_stem}_radar/` 文件夹。
2. 读取其中的 `_timetable.json`, 得到每个 mat 的 GPS UTC 时间范围
   (ts_first / ts_last, 格式 HHMMSSMMM = H*10^7 + M*10^5 + S*10^3 + ms)。
3. 枚举该 capture 下所有 part 子目录:
     - 从目录名 `..._YYYY-MM-DD-HH-MM-SS` 解析 part 的 CST 壁时钟开始时间 → UTC 秒
     - 对每个 part 内的 segment, 从目录名解析 `segment_{idx}_{t_start}_{t_end}` 得到
       relative_time_sec 范围
     - 列出该 segment 下主相机 (DA8679038) 图像, 提取 `_t` 时间戳
4. 对每个 mat:
     - 计算 GPS 时间中点 t_mid_gps (秒)
     - 遍历各 part 计算 relative_t_mid = t_mid_gps - part_start_utc_sec
     - 找到包含 relative_t_mid 的 segment
     - 在该 segment 的图像列表中取最近邻的 `_t` 时间戳
5. 输出 `{radar_dir}/radar_camera_match.json`:
   {
     "{seq_id}": {
       "{image_stem}": "{mat_filename}",
       ...
     },
     ...
   }
   其中 seq_id = "{date}/{capture}/{part}/{segment}",
   其他图像 (未被任何 mat 匹配) 不出现在此 JSON 中。

使用
----
  # 处理所有 capture (默认根目录)
  python match_radar_camera.py

  # 只处理指定 capture
  python match_radar_camera.py --capture "L:/LH_data_all_sensor/4_30/with_cameras_capture_20260430_195500"

  # 强制覆盖已有 JSON
  python match_radar_camera.py --overwrite
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# ── 常量 ────────────────────────────────────────────────────────────────────
_RADAR_SUFFIX = "_radar"
_TIMETABLE    = "_timetable.json"
_MATCH_JSON   = "radar_camera_match.json"
_CAM_SUBDIR   = "hikrobot_camera__DA8679038__image_raw"
_NAV_CSV_REL  = "nav100_state/nav100__state/nav100__state.csv"

# 从 part 目录名提取壁时钟: ..._YYYY-MM-DD-HH-MM-SS
_PART_TS_RE = re.compile(r"_(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})$")
# 从 segment 目录名提取时间范围: segment_{idx}_{t_start}_{t_end}
_SEG_RE     = re.compile(r"^segment_\d+_(\d+\.\d+)_(\d+\.\d+)$")
# 从图像文件名提取 _t 时间戳
_IMG_TS_RE  = re.compile(r"_t(\d+\.\d+)$")
# 从 bin 目录名提取 YYYYMMDD_HHMMSS
_BIN_TS_RE  = re.compile(r"(\d{8}_\d{6})")

# 中国标准时 (CST) = UTC + 8
_CST_UTC_OFFSET_H = 8


# ── 时间工具 ─────────────────────────────────────────────────────────────────

def ts_hmsm_to_utc_sec(ts: int) -> float:
    """将 GPS UTC 时间 HHMMSSMMM 整数转换为当天 UTC 秒数.

    格式: H*10^7 + MM*10^5 + SS*10^3 + mmm
    示例: 120228470 → 12:02:28.470 UTC → 43348.47 s
    """
    if ts <= 0:
        return 0.0
    hh  =  ts // 10_000_000
    mm  = (ts %  10_000_000) // 100_000
    ss  = (ts %     100_000) // 1_000
    msm =  ts %       1_000
    return hh * 3600.0 + mm * 60.0 + ss + msm / 1000.0


def parse_part_utc_sec(part_dir_name: str) -> float | None:
    """从 part 目录名解析其开始的 UTC 绝对秒 (当天秒数).

    目录名格式: `..._YYYY-MM-DD-HH-MM-SS` (CST 壁时钟).
    返回 None 表示解析失败.
    """
    m = _PART_TS_RE.search(part_dir_name)
    if not m:
        return None
    parts_str = m.group(1).split("-")   # ['2026','04','30','19','59','52']
    if len(parts_str) != 6:
        return None
    try:
        hh_cst = int(parts_str[3])
        mm     = int(parts_str[4])
        ss     = int(parts_str[5])
    except ValueError:
        return None
    hh_utc = hh_cst - _CST_UTC_OFFSET_H
    return hh_utc * 3600.0 + mm * 60.0 + ss


def parse_seg_range(seg_dir_name: str) -> tuple[float, float] | None:
    """从 segment 目录名解析时间范围 (相对时间秒).

    目录名格式: `segment_{idx}_{t_start}_{t_end}`.
    """
    m = _SEG_RE.match(seg_dir_name)
    if not m:
        return None
    try:
        return float(m.group(1)), float(m.group(2))
    except ValueError:
        return None


def parse_img_ts(stem: str) -> float | None:
    """从图像文件名 stem 提取 `_t` 时间戳."""
    m = _IMG_TS_RE.search(stem)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


# ── 核心逻辑 ─────────────────────────────────────────────────────────────────

class _SegInfo:
    """单个 segment 的时间范围 + 图像列表."""
    __slots__ = ("t_start", "t_end", "seq_id", "images")

    def __init__(self, t_start: float, t_end: float,
                 seq_id: str, images: list[tuple[float, str]]):
        self.t_start = t_start
        self.t_end   = t_end
        self.seq_id  = seq_id
        # images: sorted list of (timestamp, stem)
        self.images  = images


def _collect_segments(capture_dir: Path, date_dir_name: str,
                       capture_dir_name: str) -> list[tuple[float, list[_SegInfo]]]:
    """遍历 capture 下所有 part 目录, 收集 (part_start_utc_sec, [SegInfo, ...]) 列表."""
    result: list[tuple[float, list[_SegInfo]]] = []

    for child in sorted(capture_dir.iterdir()):
        if not child.is_dir():
            continue

        # ── 直接放 segment 的情况 (part000 有时 segment 直接在 capture 下) ──
        if child.name.startswith("segment_"):
            # 视为匿名 part, 用 capture_dir 本身的时间戳
            part_utc_sec = _parse_capture_utc_sec(capture_dir.name)
            if part_utc_sec is None:
                continue
            _process_part_child(child, part_utc_sec, date_dir_name,
                                 capture_dir_name, "", result)
            continue

        # ── 标准 part 目录 ────────────────────────────────────────────────────
        part_utc_sec = parse_part_utc_sec(child.name)
        if part_utc_sec is None:
            continue

        segs: list[_SegInfo] = []
        for seg_dir in sorted(child.iterdir()):
            if not seg_dir.is_dir() or not seg_dir.name.startswith("segment_"):
                continue
            rng = parse_seg_range(seg_dir.name)
            if rng is None:
                continue
            t_start, t_end = rng

            cam_dir = seg_dir / "images" / _CAM_SUBDIR
            if not cam_dir.exists():
                continue
            imgs: list[tuple[float, str]] = []
            for jp in cam_dir.iterdir():
                if jp.suffix.lower() != ".jpg":
                    continue
                ts = parse_img_ts(jp.stem)
                if ts is not None:
                    imgs.append((ts, jp.stem))
            imgs.sort()

            seq_id = (f"{date_dir_name}/{capture_dir_name}"
                      f"/{child.name}/{seg_dir.name}")
            segs.append(_SegInfo(t_start, t_end, seq_id, imgs))

        if segs:
            result.append((part_utc_sec, segs))

    return result


def _parse_capture_utc_sec(capture_name: str) -> float | None:
    """从 capture 目录名 with_cameras_capture_YYYYMMDD_HHMMSS 解析开始 UTC 秒."""
    m = _BIN_TS_RE.search(capture_name)
    if not m:
        return None
    ts_str = m.group(1)  # 'YYYYMMDD_HHMMSS'
    try:
        hh_cst = int(ts_str[9:11])
        mm     = int(ts_str[11:13])
        ss     = int(ts_str[13:15])
    except (IndexError, ValueError):
        return None
    return (hh_cst - _CST_UTC_OFFSET_H) * 3600.0 + mm * 60.0 + ss


def _process_part_child(seg_dir: Path, part_utc_sec: float,
                         date_dir_name: str, capture_dir_name: str,
                         part_dir_name: str,
                         result: list) -> None:
    """当 segment 直接在 capture 下时的辅助函数."""
    rng = parse_seg_range(seg_dir.name)
    if rng is None:
        return
    t_start, t_end = rng
    cam_dir = seg_dir / "images" / _CAM_SUBDIR
    if not cam_dir.exists():
        return
    imgs: list[tuple[float, str]] = []
    for jp in cam_dir.iterdir():
        if jp.suffix.lower() != ".jpg":
            continue
        ts = parse_img_ts(jp.stem)
        if ts is not None:
            imgs.append((ts, jp.stem))
    imgs.sort()
    if part_dir_name:
        seq_id = (f"{date_dir_name}/{capture_dir_name}"
                  f"/{part_dir_name}/{seg_dir.name}")
    else:
        seq_id = f"{date_dir_name}/{capture_dir_name}/{seg_dir.name}"
    seg_info = _SegInfo(t_start, t_end, seq_id, imgs)
    # 追加为独立 (part_utc_sec, [seg]) 对
    result.append((part_utc_sec, [seg_info]))


def _nearest_image(images: list[tuple[float, str]], t_ref: float
                   ) -> tuple[str, float] | None:
    """在已排序图像列表中找最近邻.

    Returns (image_stem, image_timestamp) 或 None.
    """
    if not images:
        return None
    lo, hi = 0, len(images) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if images[mid][0] < t_ref:
            lo = mid + 1
        else:
            hi = mid
    candidates = [images[lo]]
    if lo > 0:
        candidates.append(images[lo - 1])
    best = min(candidates, key=lambda x: abs(x[0] - t_ref))
    return best[1], best[0]


def process_capture(capture_dir: Path, root: Path,
                    overwrite: bool = False,
                    verbose: bool = True) -> bool:
    """为单个 capture 目录生成 radar_camera_match.json.

    Returns True 表示成功写出, False 表示跳过/失败.
    """
    date_dir_name    = capture_dir.parent.name
    capture_dir_name = capture_dir.name

    # 找 radar 目录 (bin_stem_radar)
    radar_dirs = [d for d in capture_dir.iterdir()
                  if d.is_dir() and d.name.endswith(_RADAR_SUFFIX)]
    if not radar_dirs:
        if verbose:
            print(f"  [跳过] 无 *_radar 目录: {capture_dir.name}")
        return False

    # 若有多个 radar 目录 (通常只有一个 bin), 逐一处理
    all_ok = True
    for radar_dir in radar_dirs:
        timetable_path = radar_dir / _TIMETABLE
        if not timetable_path.exists():
            if verbose:
                print(f"  [跳过] 未找到时间表: {timetable_path}")
            all_ok = False
            continue

        match_path = radar_dir / _MATCH_JSON
        if match_path.exists() and not overwrite:
            if verbose:
                print(f"  [跳过] 已有匹配文件: {match_path.name}")
            continue

        with open(timetable_path, encoding="utf-8") as fp:
            timetable: list[dict] = json.load(fp)

        if not timetable:
            if verbose:
                print(f"  [跳过] 时间表为空: {timetable_path}")
            continue

        # 收集所有 segment 信息
        parts_segs = _collect_segments(
            capture_dir, date_dir_name, capture_dir_name)
        if not parts_segs:
            if verbose:
                print(f"  [警告] 无可用 segment: {capture_dir.name}")
            continue

        if verbose:
            total_segs = sum(len(s) for _, s in parts_segs)
            print(f"  [匹配] {capture_dir.name}: "
                  f"{len(timetable)} mats × {total_segs} segments")

        # 构建 match: {seq_id: {image_stem: mat_name}}
        match: dict[str, dict[str, str]] = {}
        skipped = 0

        for entry in timetable:
            mat_name = entry["mat"]
            ts_first = entry.get("ts_first", 0)
            ts_last  = entry.get("ts_last",  0)
            if ts_first <= 0 or ts_last <= 0:
                skipped += 1
                continue

            gps_sec_first = ts_hmsm_to_utc_sec(ts_first)
            gps_sec_last  = ts_hmsm_to_utc_sec(ts_last)
            # 处理跨小时 (一般不会, 但防御一下)
            if gps_sec_last < gps_sec_first:
                gps_sec_last += 3600.0

            t_mid_gps = (gps_sec_first + gps_sec_last) / 2.0

            # 在各 part 内寻找包含该时间中点的 segment
            best_match: tuple[str, str] | None = None   # (seq_id, image_stem)
            best_dt    = float("inf")

            for part_utc_sec, segs in parts_segs:
                rel_mid = t_mid_gps - part_utc_sec
                for seg in segs:
                    # 稍微放宽边界 (±1s), 以应对时钟漂移
                    if not (seg.t_start - 1.0 <= rel_mid <= seg.t_end + 1.0):
                        continue
                    res = _nearest_image(seg.images, rel_mid)
                    if res is None:
                        continue
                    img_stem, img_ts = res
                    dt = abs(img_ts - rel_mid)
                    if dt < best_dt:
                        best_dt = dt
                        best_match = (seg.seq_id, img_stem)

            if best_match is None:
                skipped += 1
                continue

            seq_id, img_stem = best_match
            if seq_id not in match:
                match[seq_id] = {}
            match[seq_id][img_stem] = mat_name

        with open(match_path, "w", encoding="utf-8") as fp:
            json.dump(match, fp, ensure_ascii=False, indent=2)

        n_matched = sum(len(v) for v in match.values())
        if verbose:
            print(f"         → 匹配 {n_matched} 条, 跳过 {skipped} 条"
                  f" → {match_path.name}")

    return all_ok


def find_capture_dirs(root: Path) -> list[Path]:
    """递归查找所有含 *_mmwave_udp.bin 的 capture 目录."""
    captures = []
    for bin_path in sorted(root.rglob("*_mmwave_udp.bin")):
        captures.append(bin_path.parent)
    return captures


def main() -> None:
    parser = argparse.ArgumentParser(
        description="为 LH_data_all_sensor 中每个 capture 生成 radar_camera_match.json"
    )
    parser.add_argument(
        "root",
        nargs="?",
        default="L:\\LH_data_all_sensor",
        help="数据集根目录 (默认: L:\\LH_data_all_sensor)",
    )
    parser.add_argument(
        "--capture",
        metavar="DIR",
        help="只处理指定 capture 目录 (绝对路径)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="强制覆盖已有 radar_camera_match.json",
    )
    args = parser.parse_args()
    root = Path(args.root)

    if args.capture:
        captures = [Path(args.capture)]
    else:
        if not root.exists():
            print(f"[错误] 根目录不存在: {root}", file=sys.stderr)
            sys.exit(1)
        captures = find_capture_dirs(root)
        if not captures:
            print(f"[警告] 在 {root} 下未找到含 bin 的 capture 目录")
            sys.exit(0)

    print(f"[发现] {len(captures)} 个 capture 目录\n")
    for i, cap in enumerate(captures, 1):
        print(f"[{i}/{len(captures)}] {cap}")
        try:
            process_capture(cap, root, overwrite=args.overwrite)
        except Exception as exc:
            print(f"  [错误] {cap.name}: {exc}", file=sys.stderr)

    print("\n[全部完成]")


if __name__ == "__main__":
    main()
