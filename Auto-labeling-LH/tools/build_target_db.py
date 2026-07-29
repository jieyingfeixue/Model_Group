"""
build_target_db.py  —  Step 2：从雷达种子深度构建 GPS 目标深度数据库

原理
----
  无人机抖动导致相机内外参不可靠，方位角估算误差可达 ±10°。
  但雷达 range（深度）精度高，GPS 位置可靠。
  因此利用：
      target_GPS = gps_offset(vehicle_GPS, heading + az_box, depth_m)
  从多帧观测中对目标 GPS 进行聚类平均，消除方位角误差影响。

  • 单帧 GPS 误差 ≈ depth × sin(az_error) ≈ 1500m × sin(10°) ≈ 260m（大）
  • 多帧（≥10 帧）从不同位置/朝向观测 → 平均后误差降至 ~20-50m（可接受）
  • 目标 GPS 确定后，后续任意帧的深度 = haversine(vehicle_GPS, target_GPS)，精度≈GPS精度

输入
----
  {capture_dir}/depth_labels/*.json   —— assign_depth_azimuth 的雷达种子结果
  nav100__fix.csv / nav100__heading.csv  —— 车辆 GPS + 航向角

输出
----
  {capture_dir}/target_depth_db.json

  示例：
  {
    "version": 1,
    "targets": [
      {
        "id": "bui_001",
        "label": "building",
        "lat": 39.12345678, "lon": 116.54321234,
        "gps_std_m": 18.3,        # GPS 聚类标准差（m），越小越可靠
        "n_obs": 47,              # 观测次数
        "mean_depth_m": 1234.0,   # 平均深度（来自雷达 range，可靠）
        "confidence": 0.85,
        "manual": false           # true = 用户手动校正过
      }
    ]
  }

用法
----
  # 单个 capture
  python tools/build_target_db.py --capture-dir "L:/LH_data_all_sensor/4_29/with_cameras_capture_20260429_164703"

  # 全量（遍历 L_ROOT）
  python tools/build_target_db.py --all
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

# ── 常量 ─────────────────────────────────────────────────────────────────────

CLUSTER_RADIUS_M    = 100.0   # 同一目标 GPS 聚类半径（m）；建筑物尺度约 30-80m
MIN_OBS_PER_TARGET  = 1       # 至少有 n 次观测才建立目标（过滤孤立噪点）
FOV_APPROX_DEG      = 8.8     # 精确相机水平 FOV（°），fx=12503.99 计算结果；新版不依赖它
MIN_DEPTH_M         = 50.0    # 最小合理深度（m）
MAX_DEPTH_M         = 5000.0  # 最大合理深度（m）
DB_FILENAME         = "target_depth_db.json"

_RE_CAM_T = re.compile(r'_t([\d.]+)\.jpg$')


# ── GPS 几何工具 ──────────────────────────────────────────────────────────────

def gps_offset(lat: float, lon: float, bearing_deg: float, dist_m: float):
    """从 (lat, lon) 沿 bearing_deg（北起顺时针°）行进 dist_m，返回新 (lat, lon)。"""
    R = 6_371_000.0
    d = dist_m / R
    lr = math.radians(lat)
    nr = math.radians(lon)
    br = math.radians(bearing_deg)
    lat2 = math.asin(math.sin(lr) * math.cos(d) +
                     math.cos(lr) * math.sin(d) * math.cos(br))
    lon2 = nr + math.atan2(math.sin(br) * math.sin(d) * math.cos(lr),
                           math.cos(d) - math.sin(lr) * math.sin(lat2))
    return math.degrees(lat2), math.degrees(lon2)


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点大圆距离（m）。"""
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """从 (lat1, lon1) 到 (lat2, lon2) 的方位角（°，北起顺时针）。"""
    lr1 = math.radians(lat1)
    lr2 = math.radians(lat2)
    dl  = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(lr2)
    x = math.cos(lr1) * math.sin(lr2) - math.sin(lr1) * math.cos(lr2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def gps_to_xy(lat: float, lon: float, ref_lat: float, ref_lon: float):
    """GPS → 以 ref 为原点的局部平面 (E_m, N_m)。"""
    R = 6_371_000.0
    E = R * math.radians(lon - ref_lon) * math.cos(math.radians(ref_lat))
    N = R * math.radians(lat - ref_lat)
    return E, N


# ── nav100 数据加载 ───────────────────────────────────────────────────────────

def load_capture_nav(cap_dir: Path):
    """加载整个 capture 下所有 nav100 GPS + heading 数据（跨所有 part/segment）。

    返回 (ts, lat, lon, ts_h, hdg)，均为 float64 ndarray，已按时间排序。
    """
    ts_all, lat_all, lon_all = [], [], []
    ts_h_all, hdg_all = [], []

    for part_dir in sorted(cap_dir.iterdir()):
        if not part_dir.is_dir() or '_part' not in part_dir.name:
            continue
        for seg_dir in sorted(part_dir.iterdir()):
            if not seg_dir.is_dir() or not seg_dir.name.startswith('segment_'):
                continue
            gps_csv = seg_dir / 'gps'     / 'nav100__fix'     / 'nav100__fix.csv'
            hdg_csv = seg_dir / 'heading' / 'nav100__heading' / 'nav100__heading.csv'
            if gps_csv.exists():
                try:
                    with open(gps_csv, newline='', encoding='utf-8') as fh:
                        for row in csv.DictReader(fh):
                            ts_all.append(float(row['relative_time_sec']))
                            lat_all.append(float(row['latitude']))
                            lon_all.append(float(row['longitude']))
                except Exception:
                    pass
            if hdg_csv.exists():
                try:
                    with open(hdg_csv, newline='', encoding='utf-8') as fh:
                        for row in csv.DictReader(fh):
                            ts_h_all.append(float(row['relative_time_sec']))
                            hdg_all.append(float(row['value']))
                except Exception:
                    pass

    ts  = np.asarray(ts_all,  dtype=np.float64)
    lat = np.asarray(lat_all, dtype=np.float64)
    lon = np.asarray(lon_all, dtype=np.float64)
    ts_h = np.asarray(ts_h_all, dtype=np.float64)
    hdg  = np.asarray(hdg_all,  dtype=np.float64)

    if len(ts) > 0:
        o = np.argsort(ts);  ts, lat, lon = ts[o], lat[o], lon[o]
    if len(ts_h) > 0:
        o = np.argsort(ts_h);  ts_h, hdg = ts_h[o], hdg[o]

    return ts, lat, lon, ts_h, hdg


def _interp_gps_at(t: float, ts, lat, lon, ts_h, hdg):
    """在给定时间点 t 插值出 (v_lat, v_lon, v_hdg)。"""
    v_lat = float(np.interp(t, ts, lat))
    v_lon = float(np.interp(t, ts, lon))
    if len(ts_h) > 0:
        unwrapped = np.unwrap(np.deg2rad(hdg))
        v_hdg = float(np.rad2deg(np.interp(t, ts_h, unwrapped)) % 360.0)
    else:
        v_hdg = 0.0
    return v_lat, v_lon, v_hdg


# ── 简易 DBSCAN（无 sklearn 时的回退实现）──────────────────────────────────────

def _simple_dbscan(pts: np.ndarray, eps: float, min_pts: int) -> np.ndarray:
    n = len(pts)
    labels = np.full(n, -1, dtype=np.int32)
    visited = np.zeros(n, dtype=bool)
    cid = 0
    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        dists = np.linalg.norm(pts - pts[i], axis=1)
        nbrs = np.where(dists <= eps)[0]
        if len(nbrs) < min_pts:
            continue
        labels[nbrs] = cid
        stack = list(nbrs)
        while stack:
            j = stack.pop()
            if not visited[j]:
                visited[j] = True
                d2 = np.linalg.norm(pts - pts[j], axis=1)
                n2 = np.where(d2 <= eps)[0]
                if len(n2) >= min_pts:
                    for k in n2:
                        if labels[k] == -1:
                            labels[k] = cid
                            stack.append(k)
        cid += 1
    return labels


# ── 核心：从 depth_labels 构建 GPS 目标数据库 ─────────────────────────────────

def process_capture(cap_dir: Path, verbose: bool = True) -> dict:
    """为一个 capture 构建 target_depth_db.json，返回 db 字典（空字典表示失败）。"""
    depth_dir = cap_dir / "depth_labels"
    json_paths = sorted(depth_dir.glob("*.json")) if depth_dir.exists() else []
    if not json_paths:
        if verbose:
            print(f"  ⚠ 无 depth_labels/，跳过: {cap_dir.name}")
        return {}

    # ── 加载 nav100 ──────────────────────────────────────────────────────────
    ts_gps, lat_arr, lon_arr, ts_hdg, hdg_arr = load_capture_nav(cap_dir)
    if len(ts_gps) == 0:
        if verbose:
            print(f"  ⚠ 无 nav100 GPS，跳过: {cap_dir.name}")
        return {}

    ref_lat = float(lat_arr.mean())
    ref_lon = float(lon_arr.mean())

    # ── 收集观测 ─────────────────────────────────────────────────────────────
    # obs: {label → [(t_lat, t_lon, depth_m, confidence), ...]}
    obs: dict[str, list] = {}
    n_loaded = 0

    for jpath in json_paths:
        try:
            with open(jpath, encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue

        # 从 camera_name 解析相对时间
        cam_name = data.get("camera_name", "")
        m = _RE_CAM_T.search(cam_name)
        if m:
            t_ref = float(m.group(1))
        else:
            # 回退：用 GPS 序列的中间时间
            t_ref = float(ts_gps[len(ts_gps) // 2])

        v_lat, v_lon, v_hdg = _interp_gps_at(
            t_ref, ts_gps, lat_arr, lon_arr, ts_hdg, hdg_arr)

        # hdg0_deg 来自 mat 元数据（与 nav100 可能有小偏差），优先用 nav100
        if len(ts_hdg) == 0:
            v_hdg = float(data.get("hdg0_deg", v_hdg))

        for box in data.get("boxes", []):
            depth_m = box.get("depth_m")
            if not depth_m or not (MIN_DEPTH_M <= depth_m <= MAX_DEPTH_M):
                continue
            conf    = float(box.get("confidence", 0.1))
            label   = box["label"]
            az_box  = float(box.get("az_box_deg", 0.0))

            # 目标 GPS = 从车辆出发，沿 (heading + az_box) 方向走 depth_m
            world_bearing = (v_hdg + az_box) % 360.0
            t_lat, t_lon  = gps_offset(v_lat, v_lon, world_bearing, depth_m)

            obs.setdefault(label, []).append(
                (t_lat, t_lon, depth_m, conf))
        n_loaded += 1

    n_obs_total = sum(len(v) for v in obs.values())
    if verbose:
        print(f"  加载 {n_loaded}/{len(json_paths)} JSON，"
              f"共 {n_obs_total} 条观测")

    if not obs:
        return {}

    # ── DBSCAN 聚类 → 每簇 = 一个物理目标 ───────────────────────────────────
    targets = []
    tid = 0

    for label, records in sorted(obs.items()):
        lats   = np.array([r[0] for r in records], dtype=np.float64)
        lons   = np.array([r[1] for r in records], dtype=np.float64)
        depths = np.array([r[2] for r in records], dtype=np.float64)
        confs  = np.array([r[3] for r in records], dtype=np.float64)

        # GPS → 局部平面（m）
        EN = np.array([gps_to_xy(la, lo, ref_lat, ref_lon)
                       for la, lo in zip(lats, lons)], dtype=np.float64)

        try:
            from sklearn.cluster import DBSCAN
            cl = DBSCAN(eps=CLUSTER_RADIUS_M,
                        min_samples=MIN_OBS_PER_TARGET).fit_predict(EN)
        except ImportError:
            cl = _simple_dbscan(EN, CLUSTER_RADIUS_M, MIN_OBS_PER_TARGET)

        for cid in sorted(np.unique(cl)):
            if cid == -1:
                continue
            mask = cl == cid
            n    = int(mask.sum())
            if n < MIN_OBS_PER_TARGET:
                continue

            # 加权中值 GPS（权 = confidence × 1/sqrt(n)）
            w = confs[mask] + 1e-9
            w /= w.sum()
            c_lat = float((lats[mask] * w).sum())
            c_lon = float((lons[mask] * w).sum())
            c_depth = float(np.median(depths[mask]))
            c_conf  = float(np.clip(confs[mask].mean() * min(1.0, n / 10.0), 0, 1))

            # GPS 标准差（m）
            gps_errors = [haversine(c_lat, c_lon, la, lo)
                          for la, lo in zip(lats[mask], lons[mask])]
            gps_std = float(np.std(gps_errors)) if len(gps_errors) > 1 else 0.0

            tid += 1
            targets.append({
                "id":           f"{label[:3]}_{tid:03d}",
                "label":        label,
                "lat":          round(c_lat, 8),
                "lon":          round(c_lon, 8),
                "gps_std_m":    round(gps_std, 1),
                "n_obs":        n,
                "mean_depth_m": round(c_depth, 1),
                "confidence":   round(c_conf, 3),
                "manual":       False,
            })

    # 按 label + mean_depth 排序，便于人工查阅
    targets.sort(key=lambda t: (t["label"], t["mean_depth_m"]))

    db = {
        "version":    1,
        "capture_dir": str(cap_dir),
        "n_targets":  len(targets),
        "targets":    targets,
    }
    out_path = cap_dir / DB_FILENAME
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    if verbose:
        print(f"  → {len(targets)} 个目标，写入 {out_path.name}")
    return db


# ── CLI ──────────────────────────────────────────────────────────────────────

def _iter_capture_dirs(root: Path):
    for bp in sorted(root.rglob("*_mmwave_udp.bin")):
        yield bp.parent


def main():
    ap = argparse.ArgumentParser(description="构建 GPS 目标深度数据库")
    ap.add_argument("--capture-dir", type=Path,
                    help="单个 capture 目录（与 --all 二选一）")
    ap.add_argument("--all", action="store_true",
                    help="遍历 L:/LH_data_all_sensor 下所有 capture")
    ap.add_argument("--root", type=Path, default=Path("L:/LH_data_all_sensor"),
                    help="数据集根目录（--all 时使用）")
    ap.add_argument("-v", "--verbose", action="store_true", default=True)
    args = ap.parse_args()

    if args.capture_dir:
        caps = [args.capture_dir]
    elif args.all:
        caps = list(dict.fromkeys(_iter_capture_dirs(args.root)))
    else:
        ap.print_help()
        sys.exit(1)

    print(f"共 {len(caps)} 个 capture\n")
    for cap in caps:
        print(f"[{cap.parent.name}/{cap.name}]")
        try:
            process_capture(cap, verbose=args.verbose)
        except Exception as exc:
            print(f"  [错误] {exc}")
        print()
    print("完成。")


if __name__ == "__main__":
    main()
