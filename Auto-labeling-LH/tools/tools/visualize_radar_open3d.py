r"""
visualize_radar_open3d.py — 独立脚本

读取 capture 级目录（第 3 级目录，例如:
    L:\LH_data_all_sensor\4_29\with_cameras_capture_20260429_161943
）下的全部 *_mmwave_udp.bin（或已转换好的 *_radar/*.mat），
对每个天线帧做 CA-CFAR 检测，将所有波束还原到真实 GPS ENU 坐标系，
最后用 Open3D 渲染全量点云。

用法
----
  python visualize_radar_open3d.py [capture_dir] [选项]

  capture_dir  第 3 级目录，默认 L:\LH_data_all_sensor\4_29\with_cameras_capture_20260429_161943

选项
----
  --max-range   <m>     只保留该距离以内的点 (默认 2000 m)
  --min-db      <dB>    CA-CFAR 后的最小 dB 门限 (默认 25.0)
  --pfa         <概率>  CA-CFAR 虚警概率 (默认 1e-4)
  --top-view            只渲染俯视（ENU E-N 平面）- 通过相机角度控制
  --no-color            全部渲染白色（不按 dB 着色）
  --out         <文件>  同时把点云保存为 .ply 文件
  --mats-only           只读已有 mat，不尝试从 bin 转换

依赖
----
  pip install open3d scipy numpy
  (scipy 只用于读取 .mat)

坐标系
------
  输出使用 ENU（东-北-上）坐标系，以所有点的 GPS 中心为原点。
  x = East (m), y = North (m), z = Up (m)
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np

# ── 常量 ─────────────────────────────────────────────────────────────────────
_PKT            = 8624
_N_RANGE_FULL   = 668
_N_RANGE_OUT    = 666
_EL_MIN, _EL_MAX, _EL_STEP = -10.0, 5.0, 0.5
_RANGE_STEP_M   = 6.0     # 每个 range bin 的物理距离
_CFAR_TRAIN     = 15
_CFAR_GUARD     = 2
_R_EARTH_EQ     = 6_378_137.0
_R_EARTH_POL    = 6_356_752.0

# ── 工具函数 ──────────────────────────────────────────────────────────────────

def cfar_alpha(n_train: int, p_fa: float) -> float:
    return n_train * (p_fa ** (-1.0 / n_train) - 1.0)


def ca_cfar_1d(power_lin: np.ndarray, train: int, guard: int,
               alpha: float) -> np.ndarray:
    """向量化 1D CA-CFAR，返回布尔检测掩膜。"""
    n = power_lin.shape[0]
    half = train + guard
    cs = np.concatenate(([0.0], np.cumsum(power_lin, dtype=np.float64)))
    idx = np.arange(n)
    l0 = np.maximum(0, idx - half);   l1 = np.maximum(0, idx - guard)
    r0 = np.minimum(n, idx + guard + 1); r1 = np.minimum(n, idx + half + 1)
    n_tr = (l1 - l0) + (r1 - r0)
    s = (cs[l1] - cs[l0]) + (cs[r1] - cs[r0])
    noise = np.where(n_tr > 0, s / np.maximum(n_tr, 1), power_lin)
    return power_lin > (alpha * noise)


# ── mat 读取 ──────────────────────────────────────────────────────────────────

def _load_layers_from_mat(mat_path: Path) -> list[dict]:
    """从单个 mat 文件读取所有仰角层，返回 list of {el_deg, az, sd, pose}。

    pose shape: (n_az, 7) = [rangeGate, lat, lon, heading_deg, alt, PlaneEL, RadarEl]
    注意: 字段顺序与 batch_convert_bins.py 写法一致。
    """
    from scipy.io import loadmat
    try:
        raw = loadmat(str(mat_path), squeeze_me=False, struct_as_record=False)
    except Exception as exc:
        print(f"  [警告] 读取 mat 失败 {mat_path.name}: {exc}")
        return []

    data_ori = raw.get("Data_Ori")
    if data_ori is None:
        return []

    # Data_Ori: (n_el, 1) object array，每格为 (1, 5) object
    n_el = data_ori.shape[0]
    layers = []
    for k in range(n_el):
        try:
            cell = data_ori[k, 0]            # (1,5) object
            el_deg = float(np.asarray(cell[0, 0]).ravel()[0])
            az_arr = np.asarray(cell[0, 1]).ravel().astype(np.float64)    # (n_az,)
            # cell[0,2] = DiffDatadB (666, n_az)  — 不使用
            sd_db  = np.asarray(cell[0, 3]).astype(np.float32)            # (666, n_az)
            pose   = np.asarray(cell[0, 4]).astype(np.float64)            # (n_az, 7)
            if sd_db.size == 0 or az_arr.size == 0 or pose.shape[0] == 0:
                continue
            # 对齐 n_az
            n_az = min(az_arr.shape[0], sd_db.shape[1], pose.shape[0])
            layers.append({
                "el_deg": el_deg,
                "az":     az_arr[:n_az],
                "sd":     sd_db[:, :n_az],   # (n_range, n_az)
                "pose":   pose[:n_az, :],    # (n_az, 7)
            })
        except Exception as exc:
            print(f"  [警告] el-layer {k} 解析失败: {exc}")
    return layers


# ── bin 直接转换（无需写 mat 文件）─────────────────────────────────────────────

def _load_layers_from_bin(bin_path: Path,
                          ant_frame_idx: int | None = None
                          ) -> list[list[dict]]:
    """从 bin 文件直接解码，返回每个天线帧的 layers 列表。

    若指定 ant_frame_idx，只返回该帧；否则返回所有帧。
    """
    import os
    file_size = os.path.getsize(bin_path)
    if file_size == 0 or file_size % _PKT != 0:
        print(f"  [跳过] {bin_path.name}: 文件大小不合法")
        return []
    N_TOTAL = file_size // _PKT

    # ── 第 1 遍: 找天线帧边界 ──────────────────────────────────────────
    af_nums = np.empty(N_TOTAL, dtype=np.uint32)
    with open(bin_path, "rb") as f:
        chunk = 4096
        done = 0
        while done < N_TOTAL:
            m = min(chunk, N_TOTAL - done)
            buf = f.read(m * _PKT)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(m, _PKT)
            af_nums[done:done + m] = arr[:, 24:28].copy().view("<u4").ravel()
            done += m

    starts = np.where(af_nums == 1)[0]
    bounds = np.r_[starts, N_TOTAL]
    if len(starts) == 0:
        print(f"  [警告] {bin_path.name}: 未找到天线帧起始标志")
        return []

    el_grid = np.arange(_EL_MIN, _EL_MAX + _EL_STEP / 2, _EL_STEP)

    # ── 第 2 遍: 逐帧解码 ─────────────────────────────────────────────
    all_frames: list[list[dict]] = []
    with open(bin_path, "rb") as f:
        for ai, (i0, i1) in enumerate(zip(bounds[:-1], bounds[1:])):
            if ant_frame_idx is not None and ai != ant_frame_idx:
                continue
            n_fz = int(i1 - i0)
            f.seek(int(i0) * _PKT)
            buf = f.read(n_fz * _PKT)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(n_fz, _PKT)

            ant_az = arr[:, 80:84].copy().view("<f4").ravel().astype(np.float64)
            ant_el = arr[:, 84:88].copy().view("<f4").ravel().astype(np.float64)
            lat    = arr[:, 52:56].copy().view("<f4").ravel().astype(np.float64)
            lon    = arr[:, 48:52].copy().view("<f4").ravel().astype(np.float64)
            hdg    = arr[:, 56:60].copy().view("<f4").ravel().astype(np.float64)
            alt    = arr[:, 60:64].copy().view("<f4").ravel().astype(np.float64)

            body     = arr[:, 256:5632]
            sum_lin  = np.frombuffer(body[:, 8:8 + 668 * 4].tobytes(),
                                     dtype="<f4").reshape(n_fz, 668)
            # 转 dB
            sum_db   = (10.0 * np.log10(np.maximum(sum_lin, 1e-3))).astype(np.float32)
            # 裁到 666 单元
            sd = sum_db[:, 1:1 + _N_RANGE_OUT]   # (n_fz, 666)

            # 量化到仰角栅格
            el_idx = np.round((ant_el - _EL_MIN) / _EL_STEP).astype(int)
            valid  = (el_idx >= 0) & (el_idx < len(el_grid))
            if not valid.all():
                this_el_min = float(np.min(ant_el))
                this_el_max = float(np.max(ant_el))
                local_grid = np.arange(
                    np.floor(this_el_min / _EL_STEP) * _EL_STEP,
                    np.ceil(this_el_max / _EL_STEP) * _EL_STEP + _EL_STEP / 2,
                    _EL_STEP)
                el_idx = np.round((ant_el - local_grid[0]) / _EL_STEP).astype(int)
                grid_use = local_grid
            else:
                grid_use = el_grid

            frame_layers: list[dict] = []
            for k in range(len(grid_use)):
                sel = np.where(el_idx == k)[0]
                if len(sel) == 0:
                    continue
                sel = sel[np.argsort(ant_az[sel])]
                n_az = len(sel)
                az_arr = ant_az[sel]
                sd_k   = sd[sel].T.copy()  # (666, n_az)
                # pose: (n_az, 7) = [0, lat, lon, heading, alt, 0, el_deg]
                pose = np.zeros((n_az, 7), dtype=np.float64)
                pose[:, 1] = lat[sel]
                pose[:, 2] = lon[sel]
                pose[:, 3] = hdg[sel]
                pose[:, 4] = alt[sel]
                pose[:, 6] = ant_el[sel]
                frame_layers.append({
                    "el_deg": float(grid_use[k]),
                    "az":     az_arr,
                    "sd":     sd_k,
                    "pose":   pose,
                })
            if frame_layers:
                all_frames.append(frame_layers)

    return all_frames


# ── 点云构造 ──────────────────────────────────────────────────────────────────

def layers_to_enu(layers: list[dict],
                  min_db: float = 25.0,
                  max_range_m: float = 2000.0,
                  pfa: float = 1e-4,
                  ) -> tuple[np.ndarray, float, float, float]:
    """
    把一帧所有波束转换为 ENU 点云。

    参数
    ----
    layers       : list of {el_deg, az, sd (n_range, n_az), pose (n_az, 7)}
    min_db       : CFAR 后的最小 dB 门限
    max_range_m  : 最大距离门限
    pfa          : 虚警概率

    返回
    ----
    pts        : (N, 4)  float32  [E_m, N_m, U_m, power_dB]  (以 GPS 中心为原点)
    ref_lat    : float   参考点纬度（所有检测点 GPS 均值）
    ref_lon    : float   参考点经度
    ref_alt    : float   参考点高度
    """
    if not layers:
        return np.empty((0, 4), dtype=np.float32), 0.0, 0.0, 0.0

    # 参考点：全帧 GPS 均值（用于 ENU 原点）
    all_lat = np.concatenate([L["pose"][:, 1] for L in layers])
    all_lon = np.concatenate([L["pose"][:, 2] for L in layers])
    all_alt = np.concatenate([L["pose"][:, 4] for L in layers])
    ref_lat = float(np.mean(all_lat[all_lat != 0.0]) if np.any(all_lat != 0.0) else all_lat.mean())
    ref_lon = float(np.mean(all_lon[all_lon != 0.0]) if np.any(all_lon != 0.0) else all_lon.mean())
    ref_alt = float(np.mean(all_alt))

    coslat0 = math.cos(math.radians(ref_lat))
    n_train  = _CFAR_TRAIN * 2
    alpha    = cfar_alpha(n_train, pfa)

    rng_m = np.arange(1, _N_RANGE_OUT + 1, dtype=np.float32) * _RANGE_STEP_M
    in_range = rng_m <= max_range_m

    chunks: list[np.ndarray] = []
    for L in layers:
        el_deg = L["el_deg"]
        az_arr = L["az"]
        sd     = L["sd"]        # (n_range, n_az)
        pose   = L["pose"]      # (n_az, 7)

        n_range, n_az = sd.shape
        rng = rng_m[:n_range]
        in_r = in_range[:n_range]
        sd_lin = np.power(10.0, sd / 10.0).astype(np.float64)

        el_rad = math.radians(el_deg)
        cos_el, sin_el = math.cos(el_rad), math.sin(el_rad)

        for j in range(n_az):
            col_lin = sd_lin[:, j]
            mask = ca_cfar_1d(col_lin, _CFAR_TRAIN, _CFAR_GUARD, alpha)
            mask &= sd[:, j] > min_db
            mask &= in_r
            if not mask.any():
                continue

            ri = np.where(mask)[0]
            R  = rng[ri]

            az_rad = math.radians(float(az_arr[j]))
            cos_az, sin_az = math.cos(az_rad), math.sin(az_rad)

            # 波束坐标 → 车体坐标  (x=右, y=前, z=上)
            xb = R * cos_el * sin_az   # right
            yb = R * cos_el * cos_az   # forward
            zb = R * sin_el            # up

            # 当前波束 GPS 位姿
            lat_b = float(pose[j, 1])
            lon_b = float(pose[j, 2])
            hdg_b = float(pose[j, 3])
            alt_b = float(pose[j, 4])

            h = math.radians(hdg_b)
            cos_h, sin_h = math.cos(h), math.sin(h)

            # 车体 → ENU (以本束 GPS 为原点)
            E_local = xb * cos_h + yb * sin_h
            N_local = -xb * sin_h + yb * cos_h
            U_local = zb

            # 折算本束 GPS 到 ENU 参考点的偏移
            dE = (lon_b - ref_lon) * math.radians(1.0) * _R_EARTH_EQ * coslat0
            dN = (lat_b - ref_lat) * math.radians(1.0) * _R_EARTH_POL
            dU = alt_b - ref_alt

            E_abs = E_local + dE
            N_abs = N_local + dN
            U_abs = U_local + dU

            inten = sd[ri, j].astype(np.float32)
            chunks.append(np.column_stack([
                E_abs.astype(np.float32),
                N_abs.astype(np.float32),
                U_abs.astype(np.float32),
                inten,
            ]))

    if not chunks:
        return np.empty((0, 4), dtype=np.float32), ref_lat, ref_lon, ref_alt
    return np.concatenate(chunks), ref_lat, ref_lon, ref_alt


# ── 主流程 ────────────────────────────────────────────────────────────────────

def build_pointcloud(capture_dir: Path,
                     min_db: float = 25.0,
                     max_range_m: float = 2000.0,
                     pfa: float = 1e-4,
                     mats_only: bool = False,
                     ) -> tuple[np.ndarray, float, float, float]:
    """
    扫描 capture_dir，读取所有天线帧，构造合并点云。

    优先顺序:
      1. 已存在的 *_radar/*.mat（已转换好）
      2. 若 --mats-only 则跳过 bin；否则直接从 bin 解码（不落盘 mat）

    返回: (pts, ref_lat, ref_lon, ref_alt)
      pts: (N,4) [E_m, N_m, U_m, dB]，ENU 坐标系，原点为所有点 GPS 均值
    """
    # 1. 查找 *_radar 目录下的 mat
    radar_dir: Path | None = None
    for d in capture_dir.iterdir():
        if d.is_dir() and d.name.endswith("_radar"):
            radar_dir = d
            break

    all_pts:  list[np.ndarray] = []
    ref_lats: list[float]      = []
    ref_lons: list[float]      = []
    ref_alts: list[float]      = []

    if radar_dir is not None and any(radar_dir.glob("*.mat")):
        mats = sorted(radar_dir.glob("*.mat"),
                      key=lambda p: p.name)
        print(f"[信息] 发现 {len(mats)} 个 mat 文件 → {radar_dir.name}/")
        for i, mat_path in enumerate(mats, 1):
            print(f"  [{i:3d}/{len(mats)}] {mat_path.name}", end="  ", flush=True)
            layers = _load_layers_from_mat(mat_path)
            if not layers:
                print("(无层数据)")
                continue
            pts, rl, rlon, ra = layers_to_enu(layers, min_db, max_range_m, pfa)
            print(f"→ {len(pts):5d} 点")
            if pts.size > 0:
                all_pts.append(pts)
                ref_lats.append(rl);  ref_lons.append(rlon);  ref_alts.append(ra)

    elif not mats_only:
        # 从 bin 直接解码
        bins = sorted(capture_dir.glob("*_mmwave_udp.bin"))
        if not bins:
            print(f"[错误] 在 {capture_dir} 下未找到 *_mmwave_udp.bin 也没有已转换的 mat")
            return np.empty((0, 4), dtype=np.float32), 0.0, 0.0, 0.0
        bin_path = bins[0]
        print(f"[信息] 从 bin 直接解码: {bin_path.name}")
        all_frames = _load_layers_from_bin(bin_path)
        print(f"[信息] 共 {len(all_frames)} 个天线帧")
        for i, layers in enumerate(all_frames, 1):
            print(f"  [{i:3d}/{len(all_frames)}] 天线帧 (el_layers={len(layers)})",
                  end="  ", flush=True)
            pts, rl, rlon, ra = layers_to_enu(layers, min_db, max_range_m, pfa)
            print(f"→ {len(pts):5d} 点")
            if pts.size > 0:
                all_pts.append(pts)
                ref_lats.append(rl);  ref_lons.append(rlon);  ref_alts.append(ra)
    else:
        print(f"[警告] --mats-only 但未找到 mat 文件，直接退出")
        return np.empty((0, 4), dtype=np.float32), 0.0, 0.0, 0.0

    if not all_pts:
        print("[警告] 所有帧均无检测点")
        return np.empty((0, 4), dtype=np.float32), 0.0, 0.0, 0.0

    pts_merged = np.concatenate(all_pts)

    # 重新统一到全局 GPS 均值原点（各帧 ref_lat 用帧内均值，最终再归一次）
    global_lat = float(np.mean(ref_lats))
    global_lon = float(np.mean(ref_lons))
    global_alt = float(np.mean(ref_alts))
    coslat0 = math.cos(math.radians(global_lat))

    # 修正各帧的 ENU 原点差
    offset_E_list, offset_N_list, offset_U_list = [], [], []
    cumulative = 0
    for pts_chunk, rl, rlon, ra in zip(all_pts, ref_lats, ref_lons, ref_alts):
        n = len(pts_chunk)
        dE = (rlon - global_lon) * math.radians(1.0) * _R_EARTH_EQ * coslat0
        dN = (rl   - global_lat) * math.radians(1.0) * _R_EARTH_POL
        dU = ra - global_alt
        pts_merged[cumulative:cumulative + n, 0] += dE
        pts_merged[cumulative:cumulative + n, 1] += dN
        pts_merged[cumulative:cumulative + n, 2] += dU
        cumulative += n

    print(f"\n[完成] 合并点云: {len(pts_merged):,} 点  "
          f"(E {pts_merged[:, 0].min():.0f}..{pts_merged[:, 0].max():.0f} m  "
          f"N {pts_merged[:, 1].min():.0f}..{pts_merged[:, 1].max():.0f} m)")
    return pts_merged, global_lat, global_lon, global_alt


# ── Open3D 可视化 ─────────────────────────────────────────────────────────────

def db_to_color(db_vals: np.ndarray) -> np.ndarray:
    """将 dB 值映射为 BGR 热图颜色 (蓝→绿→黄→红)。返回 (N,3) float [0,1]."""
    # 归一化到 [0,1]
    lo = float(np.percentile(db_vals, 2))
    hi = float(np.percentile(db_vals, 98))
    if hi <= lo:
        hi = lo + 1.0
    t = np.clip((db_vals.astype(np.float64) - lo) / (hi - lo), 0.0, 1.0)

    # 4 段线性: 蓝→青→绿→黄→红
    r = np.where(t < 0.5, 0.0, np.where(t < 0.75, (t - 0.5) * 4, 1.0))
    g = np.where(t < 0.25, t * 4,
        np.where(t < 0.75, 1.0,
        np.where(t < 1.0,  (1.0 - t) * 4, 0.0)))
    b = np.where(t < 0.25, 1.0, np.where(t < 0.5, (0.5 - t) * 4, 0.0))
    return np.column_stack([r, g, b]).astype(np.float64)


def visualize(pts: np.ndarray,
              title: str = "LH Radar ENU Point Cloud",
              use_color: bool = True,
              top_view: bool = False,
              out_ply: Path | None = None) -> None:
    """用 Open3D 显示点云。"""
    try:
        import open3d as o3d
    except ImportError:
        print("[错误] 未安装 open3d，请执行: pip install open3d")
        sys.exit(1)

    if len(pts) == 0:
        print("[警告] 点云为空，无法可视化")
        return

    xyz = pts[:, :3].astype(np.float64)
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(xyz)

    if use_color:
        colors = db_to_color(pts[:, 3])
        pcd.colors = o3d.utility.Vector3dVector(colors)
    else:
        pcd.paint_uniform_color([1.0, 1.0, 1.0])

    # 可选保存 .ply
    if out_ply is not None:
        o3d.io.write_point_cloud(str(out_ply), pcd)
        print(f"[保存] 点云已写入 {out_ply}")

    # 坐标轴 (x=East 红, y=North 绿, z=Up 蓝)
    frame = o3d.geometry.TriangleMesh.create_coordinate_frame(
        size=100.0, origin=[0.0, 0.0, 0.0])

    vis = o3d.visualization.Visualizer()
    vis.create_window(window_name=title, width=1400, height=900)
    vis.add_geometry(pcd)
    vis.add_geometry(frame)

    # 渲染设置
    opt = vis.get_render_option()
    opt.background_color = np.array([0.05, 0.05, 0.05])
    opt.point_size = 2.5
    opt.show_coordinate_frame = True

    # 相机视角
    ctr = vis.get_view_control()
    if top_view:
        # 俯视 (ENU 顶视)
        ctr.set_front([0.0, 0.0, -1.0])
        ctr.set_up([0.0, 1.0, 0.0])
        ctr.set_lookat(xyz.mean(axis=0))
        ctr.set_zoom(0.5)
    else:
        # 斜视
        ctr.set_front([-0.5, -0.8, -0.4])
        ctr.set_up([0.0, 0.0, 1.0])
        ctr.set_lookat(xyz.mean(axis=0))
        ctr.set_zoom(0.3)

    print("\n[打开 Open3D 窗口]")
    print("  鼠标左键拖动: 旋转")
    print("  鼠标右键拖动: 平移")
    print("  滚轮: 缩放")
    print("  按 Q 或关闭窗口: 退出\n")

    # 显示基本统计信息
    print(f"  点数:  {len(pts):,}")
    print(f"  dB 范围: {pts[:, 3].min():.1f} ~ {pts[:, 3].max():.1f} dB")
    print(f"  E 范围:  {xyz[:, 0].min():.1f} ~ {xyz[:, 0].max():.1f} m")
    print(f"  N 范围:  {xyz[:, 1].min():.1f} ~ {xyz[:, 1].max():.1f} m")
    print(f"  U 范围:  {xyz[:, 2].min():.1f} ~ {xyz[:, 2].max():.1f} m\n")

    vis.run()
    vis.destroy_window()


# ── CLI 入口 ──────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LH mmWave 雷达 Open3D 可视化工具",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "capture_dir",
        nargs="?",
        default=r"L:\LH_data_all_sensor\4_29\with_cameras_capture_20260429_161943",
        help="第 3 级 capture 目录",
    )
    parser.add_argument("--max-range",  type=float, default=2000.0,
                        metavar="m",    help="最大距离门限 (m)")
    parser.add_argument("--min-db",     type=float, default=25.0,
                        metavar="dB",   help="CFAR 后最小 dB 门限")
    parser.add_argument("--pfa",        type=float, default=1e-4,
                        metavar="概率", help="CA-CFAR 虚警概率")
    parser.add_argument("--top-view",   action="store_true",
                        help="俯视渲染（ENU E-N 平面）")
    parser.add_argument("--no-color",   action="store_true",
                        help="不按 dB 着色，全部显示白色")
    parser.add_argument("--out",        type=Path, default=None,
                        metavar="FILE", help="同时保存点云为 .ply 文件")
    parser.add_argument("--mats-only",  action="store_true",
                        help="只读已有 mat，不从 bin 解码")
    args = parser.parse_args()

    capture_dir = Path(args.capture_dir)
    if not capture_dir.exists():
        print(f"[错误] 目录不存在: {capture_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[开始] capture 目录: {capture_dir}")
    print(f"       max_range={args.max_range} m  min_db={args.min_db} dB  "
          f"pfa={args.pfa:.1e}")

    pts, ref_lat, ref_lon, ref_alt = build_pointcloud(
        capture_dir,
        min_db=args.min_db,
        max_range_m=args.max_range,
        pfa=args.pfa,
        mats_only=args.mats_only,
    )

    if pts.size == 0:
        print("[结束] 没有可显示的点")
        sys.exit(0)

    print(f"\n       GPS 参考原点: lat={ref_lat:.6f}°  lon={ref_lon:.6f}°  "
          f"alt={ref_alt:.1f} m")

    visualize(
        pts,
        title=f"LH Radar ENU — {capture_dir.name}",
        use_color=not args.no_color,
        top_view=args.top_view,
        out_ply=args.out,
    )


if __name__ == "__main__":
    main()
