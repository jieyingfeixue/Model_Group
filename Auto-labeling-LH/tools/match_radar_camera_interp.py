"""
match_radar_camera_interp.py  —  方法1：W12 GPS 整秒 → nav100 线性插值

逻辑：
  每个 UDP 包的 W12 字段（offset 44）存储 GPS_CST 整秒值。
  通过 nav100__state.csv 建立 GPS_CST → relative_time_sec 的插值表，
  将每包的 W12 映射到 rel_time，再在相机列表中找最近帧。

  注意：同一 GPS 整秒内的所有包得到相同的 rel_time（W12 的精度限制）。

输出 CSV（存于每个 bin 文件同级目录，文件名与脚本名相同）：
  antframe        : 该包所属的 AntFrame 序号（0-based）
  pkt_idx         : 包在 bin 文件中的序号（0-based）
  nav100_rel_time : 通过 nav100 插值得到的相对时间（秒，相对于本 part 起始）
  camera_name     : 最近相机帧文件名（相对于 images/ 的路径）
  camera_rel_time : 该相机帧的相对时间（秒）
"""

import csv
import re
import sys
from pathlib import Path

import numpy as np

# ── 常量配置 ─────────────────────────────────────────────────────────────────
PKT       = 8624               # 每个 UDP 包字节数
PKT_WORDS = PKT // 4           # 以 uint32 为单位

CAM_SUBDIR = "hikrobot_camera__DA8679037__image_raw"   # 使用标注相机

L_ROOT = Path("L:/LH_data_all_sensor")

_RE_CAM_T = re.compile(r'_t([\d.]+)\.jpg$')

SCRIPT_STEM = Path(__file__).stem   # "match_radar_camera_interp"


# ── 工具函数 ─────────────────────────────────────────────────────────────────

def decode_w12(raw_arr: np.ndarray) -> np.ndarray:
    """W12 原始值已是 GPS_CST 整数秒（北京时间当日秒数），直接返回。"""
    return raw_arr.astype(np.float64)


def load_nav_csv(csv_path: Path):
    """
    读取 nav100__state.csv。
    返回 (gps_cst_arr, rel_time_arr) 按 gps_cst 升序排列，或 None。
    """
    gps_list, rel_list = [], []
    with open(csv_path, newline='', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                g = (int(row['gps_hour'])   * 3600
                     + int(row['gps_minute']) * 60
                     + int(row['gps_second'])
                     + int(row['gps_millisecond']) / 1000.0
                     + 28800.0)
                r = float(row['relative_time_sec'])
                gps_list.append(g)
                rel_list.append(r)
            except (KeyError, ValueError):
                pass
    if not gps_list:
        return None
    g_arr = np.array(gps_list, dtype=np.float64)
    r_arr = np.array(rel_list, dtype=np.float64)
    order = np.argsort(g_arr)
    return g_arr[order], r_arr[order]


def load_cams(cam_dir: Path):
    """
    扫描相机图像目录，从文件名提取 rel_time。
    返回 (rel_time_arr, names_list)，按 rel_time 升序排列。
    """
    times, names = [], []
    if not cam_dir.exists():
        return np.empty(0, dtype=np.float64), []
    for f in cam_dir.iterdir():
        m = _RE_CAM_T.search(f.name)
        if m:
            times.append(float(m.group(1)))
            names.append(f.name)
    if not times:
        return np.empty(0, dtype=np.float64), []
    order  = np.argsort(times)
    t_arr  = np.array(times, dtype=np.float64)[order]
    n_list = [names[i] for i in order]
    return t_arr, n_list


def nearest_cam_vectorized(rt_arr: np.ndarray, cam_t: np.ndarray, cam_n: list):
    """
    向量化最近邻相机帧查找（搜索树 searchsorted）。
    返回 (names_ndarray_of_object, cam_rt_ndarray)。
    """
    idx   = np.searchsorted(cam_t, rt_arr).clip(0, len(cam_t) - 1)
    idx_l = (idx - 1).clip(0, len(cam_t) - 1)
    best  = np.where(
        np.abs(cam_t[idx_l] - rt_arr) < np.abs(cam_t[idx] - rt_arr),
        idx_l, idx
    )
    cam_n_arr = np.array(cam_n, dtype=object)
    return cam_n_arr[best], cam_t[best]


# ── PartData：合并一个 part 下所有 segment 的 nav100 + 相机 ──────────────────

class PartData:
    __slots__ = ['name', 'gps_arr', 'rel_arr', 'cam_t', 'cam_n', 'gps_min', 'gps_max']

    def __init__(self, name: str):
        self.name    = name
        self.gps_arr = np.empty(0, dtype=np.float64)
        self.rel_arr = np.empty(0, dtype=np.float64)
        self.cam_t   = np.empty(0, dtype=np.float64)
        self.cam_n: list[str] = []
        self.gps_min = np.inf
        self.gps_max = -np.inf


def load_capture(cap_dir: Path) -> list[PartData]:
    """
    扫描 capture 目录下所有 part 子目录，
    每个 part 合并其 segment 中的 nav100 和相机数据。
    """
    parts: list[PartData] = []
    for pdir in sorted(cap_dir.iterdir()):
        if not pdir.is_dir() or '_part' not in pdir.name:
            continue

        pd = PartData(pdir.name)
        g_segs, r_segs, ct_segs, cn_all = [], [], [], []

        for seg in sorted(pdir.iterdir()):
            if not seg.is_dir() or not seg.name.startswith('segment_'):
                continue
            nav_csv = seg / 'nav100_state' / 'nav100__state' / 'nav100__state.csv'
            if not nav_csv.exists():
                continue
            res = load_nav_csv(nav_csv)
            if res is None:
                continue
            g_segs.append(res[0])
            r_segs.append(res[1])
            ct, cn = load_cams(seg / 'images' / CAM_SUBDIR)
            ct_segs.append(ct)
            cn_all.extend(cn)

        if not g_segs:
            continue

        g_all = np.concatenate(g_segs)
        r_all = np.concatenate(r_segs)
        order = np.argsort(g_all)
        pd.gps_arr = g_all[order]
        pd.rel_arr = r_all[order]

        if ct_segs:
            ct_all = np.concatenate(ct_segs)
            co = np.argsort(ct_all)
            pd.cam_t = ct_all[co]
            pd.cam_n = [cn_all[i] for i in co]

        pd.gps_min = float(pd.gps_arr[0])
        pd.gps_max = float(pd.gps_arr[-1])
        parts.append(pd)

    return parts


# ── 主处理函数 ───────────────────────────────────────────────────────────────

def process_bin(bin_path: Path, parts: list[PartData]) -> Path:
    n_bytes = bin_path.stat().st_size
    n_pkts  = n_bytes // PKT
    if n_pkts == 0:
        return None

    mm = np.memmap(str(bin_path), dtype='<u4', mode='r', shape=(n_pkts, PKT_WORDS))

    # AntFrame 序号（累计 start_flag）
    start_mask  = (mm[:, 6] == 1).astype(np.int32)
    antframe_arr = np.maximum(np.cumsum(start_mask) - 1, 0)

    # 每包 GPS_CST 秒
    gps_cst_all = decode_w12(mm[:, 11])
    del mm

    # 输出数组
    rel_time_out  = np.full(n_pkts, np.nan, dtype=np.float64)
    cam_names_out = np.empty(n_pkts, dtype=object)
    cam_names_out[:] = ''
    cam_rt_out    = np.full(n_pkts, np.nan, dtype=np.float64)

    # 按 part 分组插值 + 相机匹配
    for p in parts:
        mask = (gps_cst_all >= p.gps_min) & (gps_cst_all <= p.gps_max)
        if not mask.any() or len(p.gps_arr) < 2:
            continue
        pki = np.where(mask)[0]
        rt  = np.interp(gps_cst_all[pki], p.gps_arr, p.rel_arr)
        rel_time_out[pki] = rt

        if len(p.cam_t) > 0:
            valid     = ~np.isnan(rt)
            if valid.any():
                names, crt = nearest_cam_vectorized(rt[valid], p.cam_t, p.cam_n)
                cam_names_out[pki[valid]] = names
                cam_rt_out[pki[valid]]    = crt

    # 写出 CSV（批量构建行列表，一次性写入，减少网络驱动器 IO 次数）
    out_path = bin_path.parent / f'{SCRIPT_STEM}.csv'
    rt_strs  = np.where(np.isnan(rel_time_out),  '', np.char.mod('%.4f', rel_time_out))
    crt_strs = np.where(np.isnan(cam_rt_out),    '', np.char.mod('%.4f', cam_rt_out))
    lines = ['antframe,pkt_idx,nav100_rel_time,camera_name,camera_rel_time\n']
    lines += [
        f'{antframe_arr[i]},{i},{rt_strs[i]},{cam_names_out[i]},{crt_strs[i]}\n'
        for i in range(n_pkts)
    ]
    with open(out_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)

    return out_path


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main():
    bin_files = sorted(L_ROOT.rglob('*_mmwave_udp.bin'))
    print(f'共找到 {len(bin_files)} 个 bin 文件\n')

    for bin_path in bin_files:
        cap_dir = bin_path.parent
        print(f'[{cap_dir.parent.name}/{cap_dir.name}]', end='  ', flush=True)

        parts = load_capture(cap_dir)
        if not parts:
            print('⚠ 无 part 目录，跳过')
            continue

        n_pkts = bin_path.stat().st_size // PKT
        print(f'{n_pkts} 包 | {len(parts)} part(s) | nav100 GPS 范围: '
              f'{parts[0].gps_min:.0f}–{parts[-1].gps_max:.0f}', flush=True)

        out = process_bin(bin_path, parts)
        if out:
            print(f'  → 写出: {out.name}')

    print('\n全部完成。')


if __name__ == '__main__':
    main()
