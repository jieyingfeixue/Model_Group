#!/usr/bin/env python3
"""gen_radar_camera_match.py
============================
为 LH 数据集中每个 segment 目录生成雷达-相机时间对齐 CSV。

算法
----
1. 将 capture 目录下的 ``*_mmwave_udp.bin`` 全量读入 uint32 数组，
   提取每个 FZ 包（位置索引 = mat 文件名中的 FZ{start}-{end}）
   的 ts_hmsm 时间戳（包内偏移 44 字节 = uint32 下标 11）。
2. 对每个 segment：
   a. 读 nav100__state.csv，建立 GPS时间(当日秒) → relative_time_sec 插值表。
   b. 读 images/ 目录，建立 relative_time_sec → 图像文件名对照表。
   c. 对 mmwave_mat_1218style/ 下每个 mat：
      - 解析 FZ_start、FZ_end；取中间 FZ = (start + end) // 2
      - 从 ts_hmsm 数组获取该包时间戳 → gps_tod_sec（当日秒）
      - 线性插值 → relative_time_sec
      - 找时间最近的相机图像
   d. 将结果写入 segment_dir/radar_camera_match_ts.csv

使用方法
--------
# 处理单个 capture 目录
python gen_radar_camera_match.py --capture-dir L:/LH_data_all_sensor/4_29/with_cameras_capture_20260429_164703

# 自动扫描整个数据集根目录
python gen_radar_camera_match.py --root L:/LH_data_all_sensor

# 只统计，不写 CSV（dry-run 模式）
python gen_radar_camera_match.py --capture-dir ... --dry-run

# 如果 bin 文件时间戳是 CST 而 nav100 GPS 是 UTC，加偏移修正
python gen_radar_camera_match.py --capture-dir ... --tz-offset -8

输出 CSV 格式（radar_camera_match_ts.csv，存于 segment 目录）
-----------------------------------------------------------
mat_filename, camera_filename, mat_ant_frame, fz_mid,
mat_gps_tod_sec, mat_rel_time_sec, camera_rel_time_sec, dt_sec
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from pathlib import Path

import numpy as np

# ── 包格式常量 ─────────────────────────────────────────────────────────────
PKT_SIZE       = 8624   # 每个 FZ 包字节数（2156 × 4 字节）
PKT_WORDS      = 2156   # 每个 FZ 包 uint32 数量
TS_HMSM_IDX    = 11     # ts_hmsm 在包内 uint32 数组的下标（字节偏移 44 / 4 = 11）

# ── 目录/文件名正则 ────────────────────────────────────────────────────────
_RE_ANTFRAME   = re.compile(r"_AntFrame(\d+)_FZ(\d+)-(\d+)", re.IGNORECASE)
_RE_IMG_TIME   = re.compile(r"_t(\d+\.\d+)\.[^.]+$")
_STATE_CSV_REL = Path("nav100_state") / "nav100__state" / "nav100__state.csv"
_IMG_SUBDIR    = "hikrobot_camera__DA8679037__image_raw"
_OUT_CSV_NAME  = "radar_camera_match_ts.csv"
_LOCAL_CSV_CACHE_REL = Path("temp") / "radar_match_cache"


def _safe_cache_name(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _local_csv_cache_path(seg_dir: Path) -> Path:
    project_root = Path(__file__).resolve().parents[1]
    cache_dir = project_root / _LOCAL_CSV_CACHE_REL
    seg_key = hashlib.sha1(str(seg_dir).lower().encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{_safe_cache_name(seg_dir.name)}_{seg_key}.csv"


def _write_match_csv(csv_path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        if rows:
            w.writerows(rows)


# ═══════════════════════════════════════════════════════════════════════════
# 时间戳解码
# ═══════════════════════════════════════════════════════════════════════════
# 注意：实测 ts_hmsm 字段存储的是「当日秒数（CST）」的直接整数值
#       （例：60425 ≈ 16h47m05s CST），并非 HHMMSSMMM 编码。
# nav100__state.csv 的 GPS 时间是 UTC，需通过 --tz-offset -8 修正。
def _ts_hmsm_to_sec(ts: np.ndarray) -> np.ndarray:
    """将 ts_hmsm uint32 直接转为当日秒数（float64）。

    实测该字段存储的是 CST 秒数（直接整数，非 HHMMSSMMM 编码）。
    """
    return ts.astype(np.float64)


# ═══════════════════════════════════════════════════════════════════════════
# Bin 文件解析：提取每个 FZ 包的 GPS 时间戳
# ═══════════════════════════════════════════════════════════════════════════
def load_bin_timestamps(bin_path: Path, tz_offset_h: float = 0.0) -> np.ndarray:
    """读取 bin 文件，返回每个 FZ 包的当日 GPS 秒数数组（float64）。

    参数
    ----
    bin_path : Path
        原始 UDP bin 文件路径。
    tz_offset_h : float
        若 bin 时间戳与 nav100 GPS 时间存在时区差（小时），在此指定。
        例如 bin=CST 而 nav100=UTC 时，传入 -8.0（CST 比 UTC 快 8h，
        需减去 8h 才能与 nav100 对齐）。
        默认 0（两者同时区，无需修正）。

    返回
    ----
    ts_sec : np.ndarray, shape (n_pkt,)
        第 i 个元素为 bin 第 i 个 FZ 包的当日 GPS 秒数（已加 tz_offset）。
    """
    file_size = bin_path.stat().st_size
    n_pkt = file_size // PKT_SIZE
    remainder = file_size % PKT_SIZE
    if remainder != 0:
        print(
            f"  [警告] {bin_path.name} 文件大小 {file_size} 不是 {PKT_SIZE} 的整数倍"
            f"（余 {remainder} 字节），末尾 {remainder} 字节将被忽略。"
        )

    print(f"  读取 bin 文件: {bin_path.name}  ({file_size/1e6:.1f} MB, {n_pkt} 包)")

    # 一次性读入全部 uint32，速度最快
    raw_u32 = np.frombuffer(bin_path.read_bytes(), dtype="<u4")
    total_words = n_pkt * PKT_WORDS
    pkts = raw_u32[:total_words].reshape(n_pkt, PKT_WORDS)

    ts_hmsm = pkts[:, TS_HMSM_IDX]         # 每包 ts_hmsm 字段
    ts_sec   = _ts_hmsm_to_sec(ts_hmsm)    # 解码为当日秒数

    # 时区修正（+偏移）
    if tz_offset_h != 0.0:
        ts_sec += tz_offset_h * 3600.0

    return ts_sec


# ═══════════════════════════════════════════════════════════════════════════
# 参考 CSV 解析：构建 local_fz_start → (rel_t_start, rel_t_end) 查询表
# ═══════════════════════════════════════════════════════════════════════════
def load_ref_csv(ref_csv_path: Path) -> dict[int, tuple[float, float]] | None:
    """从参考 CSV（如 mat_to_image_range.csv）加载每个 AntFrame 的相机时间范围。

    参考 CSV 必须包含以下字段：
        local_fz_start, rel_t_start, rel_t_end

    返回 dict: local_fz_start (int) → (rel_t_start, rel_t_end) (float, float)
    若文件不存在或格式不对，返回 None。

    使用场景
    --------
    当 bin 文件内嵌 GPS 时钟（W12）与相机端时钟存在系统性偏差时
    （实测 bag1.1 偏差约 24s），W12→nav100 插值法会产生严重错误。
    此时可传入由人工标定或外部工具生成的参考 CSV，以参考 CSV 中的
    rel_t_start/rel_t_end（已是正确的相机相对时间）直接替代 W12 推算结果。
    """
    if not ref_csv_path.exists():
        print(f"  [警告] 参考 CSV 不存在: {ref_csv_path}")
        return None
    result: dict[int, tuple[float, float]] = {}
    _RE_LFZ = re.compile(r"_FZ(\d+)-(\d+)", re.IGNORECASE)
    try:
        with open(ref_csv_path, newline="", encoding="utf-8") as fh:
            rdr = csv.DictReader(fh)
            for row in rdr:
                # 支持两种键：字段 local_fz_start，或从 mat 文件名解析
                if "local_fz_start" in row and row["local_fz_start"]:
                    fz_s = int(row["local_fz_start"])
                elif "mat" in row:
                    m = _RE_LFZ.search(row["mat"])
                    if not m:
                        continue
                    fz_s = int(m.group(1))
                else:
                    continue
                rel_t_s = float(row["rel_t_start"])
                rel_t_e = float(row["rel_t_end"])
                result[fz_s] = (rel_t_s, rel_t_e)
    except Exception as exc:
        print(f"  [警告] 读取参考 CSV {ref_csv_path} 失败: {exc}")
        return None
    print(f"  已加载参考 CSV: {ref_csv_path.name}，共 {len(result)} 个 AntFrame 时间范围。")
    return result


# ═══════════════════════════════════════════════════════════════════════════
# nav100__state.csv 解析：构建 GPS时间 → relative_time_sec 插值表
# ═══════════════════════════════════════════════════════════════════════════
def load_nav100_state(csv_path: Path) -> tuple[np.ndarray, np.ndarray] | None:
    """从 nav100__state.csv 构建 GPS_tod_sec → relative_time_sec 插值表。

    返回 (gps_tod_arr, rel_time_arr)，均已按 gps_tod 升序排列。
    CSV 列名要求：gps_hour, gps_minute, gps_second, gps_millisecond, relative_time_sec
    若文件不存在或读取失败，返回 None。
    """
    if not csv_path.exists():
        return None
    gps_tod_list: list[float] = []
    rel_time_list: list[float] = []
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            rdr = csv.DictReader(fh)
            for row in rdr:
                h   = float(row["gps_hour"])
                m   = float(row["gps_minute"])
                s   = float(row["gps_second"])
                ms  = float(row["gps_millisecond"])
                tod = h * 3600.0 + m * 60.0 + s + ms / 1000.0
                gps_tod_list.append(tod)
                rel_time_list.append(float(row["relative_time_sec"]))
    except Exception as exc:
        print(f"  [警告] 读取 {csv_path} 失败: {exc}")
        return None

    if not gps_tod_list:
        return None

    gps_arr = np.array(gps_tod_list, dtype=np.float64)
    rel_arr = np.array(rel_time_list, dtype=np.float64)
    order   = np.argsort(gps_arr)
    return gps_arr[order], rel_arr[order]


# ═══════════════════════════════════════════════════════════════════════════
# 图像目录解析：建立 relative_time_sec → 文件名对照
# ═══════════════════════════════════════════════════════════════════════════
def load_image_times(img_dir: Path) -> tuple[np.ndarray, list[str]] | None:
    """返回 (times_arr, names_list)，均按时间升序排列。

    图像文件名格式：..._tTTTTTT.TTT.jpg
    """
    if not img_dir.exists():
        return None
    times: list[float] = []
    names: list[str]   = []
    for p in sorted(img_dir.glob("*.jpg")):
        m = _RE_IMG_TIME.search(p.name)
        if m:
            times.append(float(m.group(1)))
            names.append(p.name)
    if not times:
        return None
    times_arr = np.array(times, dtype=np.float64)
    return times_arr, names


# ═══════════════════════════════════════════════════════════════════════════
# 核心：处理单个 segment
# ═══════════════════════════════════════════════════════════════════════════
def process_segment(
    seg_dir: Path,
    mat_dir: Path,
    ts_sec_arr: np.ndarray,
    dry_run: bool = False,
    ref_csv_map: dict[int, tuple[float, float]] | None = None,
) -> int:
    """为一个 segment 生成 radar_camera_match_ts.csv。

    参数
    ----
    seg_dir : Path
        segment 目录（含 nav100_state/ 和 images/）。
    mat_dir : Path
        mmwave_mat_1218style 目录（含所有 mat 文件）。
    ts_sec_arr : np.ndarray
        全 capture 的 FZ 包时间戳数组（由 load_bin_timestamps 返回）。
    dry_run : bool
        仅打印统计，不写 CSV。
    ref_csv_map : dict | None
        由 load_ref_csv() 返回的查询表 {local_fz_start → (rel_t_start, rel_t_end)}。
        若提供，则跳过 W12→nav100 插值（已知该方法对本数据集存在 ~24s 系统误差），
        直接用参考 CSV 中的相机时间范围中值作为 mat_rel_time_sec。

    返回
    ----
    写入行数（干跑时为 0）。
    """
    # 1. 读取 nav100__state.csv
    state_csv = seg_dir / _STATE_CSV_REL
    nav = load_nav100_state(state_csv)
    if nav is None:
        print(f"  [跳过] {seg_dir.name}: 无 nav100__state.csv")
        return 0
    gps_tod_arr, rel_time_arr = nav

    seg_t_start = float(rel_time_arr.min())
    seg_t_end   = float(rel_time_arr.max())
    gps_t_start = float(gps_tod_arr.min())
    gps_t_end   = float(gps_tod_arr.max())

    # 2. 读取图像列表
    img_dir = seg_dir / "images" / _IMG_SUBDIR
    img_data = load_image_times(img_dir)
    if img_data is None:
        print(f"  [跳过] {seg_dir.name}: 无图像（{_IMG_SUBDIR}）")
        return 0
    img_times, img_names = img_data

    # 3. 遍历所有 mat，筛选属于本 segment 时间范围的
    all_mats = sorted(mat_dir.glob("*.mat"), key=lambda p: p.name)
    if not all_mats:
        print(f"  [跳过] {seg_dir.name}: mat 目录为空")
        return 0

    rows: list[dict] = []
    skipped = 0
    n_pkt = len(ts_sec_arr)

    for mat_path in all_mats:
        m = _RE_ANTFRAME.search(mat_path.name)
        if m is None:
            continue
        ant_frame = int(m.group(1))
        fz_start  = int(m.group(2))
        fz_end    = int(m.group(3))
        fz_mid    = (fz_start + fz_end) // 2

        # 安全边界检查
        if fz_mid >= n_pkt:
            skipped += 1
            continue

        # 中间 FZ 的 GPS 当日秒数（始终读取，用于记录原始时间戳）
        gps_tod_mat = float(ts_sec_arr[fz_mid])

        # ── 路径 A：使用参考 CSV 直接获取相机时间（推荐，绕过 W12 系统误差）──
        if ref_csv_map is not None:
            if fz_start not in ref_csv_map:
                continue  # 此 AntFrame 在参考 CSV 中不存在，跳过
            rel_t_s, rel_t_e = ref_csv_map[fz_start]
            mat_rel_time = (rel_t_s + rel_t_e) / 2.0
            # 用图像时间范围过滤：此 AntFrame 必须与本 segment 有重叠
            if rel_t_e < seg_t_start - 1.0 or rel_t_s > seg_t_end + 1.0:
                continue

        # ── 路径 B：使用 W12→nav100 插值（存在 ~24s 系统误差，仅作回退）──
        else:
            # 判断是否落入本 segment 的 GPS 时间范围（宽松 1 秒容差）
            if not (gps_t_start - 1.0 <= gps_tod_mat <= gps_t_end + 1.0):
                continue

            # GPS_tod → relative_time_sec（线性插值，边界外做外推）
            mat_rel_time = float(np.interp(gps_tod_mat, gps_tod_arr, rel_time_arr))

            # 是否在 segment 相对时间范围内
            if not (seg_t_start - 1.0 <= mat_rel_time <= seg_t_end + 1.0):
                continue

        # 找最近图像
        idx = int(np.argmin(np.abs(img_times - mat_rel_time)))
        cam_time  = float(img_times[idx])
        cam_name  = img_names[idx]
        dt_sec    = abs(cam_time - mat_rel_time)

        rows.append(dict(
            mat_filename     = mat_path.name,
            camera_filename  = cam_name,
            mat_ant_frame    = ant_frame,
            fz_mid           = fz_mid,
            mat_gps_tod_sec  = round(gps_tod_mat, 4),
            mat_rel_time_sec = round(mat_rel_time, 4),
            camera_rel_time_sec = round(cam_time, 4),
            dt_sec           = round(dt_sec, 4),
        ))

    out_csv = seg_dir / _OUT_CSV_NAME
    fieldnames = [
        "mat_filename", "camera_filename", "mat_ant_frame", "fz_mid",
        "mat_gps_tod_sec", "mat_rel_time_sec", "camera_rel_time_sec", "dt_sec",
    ]

    local_cache_csv = _local_csv_cache_path(seg_dir)

    if not rows:
        print(f"  [空] {seg_dir.name}: 无 mat 落入 GPS 时间范围 "
              f"[{gps_t_start:.1f}, {gps_t_end:.1f}]s")
        # 即使无匹配也写入仅含表头的空 CSV，防止 startup_check 每次启动均判定为缺失而无限重试
        if not dry_run:
            try:
                _write_match_csv(out_csv, [], fieldnames)
            except Exception as exc:
                print(f"    [警告] 写 segment CSV 失败，改写本地缓存: {exc}")
            _write_match_csv(local_cache_csv, [], fieldnames)
        return 0

    if dry_run:
        print(f"  [dry-run] {seg_dir.name}: {len(rows)} 对匹配，"
              f"跳过 {skipped} 个越界 FZ，max |dt|={max(r['dt_sec'] for r in rows):.3f}s")
        return 0

    # 写 CSV (segment + 本地缓存)
    try:
        _write_match_csv(out_csv, rows, fieldnames)
    except Exception as exc:
        print(f"    [警告] 写 segment CSV 失败，改写本地缓存: {exc}")
    _write_match_csv(local_cache_csv, rows, fieldnames)

    dt_vals = [r["dt_sec"] for r in rows]
    print(
        f"  {seg_dir.name}: {len(rows)} 行 → {out_csv.name}  "
        f"max_dt={max(dt_vals):.3f}s  mean_dt={sum(dt_vals)/len(dt_vals):.3f}s"
    )
    return len(rows)


# ═══════════════════════════════════════════════════════════════════════════
# 捕获目录处理
# ═══════════════════════════════════════════════════════════════════════════
def find_bin_file(capture_dir: Path) -> Path | None:
    """在 capture_dir 下寻找 *_mmwave_udp.bin 文件。"""
    candidates = list(capture_dir.glob("*_mmwave_udp.bin"))
    if not candidates:
        return None
    if len(candidates) > 1:
        print(f"  [警告] 找到多个 bin 文件，使用第一个: {candidates[0].name}")
    return candidates[0]


def find_mat_dir(capture_dir: Path) -> Path | None:
    """寻找 {bin_stem}_radar 目录（mat 文件所在位置）。"""
    for d in capture_dir.iterdir():
        if d.is_dir() and d.name.endswith("_radar"):
            return d
    return None


def iter_segments(capture_dir: Path):
    """枚举 capture_dir 下所有 segment_* 目录（支持一层或两层嵌套）。"""
    for child in sorted(capture_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("segment_"):
            yield child
        else:
            for grandchild in sorted(child.iterdir()):
                if grandchild.is_dir() and grandchild.name.startswith("segment_"):
                    yield grandchild


def process_capture(
    capture_dir: Path,
    tz_offset_h: float,
    dry_run: bool,
    ref_csv_map: dict[int, tuple[float, float]] | None = None,
    mat_dir_override: Path | None = None,
) -> int:
    """处理一个 capture 目录，返回总写入行数。"""
    print(f"\n[capture] {capture_dir}")

    bin_path = find_bin_file(capture_dir)
    if bin_path is None:
        print("  [跳过] 未找到 *_mmwave_udp.bin")
        return 0

    if mat_dir_override is not None:
        mat_dir = mat_dir_override
        if not mat_dir.is_dir():
            print(f"  [跳过] 指定的 mat 目录不存在: {mat_dir}")
            return 0
    else:
        mat_dir = find_mat_dir(capture_dir)
        if mat_dir is None:
            print("  [跳过] 未找到 mmwave_mat_1218style/")
            return 0

    # 一次性加载全部时间戳（整个 capture 共用）
    ts_sec_arr = load_bin_timestamps(bin_path, tz_offset_h)
    print(f"  共 {len(ts_sec_arr)} 个 FZ 包，mat 目录: {mat_dir.name}")
    if ref_csv_map is not None:
        print(f"  使用参考 CSV 时序（{len(ref_csv_map)} 个 AntFrame），跳过 W12→nav100 插值。")

    segments = list(iter_segments(capture_dir))
    if not segments:
        print("  [跳过] 未找到任何 segment_* 目录")
        return 0

    total = 0
    for seg_dir in segments:
        total += process_segment(seg_dir, mat_dir, ts_sec_arr, dry_run, ref_csv_map)

    return total


# ═══════════════════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════════════════
def main() -> None:
    parser = argparse.ArgumentParser(
        description="生成 LH 数据集雷达-相机时间对齐 CSV",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--capture-dir", type=Path,
        help="单个 capture 目录路径（含 bin 和 mmwave_mat_1218style）",
    )
    group.add_argument(
        "--root", type=Path,
        help="数据集根目录（自动扫描所有 with_cameras_capture_* 子目录）",
    )
    parser.add_argument(
        "--tz-offset", type=float, default=0.0,
        metavar="HOURS",
        help="时区修正：若 bin 时间戳为 CST 而 nav100 为 UTC，传入 -8.0；"
             "若相同时区，保持默认 0（默认: 0）",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅打印统计信息，不写 CSV 文件",
    )
    parser.add_argument(
        "--mat-dir", type=Path, default=None,
        metavar="PATH",
        help="手动指定 mmwave_mat_1218style 目录（适用于 mat 文件不在 capture 目录内的情况）。"
             "未指定时自动在 capture-dir 下寻找 *_radar 子目录。",
    )
    parser.add_argument(
        "--ref-csv", type=Path, default=None,
        metavar="PATH",
        help="参考 CSV 路径（如 mat_to_image_range.csv），须含 local_fz_start / rel_t_start / rel_t_end 字段。"
             "提供后将绕过 W12→nav100 时间插值（适用于 W12 时钟与相机端存在系统性偏差的情况），"
             "直接使用参考 CSV 中的相机时间范围中值匹配图像。",
    )
    args = parser.parse_args()

    # 加载参考 CSV（若提供）
    ref_csv_map: dict[int, tuple[float, float]] | None = None
    if args.ref_csv is not None:
        ref_csv_map = load_ref_csv(args.ref_csv)
        if ref_csv_map is None:
            print(f"[错误] 无法加载参考 CSV: {args.ref_csv}", file=sys.stderr)
            sys.exit(1)

    if args.capture_dir:
        total = process_capture(
            args.capture_dir, args.tz_offset, args.dry_run, ref_csv_map,
            mat_dir_override=args.mat_dir,
        )
        print(f"\n完成，共写入 {total} 行匹配记录。")
    else:
        root = args.root
        capture_dirs = [
            p for p in sorted(root.rglob("with_cameras_capture_*"))
            if p.is_dir() and any(d.name.endswith("_radar") for d in p.iterdir() if d.is_dir())
        ]
        if not capture_dirs:
            print(f"[错误] 在 {root} 下未找到 with_cameras_capture_* 目录", file=sys.stderr)
            sys.exit(1)
        grand_total = 0
        for cap_dir in capture_dirs:
            grand_total += process_capture(cap_dir, args.tz_offset, args.dry_run, ref_csv_map)
        print(f"\n全部完成，共 {len(capture_dirs)} 个 capture，写入 {grand_total} 行。")


if __name__ == "__main__":
    main()
