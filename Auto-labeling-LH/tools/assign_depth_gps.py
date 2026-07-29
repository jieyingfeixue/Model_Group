"""
assign_depth_gps.py  —  GPS 射线匹配深度赋值（无需雷达-相机标定）

策略：
  1. 从 capture 下 **所有** mat 文件提取 GPS 目标点图 (lat, lon, dB)
  2. 从各 segment 的 nav100__state.csv 建立时间→车辆位姿索引
  3. 对每个相机标注帧（按 t_rel 插值车辆 lat/lon/heading）：
     a. 由标注框像素中心计算相机空间方位角 box_az_cam
     b. world_az = vehicle_heading + box_az_cam（相机近似朝车头）
     c. 在 GPS 目标点图中按方位角 + 距离搜索最佳匹配
     d. depth = GPS 欧氏距离（m）
  4. 结果写入 {capture_dir}/depth_labels/{camera_stem}.json
     （与 assign_depth_azimuth.py 输出兼容，boxes 格式相同）

与 assign_depth_azimuth.py 的主要区别：
  * 不需要 delta_az 雷达天线标定
  * 用所有 mat 的 GPS 目标（更多雷达数据覆盖）
  * 对所有有标注的相机帧均可生成（不限于 CSV 中已匹配的帧）
"""

from __future__ import annotations

import csv
import json
import math
import re
import sys
from pathlib import Path
from typing import Optional

import numpy as np

# ── 路径设置 ──────────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

# ── 常量 ─────────────────────────────────────────────────────────────────────
_R_EARTH_EQ = 6_378_137.0    # m (赤道半径)
_R_EARTH_POL = 6_356_752.3   # m (极半径)
_RADAR_MAX_RANGE_M = 4000.0
_RADAR_MAX_POINTS = 3000     # 每个 mat 最多保留 N 个最强点
_FOV_H_DEG = 8.78            # 75mm 长焦相机水平 FoV（°）, fx=12503.99 精确计算
_CAMERA_HFOV_DEG = 8.78   # 75mm 长焦实测水平视场, fx=12503.99 → 2*atan(1920/(2*12504))≈8.78°
_CAMERA_VFOV_DEG = 7.3       # 75mm 长焦实测垂直视场
_AZ_TOL_DEG = 8.0            # 方位角匹配容差（°）
_MIN_DEPTH_M = 400.0         # 长焦相机不可见近场，硬过滤 400m 内回波
_CAMERA_MOUNT_YAW_DEG = 0.0  # 相机安装偏角（°），近似为 0（正向安装）

_STATE_CSV = Path("nav100_state") / "nav100__state" / "nav100__state.csv"
_RE_CAMERA_TREL = re.compile(r"_t(\d+\.\d+)(?:\.\w+)?$")
_RE_ANNOT_STEM = re.compile(r"hikrobot_camera__DA8679037__image_raw_\d+_t\d+\.\d+$")


# ── nav100 时间索引 ───────────────────────────────────────────────────────────

def build_nav100_index(capture_dir: Path):
    """扫描 capture 下所有 segment 的 nav100__state.csv 建立时间索引.

    Returns (t_arr, lat_arr, lon_arr, hdg_arr) 均按 t_arr 升序, 或 None.
    """
    ts, lats, lons, alts, pitches, hdgs = [], [], [], [], [], []
    for seg in sorted(capture_dir.rglob("segment_*"), key=lambda p: p.name):
        if not seg.is_dir():
            continue
        csv_path = seg / _STATE_CSV
        if not csv_path.exists():
            continue
        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    try:
                        ts.append(float(row["relative_time_sec"]))
                        lats.append(float(row["latitude"]))
                        lons.append(float(row["longitude"]))
                        alts.append(float(row.get("altitude", row.get("gps_altitude", 0.0))))
                        pitches.append(math.degrees(float(row.get("pitch", 0.0))))
                        hdgs.append(float(row.get("true_heading_deg", 0.0)))
                    except (KeyError, ValueError):
                        continue
        except Exception:
            continue
    if not ts:
        return None
    t_arr = np.asarray(ts)
    order = np.argsort(t_arr)
    return (
        t_arr[order],
        np.asarray(lats)[order],
        np.asarray(lons)[order],
        np.asarray(alts)[order],
        np.asarray(pitches)[order],
        np.asarray(hdgs)[order],
    )


def interp_vehicle_pose(
    t: float,
    nav: "tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]",
) -> "tuple[float, float, float] | None":
    """在 nav 时间索引中插值 (lat, lon, heading_deg). t 超出范围时用端点值."""
    if nav is None:
        return None
    t_arr, lat_arr, lon_arr, alt_arr, pitch_arr, hdg_arr = nav
    i = int(np.searchsorted(t_arr, t))
    if i == 0:
        return (
            float(lat_arr[0]), float(lon_arr[0]), float(alt_arr[0]),
            float(pitch_arr[0]), float(hdg_arr[0]),
        )
    if i >= len(t_arr):
        return (
            float(lat_arr[-1]), float(lon_arr[-1]), float(alt_arr[-1]),
            float(pitch_arr[-1]), float(hdg_arr[-1]),
        )
    t0, t1 = float(t_arr[i - 1]), float(t_arr[i])
    alpha = (t - t0) / (t1 - t0) if (t1 - t0) > 1e-9 else 0.0
    lat = float(lat_arr[i - 1]) + alpha * float(lat_arr[i] - lat_arr[i - 1])
    lon = float(lon_arr[i - 1]) + alpha * float(lon_arr[i] - lon_arr[i - 1])
    alt = float(alt_arr[i - 1]) + alpha * float(alt_arr[i] - alt_arr[i - 1])
    pitch = float(pitch_arr[i - 1]) + alpha * float(pitch_arr[i] - pitch_arr[i - 1])
    # 航向角插值需处理跨 360° 的情况
    h0, h1 = float(hdg_arr[i - 1]), float(hdg_arr[i])
    dh = (h1 - h0 + 180.0) % 360.0 - 180.0  # [-180, 180]
    hdg = h0 + alpha * dh
    return lat, lon, alt, pitch, hdg


# ── GPS 目标点图 ──────────────────────────────────────────────────────────────

def build_gps_target_map(capture_dir: Path, verbose: bool = True) -> np.ndarray:
    """从 capture 下所有 mat 文件提取 GPS 目标点 (lat, lon, dB).

    Returns (N, 3) float32. 使用 lh_adapter._load_mmwave_enu_pts 与地图模式一致.
    """
    from src.io.adapters.lh_adapter import _load_mmwave_enu_pts, _find_radar_dir

    radar_dir = _find_radar_dir(capture_dir)
    if radar_dir is None or not radar_dir.exists():
        if verbose:
            print("  [GPS图] 未找到 radar 目录")
        return np.empty((0, 4), dtype=np.float32)

    mat_files = sorted(radar_dir.glob("*.mat"))
    if not mat_files:
        return np.empty((0, 4), dtype=np.float32)

    if verbose:
        print(f"  [GPS图] 从 {len(mat_files)} 个 mat 提取目标点...")

    chunks: list[np.ndarray] = []
    for i, mp in enumerate(mat_files):
        try:
            pts, _, _ = _load_mmwave_enu_pts(mp)   # (N, 4) [lat, lon, U, dB]
            if len(pts) > 0:
                chunks.append(pts[:, :4])
        except Exception:
            pass
        if verbose and (i + 1) % 30 == 0:
            print(f"    {i + 1}/{len(mat_files)} ...")

    if not chunks:
        return np.empty((0, 4), dtype=np.float32)

    merged = np.concatenate(chunks, axis=0).astype(np.float32)
    if verbose:
        print(f"  [GPS图] 共 {len(merged):,} 个目标点 (来自 {len(mat_files)} 个 mat)")
    return merged


# ── GPS 射线深度赋值 ──────────────────────────────────────────────────────────

def assign_depth_gps_ray(
    shapes: list,
    annot_w: int,
    annot_h: int,
    vehicle_lat: float,
    vehicle_lon: float,
    vehicle_alt_m: float,
    vehicle_pitch_deg: float,
    vehicle_hdg_deg: float,
    gps_targets: np.ndarray,   # (N, 4) [lat, lon, U_abs, dB]
    fov_h_deg: float = _FOV_H_DEG,
    az_tol_deg: float = _AZ_TOL_DEG,
    camera_mount_yaw_deg: float = _CAMERA_MOUNT_YAW_DEG,
    temporal_state: "list[dict] | None" = None,
) -> list:
    """对一帧的每个标注框用 GPS 射线匹配深度.

    返回 boxes list（格式与 assign_depth_azimuth 的 boxes 兼容）.
    """
    if len(gps_targets) == 0 or not shapes:
        return []

    # 把所有目标 GPS 转换为相对车辆的 ENU (east_m, north_m, dist_m, az_deg)
    coslat_v = math.cos(math.radians(vehicle_lat))
    dlat = gps_targets[:, 0].astype(np.float64) - vehicle_lat
    dlon = (gps_targets[:, 1].astype(np.float64) - vehicle_lon) * coslat_v
    dN = dlat * (math.pi / 180.0) * _R_EARTH_POL
    dE = dlon * (math.pi / 180.0) * _R_EARTH_EQ
    dist = np.sqrt(dN ** 2 + dE ** 2)

    # 方位角（以北为 0，顺时针为正）
    target_az_deg = np.degrees(np.arctan2(dE, dN))   # [-180, 180]

    # 过滤极近/极远目标
    valid_mask = (dist >= _MIN_DEPTH_M) & (dist < _RADAR_MAX_RANGE_M)
    if not valid_mask.any():
        return []

    if gps_targets.shape[1] >= 4:
        altitude = gps_targets[:, 2].astype(np.float64)
        strength = gps_targets[:, 3].astype(np.float64)
    else:
        altitude = np.zeros(len(gps_targets), dtype=np.float64)
        strength = gps_targets[:, 2].astype(np.float64)
    valid_mask &= altitude >= 0.0
    if not valid_mask.any():
        return []
    dist_v = dist[valid_mask]
    az_v = target_az_deg[valid_mask]
    alt_v = altitude[valid_mask]
    dB_v = strength[valid_mask]
    elevation_v = np.degrees(np.arctan2(alt_v - vehicle_alt_m, dist_v))

    # Estimate frame-wide camera yaw from a 0.5-degree radar bearing histogram.
    # This stays fast even when the accumulated GPS target map has >1M points.
    box_azimuths = []
    for shape in shapes:
        pts = shape.get("points", [])
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        cx = (min(xs) + max(xs)) / 2.0
        box_azimuths.append((cx / max(annot_w, 1) - 0.5) * fov_h_deg)

    camera_yaw_offset = 0.0
    if box_azimuths:
        bin_size = 0.5
        n_bins = int(360.0 / bin_size)
        bin_ids = np.floor((az_v + 180.0) / bin_size).astype(np.int64) % n_bins
        compensated = dB_v + 40.0 * np.log10(
            np.maximum(dist_v, 1.0) / _MIN_DEPTH_M
        )
        peak = np.full(n_bins, -np.inf, dtype=np.float64)
        np.maximum.at(peak, bin_ids, compensated)
        occupied = np.bincount(bin_ids, minlength=n_bins) > 0
        radius_bins = int(round(4.0 / bin_size))

        best_key = (-1, -float("inf"), -float("inf"))
        for offset in np.arange(-180.0, 180.01, 0.5):
            values = []
            for box_az in box_azimuths:
                ray = vehicle_hdg_deg + camera_mount_yaw_deg + box_az + offset
                center = int(math.floor(((ray + 180.0) % 360.0) / bin_size))
                ids = (center + np.arange(-radius_bins, radius_bins + 1)) % n_bins
                valid_ids = ids[occupied[ids]]
                if len(valid_ids):
                    values.append(float(np.max(peak[valid_ids])))
            key = (
                len(values),
                float(np.mean(values)) if values else -float("inf"),
                -abs(float(offset)),
            )
            if key > best_key:
                best_key = key
                camera_yaw_offset = float(offset)

    camera_center_az = vehicle_hdg_deg + camera_mount_yaw_deg + camera_yaw_offset
    horizontal_error = (az_v - camera_center_az + 180.0) % 360.0 - 180.0
    horizontal_fov = np.abs(horizontal_error) <= (_CAMERA_HFOV_DEG * 0.6)

    # Estimate camera mounting pitch from box vertical positions and radar elevation.
    box_elevations = []
    for shape in shapes:
        pts = shape.get("points", [])
        if len(pts) < 2:
            continue
        ys = [p[1] for p in pts]
        cy = (min(ys) + max(ys)) / 2.0
        box_elevations.append((0.5 - cy / max(annot_h, 1)) * _CAMERA_VFOV_DEG)
    camera_pitch_offset = 0.0
    if box_elevations and horizontal_fov.any():
        best = (-1, -float("inf"), -float("inf"))
        elev_h = elevation_v[horizontal_fov]
        strength_h = dB_v[horizontal_fov]
        for offset in np.arange(-45.0, 45.01, 0.5):
            values = []
            for box_el in box_elevations:
                expected = vehicle_pitch_deg + float(offset) + box_el
                mask = np.abs(elev_h - expected) <= 2.0
                if mask.any():
                    values.append(float(np.percentile(strength_h[mask], 90)))
            key = (len(values), float(np.mean(values)) if values else -float("inf"), -abs(offset))
            if key > best:
                best = key
                camera_pitch_offset = float(offset)

    camera_center_pitch = vehicle_pitch_deg + camera_pitch_offset
    vertical_fov = np.abs(elevation_v - camera_center_pitch) <= (_CAMERA_VFOV_DEG * 0.6)
    in_camera_fov = horizontal_fov & vertical_fov
    dist_v, az_v, dB_v = dist_v[in_camera_fov], az_v[in_camera_fov], dB_v[in_camera_fov]
    elevation_v = elevation_v[in_camera_fov]
    if len(dist_v) == 0:
        return []

    from src.fusion.radar_depth_layers import select_depth_layer

    boxes = []
    next_state: list[dict] = []

    def _previous_depth(label: str, cx_norm: float) -> float | None:
        if not temporal_state:
            return None
        candidates = [
            row for row in temporal_state
            if row["label"] == label and abs(row["cx"] - cx_norm) <= 0.2
        ]
        if not candidates:
            return None
        return float(min(candidates, key=lambda row: abs(row["cx"] - cx_norm))["depth_m"])

    for shape in shapes:
        pts = shape.get("points", [])
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        cx = (min(xs) + max(xs)) / 2.0
        cy = (min(ys) + max(ys)) / 2.0
        cx_norm = cx / max(annot_w, 1)
        label = shape.get("label", "")

        # 标注框相机空间方位角 (0=中心, 负=左, 正=右)
        box_az_cam = (cx / max(annot_w, 1) - 0.5) * fov_h_deg

        # 世界坐标方位角 = 车辆航向 + 相机安装偏角 + 框方位角
        world_az = (
            vehicle_hdg_deg + camera_mount_yaw_deg
            + box_az_cam + camera_yaw_offset
        )

        # 计算目标方位角与射线方向的偏差（处理跨 360°）
        az_diff = az_v - world_az
        az_diff = (az_diff + 180.0) % 360.0 - 180.0   # [-180, 180]
        box_el_cam = (0.5 - cy / max(annot_h, 1)) * _CAMERA_VFOV_DEG
        world_el = camera_center_pitch + box_el_cam
        el_diff = elevation_v - world_el
        box_h_half = max(
            0.45,
            0.5 * (max(xs) - min(xs)) / max(annot_w, 1) * _CAMERA_HFOV_DEG + 0.35,
        )
        box_v_half = max(
            0.45,
            0.5 * (max(ys) - min(ys)) / max(annot_h, 1) * _CAMERA_VFOV_DEG + 0.35,
        )
        in_cone = (np.abs(az_diff) <= box_h_half) & (np.abs(el_diff) <= box_v_half)

        if not in_cone.any():
            continue

        cone_idx = np.where(in_cone)[0]
        layer = select_depth_layer(
            dist_v[cone_idx],
            dB_v[cone_idx],
            np.abs(az_diff[cone_idx]),
            previous_depth_m=_previous_depth(label, cx_norm),
        )
        if layer is None:
            continue

        depth_m = float(layer["depth_m"])
        layer_mask = np.abs(dist_v[cone_idx] - depth_m) <= max(45.0, depth_m * 0.055)
        layer_az = az_v[cone_idx][layer_mask]
        world_az_best = float(np.median(layer_az)) if len(layer_az) else float(world_az)

        boxes.append({
            "label": label,
            "bbox_xyxy": [
                round(min(xs), 1), round(min(ys), 1),
                round(max(xs), 1), round(max(ys), 1),
            ],
            "az_box_deg": round(box_az_cam, 2),
            "world_az_deg": round(world_az, 2),
            "world_el_deg": round(world_el, 2),
            "target_az_deg": round(world_az_best, 2),
            "depth_m": round(depth_m, 1),
            "camera_yaw_offset_deg": round(camera_yaw_offset, 2),
            "camera_pitch_offset_deg": round(camera_pitch_offset, 2),
            "depth_cluster_points": layer["n_points"],
            "depth_cluster_spread_m": round(layer["spread_m"], 1),
            "method": "gps_ray_clustered",
        })
        next_state.append({"label": label, "cx": cx_norm, "depth_m": depth_m})

    if temporal_state is not None:
        temporal_state[:] = next_state
    return boxes


# ── 标注 JSON 索引 ────────────────────────────────────────────────────────────

def _build_annot_stem_index(annot_root: Path) -> "dict[str, Path]":
    """递归扫描 annot_root 下所有 hikrobot 标注 JSON，返回 {stem: path}."""
    index: dict[str, Path] = {}
    if not annot_root.exists():
        return index
    for p in annot_root.rglob("hikrobot_camera__DA8679037__image_raw/*.json"):
        index[p.stem] = p
    return index


def _parse_camera_t_rel(camera_name: str) -> "float | None":
    """从相机文件名（或 stem）解析 t_rel (秒)。失败返回 None.

    不使用 Path.stem，因为时间戳如 t000003.285 中的 .285 会被 pathlib 误识别为扩展名。
    """
    # 先尝试在原始字符串上匹配 (stem 情况)
    m = _RE_CAMERA_TREL.search(camera_name)
    if m:
        return float(m.group(1))
    # 再尝试去掉最后一段扩展名后匹配（如 .jpg .json）
    name_no_ext = re.sub(r"\.\w{2,5}$", "", camera_name)
    m = _RE_CAMERA_TREL.search(name_no_ext)
    if m:
        return float(m.group(1))
    return None


# ── 主处理函数 ────────────────────────────────────────────────────────────────

def process_capture_gps(
    capture_dir: Path,
    annot_root: "Path | None" = None,
    fov_deg: float = _FOV_H_DEG,
    az_tol_deg: float = _AZ_TOL_DEG,
    verbose: bool = True,
    extra_annot_roots: "list[Path] | None" = None,
) -> int:
    """用 GPS 射线法为 capture 下所有有标注的相机帧生成深度标签.

    输出文件：{capture_dir}/depth_labels/{camera_stem}.json
    与 assign_depth_azimuth 输出格式兼容（boxes 字段相同），可混用。

    Parameters
    ----------
    capture_dir       : capture 根目录（含 *_mmwave_udp_radar/ 子目录）
    annot_root        : labelme 标注根目录（可为 None）
    fov_deg           : 相机水平 FoV（°），默认 20°
    az_tol_deg        : 方位角匹配容差（°），默认 8°
    verbose           : 是否打印进度
    extra_annot_roots : 额外标注根目录列表（如 autofill_root）

    Returns
    -------
    n_written : 成功写出的 JSON 数量
    """
    capture_dir = Path(capture_dir)

    # ── 1. 建立标注 stem 索引 ────────────────────────────────────────────────
    stem_index: dict[str, Path] = {}
    roots_to_scan: list[Path] = []
    if annot_root:
        # 仅索引该 capture 对应的标注子目录
        cap_annot = (
            annot_root
            / capture_dir.parent.name   # date folder
            / capture_dir.name
        )
        roots_to_scan.append(cap_annot)
    if extra_annot_roots:
        for er in extra_annot_roots:
            ea = er / capture_dir.parent.name / capture_dir.name
            roots_to_scan.append(ea)

    for root in roots_to_scan:
        partial = _build_annot_stem_index(root)
        stem_index.update(partial)

    if not stem_index:
        if verbose:
            print(f"  [GPS] 无标注索引，跳过 {capture_dir.name}")
        return 0

    if verbose:
        n_roots = len(roots_to_scan)
        print(f"  [标注索引] 共 {len(stem_index)} 个 JSON（来源: {n_roots} 个根）")

    # ── 2. 建立 nav100 时间索引 ──────────────────────────────────────────────
    nav = build_nav100_index(capture_dir)
    if nav is None:
        if verbose:
            print(f"  [GPS] 未找到 nav100__state.csv，跳过 {capture_dir.name}")
        return 0
    if verbose:
        print(f"  [nav100] {len(nav[0])} 行，时间范围 "
              f"{float(nav[0][0]):.1f}s ~ {float(nav[0][-1]):.1f}s")

    # ── 3. 建立 GPS 目标点图 ─────────────────────────────────────────────────
    gps_targets = build_gps_target_map(capture_dir, verbose=verbose)
    if len(gps_targets) == 0:
        if verbose:
            print(f"  [GPS] 无雷达目标点，跳过 {capture_dir.name}")
        return 0

    # ── 4. 输出目录 ──────────────────────────────────────────────────────────
    out_dir = capture_dir / "depth_labels"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── 5. 逐帧处理 ─────────────────────────────────────────────────────────
    n_written = 0
    n_no_pose = 0
    n_no_boxes = 0
    skipped_existing = 0

    temporal_states: dict[str, list[dict]] = {}
    ordered_annotations = sorted(
        stem_index.items(),
        key=lambda item: (
            str(item[1].parents[2]) if len(item[1].parents) > 2 else str(item[1].parent),
            _parse_camera_t_rel(item[0]) or float("inf"),
        ),
    )
    for camera_stem, annot_path in ordered_annotations:
        # 解析相机帧时间
        t_rel = _parse_camera_t_rel(camera_stem)
        if t_rel is None:
            continue

        out_path = out_dir / (camera_stem + ".json")

        # 跳过：已存在且含有效 boxes（避免重复生成）
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if existing.get("method") == "gps_ray_fov_clustered" and existing.get("boxes"):
                    skipped_existing += 1
                    continue
            except Exception:
                pass

        # 插值车辆位姿
        pose = interp_vehicle_pose(t_rel, nav)
        if pose is None:
            n_no_pose += 1
            continue
        lat_v, lon_v, alt_v, pitch_v, hdg_v = pose

        # 读取标注 JSON
        try:
            annot = json.loads(annot_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        shapes = annot.get("shapes", [])
        annot_w = annot.get("imageWidth", 1920)
        annot_h = annot.get("imageHeight", 1200)

        sequence_key = (
            str(annot_path.parents[2])
            if len(annot_path.parents) > 2
            else str(annot_path.parent)
        )
        temporal_state = temporal_states.setdefault(sequence_key, [])

        # GPS 射线深度匹配
        boxes = assign_depth_gps_ray(
            shapes, annot_w, annot_h,
            lat_v, lon_v, alt_v, pitch_v, hdg_v,
            gps_targets,
            fov_h_deg=fov_deg,
            az_tol_deg=az_tol_deg,
            temporal_state=temporal_state,
        )

        if not boxes:
            n_no_boxes += 1

        # 写出 JSON（与 assign_depth_azimuth 输出格式兼容）
        out_data = {
            "camera_name": camera_stem + ".jpg",
            "t_rel_sec": round(t_rel, 3),
            "vehicle_lat": round(lat_v, 8),
            "vehicle_lon": round(lon_v, 8),
            "vehicle_hdg_deg": round(hdg_v, 2),
            "method": "gps_ray_fov_clustered",
            "min_visible_depth_m": _MIN_DEPTH_M,
            "min_absolute_height_m": 0.0,
            "camera_hfov_deg": _CAMERA_HFOV_DEG,
            "camera_vfov_deg": _CAMERA_VFOV_DEG,
            "n_gps_targets": int(len(gps_targets)),
            "fov_deg": fov_deg,
            "az_tol_deg": az_tol_deg,
            "clusters": [],   # GPS 方法无 per-frame 簇（用全段图代替）
            "boxes": boxes,
        }
        out_path.write_text(
            json.dumps(out_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        n_written += 1

    if verbose:
        print(
            f"[{capture_dir.name}] GPS深度标签: "
            f"{n_written} 个写出 / {len(stem_index)} 帧，"
            f"无位姿={n_no_pose}，无匹配={n_no_boxes}，"
            f"跳过已有={skipped_existing}"
        )
    return n_written


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="GPS 射线深度赋值")
    parser.add_argument("--capture-dir", required=True, help="capture 根目录")
    parser.add_argument("--annot-root", default=None, help="labelme 标注根目录")
    parser.add_argument("--autofill-root", default=None, help="autofill 标注根目录")
    parser.add_argument("--fov", type=float, default=20.0, help="相机水平 FoV（°）")
    parser.add_argument("--az-tol", type=float, default=8.0, help="方位角容差（°）")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    cap = Path(args.capture_dir)
    ann = Path(args.annot_root) if args.annot_root else None
    ext = [Path(args.autofill_root)] if args.autofill_root else None

    n = process_capture_gps(
        cap, annot_root=ann, fov_deg=args.fov, az_tol_deg=args.az_tol,
        verbose=True, extra_annot_roots=ext,
    )
    print(f"完成，共写出 {n} 个 JSON")
