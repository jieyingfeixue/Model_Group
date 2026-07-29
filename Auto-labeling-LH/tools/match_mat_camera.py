"""
match_mat_camera.py  —  基于 fz 级别匹配 CSV，为每个 mat 文件找对应相机帧

逻辑：
  mat 文件名如 mmwave_20260429_164703_AntFrame000_FZ001981-003961.mat，
  FZ 编号与 match_radar_camera_anchor.csv 中的 pkt_idx 直接对应。

  步骤：
    ① 读取 match_radar_camera_anchor.csv → pkt_idx 到相机帧的映射表
    ② 扫描 *_mmwave_udp_radar/ 子目录下所有 .mat 文件
    ③ 从文件名解析 FZ 范围 [fz0, fz1_incl]，取中间 FZ = (fz0+fz1_incl)//2
    ④ 查映射表，若中间 FZ 无记录则向两侧扩展最多 50 包寻找最近有效行
    ⑤ 输出 match_mat_camera.csv（与 match_radar_camera_anchor.csv 同级）

输出 CSV 列：
  mat_name         : mat 文件名（不含路径）
  camera_name      : 对应相机帧文件名
  camera_rel_time  : 该相机帧的相对时间（秒）
  nav100_rel_time  : 中间 FZ 的 nav100 插值时间（秒，供参考）
"""

import csv
import re
from pathlib import Path

L_ROOT = Path("L:/LH_data_all_sensor")
SRC_CSV   = "match_radar_camera_anchor.csv"
OUT_CSV   = "match_mat_camera.csv"
RADAR_SFX = "_mmwave_udp_radar"

_RE_FZ = re.compile(r'_FZ(\d+)-(\d+)\.mat$')


# ── 读取 fz 级别 CSV ──────────────────────────────────────────────────────────

def load_fz_map(csv_path: Path) -> dict[int, tuple[str, str, str]]:
    """
    返回 {pkt_idx: (camera_name, camera_rel_time_str, nav100_rel_time_str)}。
    camera_name 为空的行跳过（无有效相机匹配）。
    """
    result: dict[int, tuple[str, str, str]] = {}
    with open(csv_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            cam = row.get('camera_name', '').strip()
            if not cam:
                continue
            try:
                pkt = int(row['pkt_idx'])
            except (KeyError, ValueError):
                continue
            crt = row.get('camera_rel_time', '').strip()
            nrt = row.get('nav100_rel_time', '').strip()
            result[pkt] = (cam, crt, nrt)
    return result


# ── 处理单个 capture 目录 ─────────────────────────────────────────────────────

def process_capture(cap_dir: Path) -> None:
    src_csv = cap_dir / SRC_CSV
    if not src_csv.exists():
        print(f'  ⚠ 缺少 {SRC_CSV}，跳过')
        return

    # 找 radar 子目录
    radar_dirs = [d for d in cap_dir.iterdir()
                  if d.is_dir() and d.name.endswith(RADAR_SFX)]
    if not radar_dirs:
        print(f'  ⚠ 未找到 {RADAR_SFX} 子目录，跳过')
        return
    radar_dir = radar_dirs[0]

    mat_files = sorted(radar_dir.glob('*.mat'))
    if not mat_files:
        print(f'  ⚠ {radar_dir.name} 中无 .mat 文件，跳过')
        return

    # 加载 fz 级别映射
    fz_map = load_fz_map(src_csv)
    if not fz_map:
        print(f'  ⚠ {SRC_CSV} 无有效行，跳过')
        return

    out_rows: list[tuple[str, str, str, str]] = []
    n_miss = 0

    for mat in mat_files:
        m = _RE_FZ.search(mat.name)
        if not m:
            continue

        fz0          = int(m.group(1))
        fz1_incl     = int(m.group(2))   # 文件名中的末位 FZ（inclusive，= i1-1）
        mid_fz       = (fz0 + fz1_incl) // 2
        half_span    = (fz1_incl - fz0) // 2

        # 查中间 FZ；若缺失则向两侧扩展找最近有效记录
        entry = fz_map.get(mid_fz)
        if entry is None:
            for delta in range(1, min(51, half_span + 1)):
                entry = fz_map.get(mid_fz - delta) or fz_map.get(mid_fz + delta)
                if entry:
                    break

        if entry:
            cam_name, cam_rt, nav_rt = entry
            out_rows.append((mat.name, cam_name, cam_rt, nav_rt))
        else:
            out_rows.append((mat.name, '', '', ''))
            n_miss += 1

    out_path = cap_dir / OUT_CSV
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['mat_name', 'camera_name', 'camera_rel_time', 'nav100_rel_time'])
        w.writerows(out_rows)

    hit = len(out_rows) - n_miss
    print(f'  {len(out_rows)} mat，命中 {hit}，未命中 {n_miss}  → {out_path.name}')


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    cap_dirs = []
    for date_dir in sorted(L_ROOT.iterdir()):
        if not date_dir.is_dir():
            continue
        for cap_dir in sorted(date_dir.iterdir()):
            if cap_dir.is_dir() and (cap_dir / SRC_CSV).exists():
                cap_dirs.append(cap_dir)

    print(f'共找到 {len(cap_dirs)} 个 capture 目录\n')
    for cap_dir in cap_dirs:
        print(f'[{cap_dir.parent.name}/{cap_dir.name}]')
        process_capture(cap_dir)
    print('\n全部完成。')


if __name__ == '__main__':
    main()
