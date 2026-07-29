"""毫米波雷达与图像时间对齐 -- 独立脚本（仅 CSV 策略）.

从 lh_adapter.py + gen_radar_camera_match.py 抽出，去除框架耦合，
仅依赖 numpy（标准库）。

对齐原理
--------
使用 radar_camera_match_ts.csv（离线预生成）：

  1. 读取 capture 级 *_mmwave_udp.bin；每包 8624 字节（2156 uint32），
     uint32[11] = ts_hmsm = 当日 GPS 秒数直接整数（CST，非 HHMMSSMMM 编码）。
  2. 读取 nav100__state.csv，构建 GPS_tod_sec -> relative_time_sec 插值表。
  3. 每个 .mat 从文件名解析 FZ 范围(_AntFrameN_FZstart-end)，
     取中间 FZ 的 ts_hmsm -> GPS_tod_sec -> relative_time_sec，
     在 images/ 按最近邻匹配图像，写入 CSV。

CSV 字段：mat_filename, camera_filename, mat_ant_frame, fz_mid,
         mat_gps_tod_sec, mat_rel_time_sec, camera_rel_time_sec, dt_sec

可选航向修正：Δh = hdg_cam(GPS) - hdg_ref(mat 参考束) -> 点云做 Rz(Δh)。

CLI 用法
--------
  gen-csv  --capture-dir <dir>  [--tz-offset -8]  [--dry-run]
  pick     <frame_id>  --seg-dir <dir>  --mmw-dir <dir>
  list     --seg-dir <dir>  --mmw-dir <dir>
"""

from __future__ import annotations
import argparse, csv, re
from pathlib import Path
import numpy as np

_TS_REGEX      = re.compile(r"_t(\d+\.\d+)")
_RE_ANTFRAME   = re.compile(r"_AntFrame(\d+)_FZ(\d+)-(\d+)", re.IGNORECASE)
_STATE_CSV_REL   = Path("nav100_state") / "nav100__state" / "nav100__state.csv"
_HEADING_CSV_REL = Path("heading") / "nav100__heading" / "nav100__heading.csv"
_MATCH_CSV_NAME  = "radar_camera_match_ts.csv"
_IMG_SUBDIRS = ["hikrobot_camera__DA8679038__image_raw",
               "hikrobot_camera__DA8679037__image_raw"]
PKT_SIZE = 8624; PKT_WORDS = 2156; TS_HMSM_IDX = 11


def _natural_key(p):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", p.name)]

def parse_timestamp(name):
    m = _TS_REGEX.search(name)
    return float(m.group(1)) if m else None

def find_images(seg_dir):
    for subdir in _IMG_SUBDIRS:
        d = seg_dir / "images" / subdir
        if not d.exists(): continue
        times, names = [], []
        for p in sorted(d.glob("*.jpg"), key=_natural_key):
            t = parse_timestamp(p.stem)
            if t is not None: times.append(t); names.append(p.name)
        if times:
            arr = np.array(times, np.float64); order = np.argsort(arr)
            return arr[order], [names[i] for i in order]
    return None

def nearest_by_time(arr, names, t):
    i = int(np.argmin(np.abs(arr - t)))
    return names[i], abs(float(arr[i]) - t)

def load_csv_match(seg_dir):
    result = {}
    p = seg_dir / _MATCH_CSV_NAME
    if not p.exists(): return result
    try:
        with open(p, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                result[Path(row["camera_filename"]).stem] = row["mat_filename"]
    except Exception as e: print(f"[WARN] load_csv_match: {e}")
    return result

def pick_mat_for_frame(frame_id, seg_dir, mmw_dir):
    name = load_csv_match(seg_dir).get(frame_id)
    if name:
        c = mmw_dir / name
        return c if c.exists() else None
    return None

def load_bin_timestamps(bin_path, tz_offset_h=0.0):
    """从 UDP bin 提取每个 FZ 包的当日 GPS 秒数（float64）。"""
    n = bin_path.stat().st_size // PKT_SIZE
    raw = np.frombuffer(bin_path.read_bytes(), dtype="<u4")
    ts = raw[:n * PKT_WORDS].reshape(n, PKT_WORDS)[:, TS_HMSM_IDX].astype(np.float64)
    if tz_offset_h: ts += tz_offset_h * 3600.0
    return ts

def load_nav100_state(csv_path):
    """nav100__state.csv -> (gps_tod_arr, rel_time_arr) 升序。"""
    if not csv_path.exists(): return None
    gl, rl = [], []
    try:
        with open(csv_path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                gl.append(float(row["gps_hour"])*3600 + float(row["gps_minute"])*60
                          + float(row["gps_second"]) + float(row["gps_millisecond"])/1000)
                rl.append(float(row["relative_time_sec"]))
    except Exception as e: print(f"[WARN] nav100_state: {e}"); return None
    if not gl: return None
    ga = np.array(gl, np.float64); ra = np.array(rl, np.float64)
    o = np.argsort(ga)
    return ga[o], ra[o]

def gen_csv_for_segment(seg_dir, mat_dir, ts_sec_arr, dry_run=False):
    """为单个 segment 生成 radar_camera_match_ts.csv。返回写入行数。"""
    nav = load_nav100_state(seg_dir / _STATE_CSV_REL)
    if nav is None: print(f"  [skip] {seg_dir.name}: no nav100__state.csv"); return 0
    gps_tod_arr, rel_time_arr = nav
    seg_t0 = float(rel_time_arr.min()); seg_t1 = float(rel_time_arr.max())
    gps_t0 = float(gps_tod_arr.min());  gps_t1 = float(gps_tod_arr.max())
    img = find_images(seg_dir)
    if img is None: print(f"  [skip] {seg_dir.name}: no images"); return 0
    img_times, img_names = img
    n_pkt = len(ts_sec_arr); rows = []
    for mp in sorted(mat_dir.glob("*.mat"), key=_natural_key):
        m = _RE_ANTFRAME.search(mp.name)
        if not m: continue
        af = int(m.group(1)); fz_mid = (int(m.group(2)) + int(m.group(3))) // 2
        if fz_mid >= n_pkt: continue
        gtm = float(ts_sec_arr[fz_mid])
        if not (gps_t0-1 <= gtm <= gps_t1+1): continue
        mr = float(np.interp(gtm, gps_tod_arr, rel_time_arr))
        if not (seg_t0-1 <= mr <= seg_t1+1): continue
        cn, dt = nearest_by_time(img_times, img_names, mr)
        cr = float(img_times[img_names.index(cn)])
        rows.append(dict(mat_filename=mp.name, camera_filename=cn, mat_ant_frame=af,
                         fz_mid=fz_mid, mat_gps_tod_sec=round(gtm,4),
                         mat_rel_time_sec=round(mr,4), camera_rel_time_sec=round(cr,4),
                         dt_sec=round(dt,4)))
    if not rows:
        print(f"  [empty] {seg_dir.name}: no mats in GPS range [{gps_t0:.1f},{gps_t1:.1f}]s")
        return 0
    dts = [r["dt_sec"] for r in rows]
    if dry_run:
        print(f"  [dry] {seg_dir.name}: {len(rows)} pairs  max_dt={max(dts):.3f}s"); return 0
    fn = ["mat_filename","camera_filename","mat_ant_frame","fz_mid",
          "mat_gps_tod_sec","mat_rel_time_sec","camera_rel_time_sec","dt_sec"]
    with open(seg_dir / _MATCH_CSV_NAME, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fn); w.writeheader(); w.writerows(rows)
    print(f"  {seg_dir.name}: {len(rows)} rows  max_dt={max(dts):.3f}s  mean_dt={sum(dts)/len(dts):.3f}s")
    return len(rows)

def load_heading_at(seg_dir, t_ref):
    """从 nav100__heading.csv 插值 t_ref 时刻的 GPS 航向角 (°)。"""
    p = seg_dir / _HEADING_CSV_REL
    if not p.exists(): return None
    ht, hv = [], []
    try:
        with open(p, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ht.append(float(row["relative_time_sec"])); hv.append(float(row["value"]))
    except Exception: return None
    return float(np.interp(t_ref, np.array(ht, np.float64), np.array(hv, np.float64))) if ht else None

def apply_heading_correction(pts, hdg_cam_deg, hdg_ref_deg, min_delta_deg=0.5):
    """点云绕 Z 轴旋转 Δh = hdg_cam - hdg_ref。pts: (N,4)[x,y,z,dB]。"""
    dh = (hdg_cam_deg - hdg_ref_deg + 180.0) % 360.0 - 180.0
    if abs(dh) < min_delta_deg: return pts
    c, s = float(np.cos(np.deg2rad(dh))), float(np.sin(np.deg2rad(dh)))
    out = pts.copy(); xr, yr = pts[:,0].copy(), pts[:,1].copy()
    out[:,0] = c*xr - s*yr; out[:,1] = s*xr + c*yr
    return out


def _main():
    ap = argparse.ArgumentParser(description="mmwave <-> image 时间对齐（基于 CSV）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pg = sub.add_parser("gen-csv", help="生成 radar_camera_match_ts.csv")
    pg.add_argument("--capture-dir", type=Path, required=True)
    pg.add_argument("--tz-offset", type=float, default=0.0, metavar="HOURS",
                    help="bin 与 nav100 时区差（小时），如 bin=CST nav100=UTC 传 -8.0")
    pg.add_argument("--dry-run", action="store_true")

    pp = sub.add_parser("pick", help="frame_stem -> mat（依赖已有 CSV）")
    pp.add_argument("frame_id"); pp.add_argument("--seg-dir", type=Path, required=True)
    pp.add_argument("--mmw-dir", type=Path, required=True)

    pl = sub.add_parser("list", help="打印 segment 内所有 frame->mat 对照")
    pl.add_argument("--seg-dir", type=Path, required=True)
    pl.add_argument("--mmw-dir", type=Path, required=True)

    args = ap.parse_args()

    if args.cmd == "gen-csv":
        cd = args.capture_dir
        bins = list(cd.glob("*_mmwave_udp.bin"))
        if not bins: print("[ERROR] no *_mmwave_udp.bin"); return
        ts = load_bin_timestamps(bins[0], args.tz_offset)
        print(f"Loaded {len(ts)} FZ packets from {bins[0].name}")
        md = next((d for d in cd.iterdir() if d.is_dir() and d.name.endswith("_radar")), None)
        if not md: print("[ERROR] no *_radar dir"); return
        total = 0
        for child in sorted(cd.iterdir(), key=_natural_key):
            if not child.is_dir(): continue
            segs = ([child] if child.name.startswith("segment_")
                    else sorted((s for s in child.iterdir()
                                 if s.is_dir() and s.name.startswith("segment_")), key=_natural_key))
            for seg in segs: total += gen_csv_for_segment(seg, md, ts, args.dry_run)
        print(f"Done. Total rows: {total}")

    elif args.cmd == "pick":
        mat = pick_mat_for_frame(args.frame_id, args.seg_dir, args.mmw_dir)
        print(f"frame: {args.frame_id}")
        print(f"mat  : {mat.name if mat else 'Not found'}")

    elif args.cmd == "list":
        cp = args.seg_dir / _MATCH_CSV_NAME
        if not cp.exists(): print("[ERROR] no radar_camera_match_ts.csv"); return
        print(f"{'frame_stem':<60} {'mat_filename':<55} dt_sec")
        print("-" * 125)
        with open(cp, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                stem = Path(row["camera_filename"]).stem
                print(f"{stem:<60} {row['mat_filename']:<55} {row['dt_sec']}")

if __name__ == "__main__":
    _main()
