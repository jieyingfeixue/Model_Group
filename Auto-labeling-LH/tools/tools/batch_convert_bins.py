r"""
批量把 L:\LH_data_all_sensor 下所有 *_mmwave_udp.bin 转换为 1218-style mat。

目录约定:
    {root}/{date}/{capture}/
        {capture}_mmwave_udp.bin                ← 输入
        {capture}_mmwave_udp_radar/             ← 输出 (自动创建, 与 bin 同级)
            mmwave_{date}_{time}_AntFrame{NNN}_FZ{xxxxxx}-{yyyyyy}.mat
            _timetable.json                     ← 各 mat 的 GPS 时间范围元数据

mat 格式 (Data_Ori cell):
    Data_Ori : cell (n_el, 1)
      每元素 = cell (1, 5):
        {1} EL_scalar   float32 (1,1)       本俯仰角 (度)
        {2} AZ0         float64 (1, n_az)   各方位采样角 (度)
        {3} DiffDatadB  float32 (666, n_az) 差路 dB
        {4} SumDatadB   float32 (666, n_az) 和路 dB
        {5} meta        float64 (n_az, 7)   [rangeGate, fLat, fLon, Heading, Alt, PlaneEL, RadarEl]

注意: meta 中的纬度/经度为各 FZ 采集时的原始 GPS 值, 不做任何参考帧归零/统一操作。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
from scipy.io import savemat

# ── 常量 (与 bin_to_1218_mat.py 保持一致) ────────────────────────────────────
PKT = 8624
N_RANGE_FULL = 668      # bin 实际距离单元数
N_RANGE_OUT  = 666      # 与 1218 mat 一致 (去掉首尾各 1 个保护单元)
EL_MIN, EL_MAX, EL_STEP = -10.0, 5.0, 0.5   # 1218 默认俯仰栅格


def power_to_db(x: np.ndarray) -> np.ndarray:
    """实数功率谱 → dB (10 * log10)."""
    return (10.0 * np.log10(np.maximum(x, 1e-3))).astype(np.float32)


def _extract_timestamp_tag(bin_path: Path) -> str:
    """从 bin 文件名抽取 YYYYMMDD_HHMMSS 用于输出文件名."""
    m = re.search(r"(\d{8}_\d{6})", bin_path.name)
    return m.group(1) if m else bin_path.stem


def convert_bin(bin_path: Path, out_dir: Path,
                progress_cb=None) -> None:
    """把单个 bin 文件转换为若干 mat, 输出到 out_dir。

    每个"天线帧" (ant_frame, 连续的 FZ 序列) 对应一个 mat 文件。
    meta 中纬度/经度直接取自各 FZ 原始值, 不做 GPS 统一/归零。
    同时写 out_dir/_timetable.json: [{mat, fz_start, fz_end, ts_first, ts_last}, ...]
    ts_first/ts_last 是 GPS UTC 时间, 格式 HHMMSSMMM (H*10^7+M*10^5+S*10^3+ms)。
    """
    ts_tag = _extract_timestamp_tag(bin_path)
    file_size = os.path.getsize(bin_path)
    if file_size == 0 or file_size % PKT != 0:
        print(f"  [跳过] {bin_path.name}: 文件大小 {file_size} 不是 {PKT} 的整数倍")
        return

    N_TOTAL = file_size // PKT
    print(f"  [扫描] {bin_path.name}  总计 {N_TOTAL} 个 FZ ...")

    # ── 第 1 遍: 扫描每个 FZ 的天线帧序号 (字节偏移 24..27) ─────────────────
    af_start = np.empty(N_TOTAL, dtype=np.uint32)
    # 同时读取 ts_hmsm (偏移 44..47) 供后续时间表使用
    ts_all   = np.empty(N_TOTAL, dtype=np.uint32)
    with open(bin_path, "rb") as f:
        chunk = 8192
        done = 0
        while done < N_TOTAL:
            m = min(chunk, N_TOTAL - done)
            buf = f.read(m * PKT)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(m, PKT)
            af_start[done:done + m] = arr[:, 24:28].copy().view("<u4").ravel()
            ts_all[done:done + m]   = arr[:, 44:48].copy().view("<u4").ravel()
            done += m

    start_idx = np.where(af_start == 1)[0]
    boundaries = np.r_[start_idx, N_TOTAL]   # sentinel
    n_ant_frames = len(start_idx)
    if n_ant_frames == 0:
        print(f"  [警告] {bin_path.name}: 未找到天线帧起始标志, 跳过")
        return
    print(f"  [切分] {n_ant_frames} 个天线帧, 平均 {N_TOTAL / n_ant_frames:.1f} FZ/帧")

    el_grid = np.arange(EL_MIN, EL_MAX + EL_STEP / 2, EL_STEP)   # 31 个默认俯仰

    timetable: list[dict] = []   # 记录每个 mat 的时间范围

    # ── 第 2 遍: 逐天线帧解码 + 写 mat ──────────────────────────────────────
    with open(bin_path, "rb") as f:
        for ai, (i0, i1) in enumerate(zip(boundaries[:-1], boundaries[1:])):
            n_fz = int(i1 - i0)
            f.seek(int(i0) * PKT)
            buf = f.read(n_fz * PKT)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(n_fz, PKT)

            # 提取每 FZ 的关键标量 (偏移与 bin_to_1218_mat.py 一致)
            ant_az = arr[:, 80:84].copy().view("<f4").ravel().astype(np.float64)
            ant_el = arr[:, 84:88].copy().view("<f4").ravel().astype(np.float64)
            lat    = arr[:, 52:56].copy().view("<f4").ravel().astype(np.float64)
            lon    = arr[:, 48:52].copy().view("<f4").ravel().astype(np.float64)
            hdg    = arr[:, 56:60].copy().view("<f4").ravel().astype(np.float64)
            alt    = arr[:, 60:64].copy().view("<f4").ravel().astype(np.float64)
            ts_fz  = ts_all[i0:i1]   # GPS UTC 时间 (HHMMSSMMM 格式)

            # 解和路/差路
            body     = arr[:, 256:5632]   # (n_fz, 5376)
            sum_lin  = np.frombuffer(body[:, 8:8 + 668 * 4].tobytes(),
                                     dtype="<f4").reshape(n_fz, 668)
            diff_lin = np.frombuffer(body[:, 2696:2696 + 668 * 4].tobytes(),
                                     dtype="<f4").reshape(n_fz, 668)
            sum_db  = power_to_db(sum_lin)
            diff_db = power_to_db(diff_lin)

            # 裁到 666 距离单元 (去首尾各 1 个保护单元, 与 1218 一致)
            sum_db_666  = sum_db[:,  1:1 + N_RANGE_OUT]
            diff_db_666 = diff_db[:, 1:1 + N_RANGE_OUT]

            # 把 FZ 按俯仰量化到 EL 栅格
            el_idx = np.round((ant_el - EL_MIN) / EL_STEP).astype(int)
            valid = (el_idx >= 0) & (el_idx < len(el_grid))
            if not valid.all():
                # 超出默认 [-10, +5] 范围时, 自动扩展栅格 (保留所有 FZ)
                this_el_min = float(np.min(ant_el))
                this_el_max = float(np.max(ant_el))
                local_grid = np.arange(
                    np.floor(this_el_min / EL_STEP) * EL_STEP,
                    np.ceil(this_el_max / EL_STEP) * EL_STEP + EL_STEP / 2,
                    EL_STEP)
                el_idx = np.round((ant_el - local_grid[0]) / EL_STEP).astype(int)
                grid_use = local_grid
            else:
                grid_use = el_grid

            n_el = len(grid_use)

            # 构造 Data_Ori cell (n_el × 1)
            data_ori = np.empty((n_el, 1), dtype=object)
            for k in range(n_el):
                sel = np.where(el_idx == k)[0]
                if len(sel) == 0:
                    el_scalar = np.array([[float(grid_use[k])]], dtype=np.float32)
                    az0   = np.zeros((1, 0), dtype=np.float64)
                    diffd = np.zeros((N_RANGE_OUT, 0), dtype=np.float32)
                    sumd  = np.zeros((N_RANGE_OUT, 0), dtype=np.float32)
                    meta  = np.zeros((0, 7), dtype=np.float64)
                else:
                    sel = sel[np.argsort(ant_az[sel])]
                    el_scalar = np.array([[float(grid_use[k])]], dtype=np.float32)
                    az0   = ant_az[sel].reshape(1, -1)         # (1, n_az)
                    diffd = diff_db_666[sel].T.copy()          # (666, n_az)
                    sumd  = sum_db_666[sel].T.copy()           # (666, n_az)
                    # meta: [rangeGate, fLatitude, fLongitude, PlaneCouse, HHeight, PlaneEL, RadarEl]
                    # 纬度/经度直接写入各 FZ 原始值, 不做任何参考帧归零
                    meta = np.zeros((len(sel), 7), dtype=np.float64)
                    meta[:, 0] = 0.0           # rangeGate (1218 全 0)
                    meta[:, 1] = lat[sel]      # fLatitude  — 原始 GPS, 未修改
                    meta[:, 2] = lon[sel]      # fLongitude — 原始 GPS, 未修改
                    meta[:, 3] = hdg[sel]      # PlaneCouse (航向)
                    meta[:, 4] = alt[sel]      # HHeight    (高度)
                    meta[:, 5] = 0.0           # PlaneEL    (载机俯仰, bin 中无此字段)
                    meta[:, 6] = ant_el[sel]   # RadarEl

                cell5 = np.empty((1, 5), dtype=object)
                cell5[0, 0] = el_scalar
                cell5[0, 1] = az0
                cell5[0, 2] = diffd
                cell5[0, 3] = sumd
                cell5[0, 4] = meta
                data_ori[k, 0] = cell5

            out_name = (
                f"mmwave_{ts_tag}_AntFrame{ai:03d}"
                f"_FZ{int(i0):06d}-{int(i1) - 1:06d}.mat"
            )
            out_path = out_dir / out_name
            savemat(str(out_path), {"Data_Ori": data_ori}, do_compression=True)

            # 记录该 mat 的时间范围 (过滤掉全 0 的无效 ts)
            valid_ts = ts_fz[ts_fz > 0]
            ts_first = int(valid_ts[0])  if len(valid_ts) > 0 else 0
            ts_last  = int(valid_ts[-1]) if len(valid_ts) > 0 else 0
            timetable.append({
                "mat":      out_name,
                "fz_start": int(i0),
                "fz_end":   int(i1) - 1,
                "ts_first": ts_first,
                "ts_last":  ts_last,
            })

            if progress_cb is not None:
                progress_cb(ai + 1, n_ant_frames, out_name)

            if ai < 3 or ai == n_ant_frames - 1 or (ai + 1) % 10 == 0:
                print(
                    f"    [{ai + 1:3d}/{n_ant_frames}] FZ {i0}..{i1 - 1}"
                    f" ({n_fz:5d} FZ)  "
                    f"el {ant_el.min():+6.2f}..{ant_el.max():+6.2f}  "
                    f"az {ant_az.min():+7.2f}..{ant_az.max():+7.2f}  "
                    f"→ {out_name}"
                )

    # 写时间表 JSON
    timetable_path = out_dir / "_timetable.json"
    with open(timetable_path, "w", encoding="utf-8") as fp:
        json.dump(timetable, fp, ensure_ascii=False, indent=2)
    print(f"  [完成] {n_ant_frames} 个 mat → {out_dir}")
    print(f"         时间表已写: {timetable_path.name}\n")


def find_bins(root: Path) -> list[Path]:
    """在 root 下递归查找所有 *_mmwave_udp.bin 文件."""
    return sorted(root.rglob("*_mmwave_udp.bin"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="批量将 LH_data_all_sensor 中的 mmwave UDP .bin 转换为 1218-style .mat"
    )
    parser.add_argument(
        "root",
        nargs="?",
        default="L:\\LH_data_all_sensor",
        help="数据集根目录 (默认: L:\\LH_data_all_sensor)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="若 {bin_stem}_radar 目录已有 mat 文件则跳过该 bin",
    )
    args = parser.parse_args()
    root = Path(args.root)

    if not root.exists():
        print(f"[错误] 根目录不存在: {root}", file=sys.stderr)
        sys.exit(1)

    bins = find_bins(root)
    if not bins:
        print(f"[警告] 在 {root} 下未找到任何 *_mmwave_udp.bin 文件")
        sys.exit(0)

    print(f"[发现] {len(bins)} 个 bin 文件, 根目录: {root}\n")

    for i, bin_path in enumerate(bins, 1):
        # 输出目录: 与 bin 同级, 名称 = bin_stem + "_radar"
        out_dir = bin_path.parent / (bin_path.stem + "_radar")
        print(f"[{i}/{len(bins)}] {bin_path.relative_to(root)}")
        print(f"       输出: {out_dir}")

        if args.skip_existing and out_dir.exists():
            existing = list(out_dir.glob("*.mat"))
            if existing:
                print(f"  [跳过] 已有 {len(existing)} 个 mat 文件\n")
                continue

        out_dir.mkdir(parents=True, exist_ok=True)
        try:
            convert_bin(bin_path, out_dir)
        except Exception as exc:
            print(f"  [错误] 处理 {bin_path.name} 时发生异常: {exc}\n",
                  file=sys.stderr)


if __name__ == "__main__":
    main()
