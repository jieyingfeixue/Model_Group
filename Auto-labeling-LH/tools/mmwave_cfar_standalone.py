"""毫米波雷达 CA-CFAR 点云生成 —— 独立脚本.

从 `Auto-labeling-LH/src/io/adapters/lh_adapter.py` 抽出，去除框架耦合
(无 FrameData / logger / 项目 import)，仅依赖 ``numpy`` + ``scipy.io``。

输入: 1218-style 的 ``.mat`` 文件，含以下任一格式:
  1) 标准格式: 同时含 ``Data_Ori`` 和 ``BeamPose``
        - Data_Ori: (n_el, 1) object, 每 cell raveled =
              [el_deg(scalar), az(n_az,), ?, sd_dB(n_range, n_az), ...]
        - BeamPose: (n_el, 1) object, 每 cell = (n_az, 7)
              = [az_deg, el_deg, lat, lon, alt, heading_deg, ts_sec]
  2) batch_convert_bins 生成格式: 仅有 ``Data_Ori``, pose 嵌在 sub[4]:
        meta 列 = [0, lat, lon, heading_deg, alt, 0, el_deg]

处理步骤 (与原 adapter 一致):
  1. 每 (el-layer, az-column) 沿 range 做 1D CA-CFAR (CA-15/2, P_fa=1e-4);
  2. 每点 R=(r+1)*6 m, beam frame:
        x_right = R·cos(el)·sin(az)
        y_fwd   = R·cos(el)·cos(az)
        z_up    = R·sin(el)
  3. 多束用参考束(全 mat 中 ts 最小那束) GPS+heading 统一到同一参考帧.

输出: ``(N, 4)`` ndarray ``[x_right, y_fwd, z_up, power_dB]``,
      以及参考束航向角 ``hdg0_deg`` (北起顺时针, °).

CLI:
    python mmwave_cfar_standalone.py path/to/foo.mat [-o out.npy] [--max-points 20000]
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

import numpy as np


# ── 参数 (与 lh_adapter.py 保持一致) ────────────────────────────────────────
RADAR_RANGE_STEP_M = 6.0          # 单 range bin 物理距离 (m)
RADAR_MAX_RANGE_M  = 4000.0
CFAR_TRAIN         = 15            # 每侧训练单元
CFAR_GUARD         = 2             # 每侧保护单元
CFAR_PFA           = 1e-4          # 虚警概率
CFAR_MIN_DB        = 20.0          # dB 保底
MAX_POINTS         = 20000         # 单帧点数上限
R_EARTH_EQ         = 6378137.0     # WGS84 赤道半径 (m)
R_EARTH_POL        = 6356752.0     # WGS84 极半径 (m)


# ── CFAR 核心 ────────────────────────────────────────────────────────────────

def cfar_alpha(n_train: int, p_fa: float) -> float:
    """CA-CFAR 门限缩放因子."""
    return n_train * (p_fa ** (-1.0 / n_train) - 1.0)


def ca_cfar_1d(power_lin: np.ndarray, train: int, guard: int, alpha: float) -> np.ndarray:
    """向量化 1D CA-CFAR.

    Parameters
    ----------
    power_lin : (N,) ndarray, 线性功率 (非 dB).
    train     : 每侧训练单元数.
    guard     : 每侧保护单元数.
    alpha     : 见 :func:`cfar_alpha`.

    Returns
    -------
    (N,) bool ndarray, True = 超过自适应门限.
    """
    n = power_lin.shape[0]
    half_win = train + guard
    cs = np.concatenate(([0.0], np.cumsum(power_lin, dtype=np.float64)))
    idx = np.arange(n)
    l0 = np.maximum(0, idx - half_win)
    l1 = np.maximum(0, idx - guard)
    r0 = np.minimum(n, idx + guard + 1)
    r1 = np.minimum(n, idx + half_win + 1)
    n_tr = (l1 - l0) + (r1 - r0)
    s = (cs[l1] - cs[l0]) + (cs[r1] - cs[r0])
    safe = np.maximum(n_tr, 1)
    noise = s / safe
    noise = np.where(n_tr > 0, noise, power_lin)  # 边界退化
    return power_lin > (alpha * noise)


# ── .mat 解析 ────────────────────────────────────────────────────────────────

def load_mmwave_layers(path: Path) -> list[dict]:
    """解析 mat -> 每个 el-layer 的字典列表.

    每项: ``{'el_deg': float, 'az': (n_az,), 'sd': (n_range, n_az) dB,
              'pose': (n_az, 7) = [az,el,lat,lon,alt,heading,ts]}``.
    """
    import scipy.io as sio  # 延迟 import, 仅在调用时需要

    raw = sio.loadmat(str(path))
    do = raw.get("Data_Ori")
    if do is None or do.size == 0:
        return []

    pose_top = raw.get("BeamPose")
    has_beam_pose = pose_top is not None and pose_top.size > 0
    n_layers = do.shape[0]
    if has_beam_pose:
        n_layers = min(n_layers, pose_top.shape[0])

    layers: list[dict] = []
    for k in range(n_layers):
        try:
            sub = do[k, 0].ravel()
            el_deg = float(np.asarray(sub[0]).ravel()[0])
            az = np.asarray(sub[1]).ravel().astype(np.float32)
            sd = np.asarray(sub[3]).astype(np.float32)  # (n_range, n_az) dB

            if has_beam_pose:
                pose = np.asarray(pose_top[k, 0]).astype(np.float64)
            else:
                meta = np.asarray(sub[4]).astype(np.float64)  # (n_az, 7)
                n_az = min(az.shape[0], meta.shape[0])
                az = az[:n_az]
                sd = sd[:, :n_az] if sd.ndim == 2 else sd
                pose = np.zeros((n_az, 7), dtype=np.float64)
                pose[:, 0] = az.astype(np.float64)
                pose[:, 1] = el_deg
                pose[:, 2] = meta[:n_az, 1]   # lat
                pose[:, 3] = meta[:n_az, 2]   # lon
                pose[:, 4] = meta[:n_az, 4]   # alt
                pose[:, 5] = meta[:n_az, 3]   # heading_deg
                pose[:, 6] = 0.0              # ts (此格式无)

            if sd.size == 0 or az.size == 0 or pose.shape[0] == 0:
                continue
            layers.append({"el_deg": el_deg, "az": az, "sd": sd, "pose": pose})
        except Exception:
            continue
    return layers


def stack_power_cube(layers: list[dict]) -> np.ndarray:
    """把多束按主形状拼成 (n_el, n_range, n_az) 功率 cube (dB).

    用于需要原始张量的下游(可选)。
    """
    if not layers:
        return np.empty((0,), dtype=np.float32)
    shapes = Counter(L["sd"].shape for L in layers)
    target_shape, _ = shapes.most_common(1)[0]
    cube = np.stack([L["sd"] for L in layers if L["sd"].shape == target_shape], axis=0)
    return cube.astype(np.float32, copy=False)


# ── 点云生成主函数 ───────────────────────────────────────────────────────────

def mmwave_pointcloud_from_mat(
    path: Path,
    *,
    range_step_m: float = RADAR_RANGE_STEP_M,
    max_range_m: float  = RADAR_MAX_RANGE_M,
    cfar_train: int     = CFAR_TRAIN,
    cfar_guard: int     = CFAR_GUARD,
    cfar_pfa: float     = CFAR_PFA,
    cfar_min_db: float  = CFAR_MIN_DB,
    max_points: int     = MAX_POINTS,
) -> tuple[np.ndarray, float]:
    """CA-CFAR + GPS 统一 -> ``(N,4)`` 点云 ``[x_right, y_fwd, z_up, power_dB]``.

    Returns
    -------
    pts : (N,4) float32 ndarray, 已限制到 ``max_points``.
    hdg0_deg : float, 参考束航向角 (°, 北起顺时针).
    """
    layers = load_mmwave_layers(path)
    if not layers:
        return np.empty((0, 4), dtype=np.float32), 0.0

    # 参考束: 全 mat 中 ts 最小的那束
    all_ts  = np.concatenate([L["pose"][:, 6] for L in layers])
    all_lat = np.concatenate([L["pose"][:, 2] for L in layers])
    all_lon = np.concatenate([L["pose"][:, 3] for L in layers])
    all_alt = np.concatenate([L["pose"][:, 4] for L in layers])
    all_hdg = np.concatenate([L["pose"][:, 5] for L in layers])
    ref = int(np.argmin(all_ts))
    lat0 = float(all_lat[ref])
    lon0 = float(all_lon[ref])
    alt0 = float(all_alt[ref])
    hdg0 = float(all_hdg[ref])
    h0 = np.deg2rad(hdg0)
    cos_h0, sin_h0 = float(np.cos(h0)), float(np.sin(h0))
    coslat0 = float(np.cos(np.deg2rad(lat0)))

    n_train_total = cfar_train * 2
    alpha = cfar_alpha(n_train_total, cfar_pfa)

    pts_chunks: list[np.ndarray] = []
    for L in layers:
        el_deg = L["el_deg"]
        az_arr = L["az"]
        sd = L["sd"]
        pose = L["pose"]
        n_range, n_az = sd.shape
        if pose.shape[0] < n_az:
            n_az = pose.shape[0]
            sd = sd[:, :n_az]
            az_arr = az_arr[:n_az]
        rng_m = np.arange(1, n_range + 1, dtype=np.float32) * range_step_m
        in_range = rng_m < max_range_m
        sd_lin = np.power(10.0, sd / 10.0).astype(np.float64)

        for j in range(n_az):
            col_lin = sd_lin[:, j]
            mask = ca_cfar_1d(col_lin, cfar_train, cfar_guard, alpha)
            mask &= sd[:, j] > cfar_min_db
            mask &= in_range
            if not mask.any():
                continue
            ri = np.where(mask)[0]
            R = rng_m[ri]
            az_rad = np.deg2rad(float(az_arr[j]))
            el_rad = np.deg2rad(el_deg)
            ce, se = float(np.cos(el_rad)), float(np.sin(el_rad))
            ca, sa = float(np.cos(az_rad)), float(np.sin(az_rad))
            xb = R * ce * sa   # 右
            yb = R * ce * ca   # 前
            zb = R * se        # 上

            # 该束 GPS 位姿
            lat_b = float(pose[j, 2]); lon_b = float(pose[j, 3])
            alt_b = float(pose[j, 4]); hdg_b = float(pose[j, 5])
            dE = (lon_b - lon0) * np.deg2rad(1.0) * R_EARTH_EQ * coslat0
            dN = (lat_b - lat0) * np.deg2rad(1.0) * R_EARTH_POL
            dU = alt_b - alt0
            h = np.deg2rad(hdg_b)
            cos_h, sin_h = float(np.cos(h)), float(np.sin(h))
            # 束体系 -> ENU (yaw = heading from north, clockwise)
            E = dE + xb * cos_h + yb * sin_h
            N = dN - xb * sin_h + yb * cos_h
            U = dU + zb
            # ENU -> 参考束体系 (x_right, y_fwd, z_up)
            xr = E * cos_h0 - N * sin_h0
            yr = E * sin_h0 + N * cos_h0
            zr = U

            inten = sd[ri, j].astype(np.float32)
            pts_chunks.append(np.stack(
                [xr.astype(np.float32),
                 yr.astype(np.float32),
                 zr.astype(np.float32),
                 inten], axis=1))

    if not pts_chunks:
        return np.empty((0, 4), dtype=np.float32), hdg0
    out = np.concatenate(pts_chunks, axis=0)
    if out.shape[0] > max_points:
        idx = np.argpartition(out[:, 3], -max_points)[-max_points:]
        out = out[idx]
    return out, hdg0


# ── CLI ──────────────────────────────────────────────────────────────────────

def _main() -> None:
    ap = argparse.ArgumentParser(description="mmwave CA-CFAR pointcloud (standalone)")
    ap.add_argument("mat", type=Path, help="输入 .mat 文件路径")
    ap.add_argument("-o", "--out", type=Path, default=None,
                    help="输出 .npy 路径 (默认: <mat 同名>.npy)")
    ap.add_argument("--max-points", type=int, default=MAX_POINTS)
    ap.add_argument("--min-db", type=float, default=CFAR_MIN_DB)
    args = ap.parse_args()

    pts, hdg0 = mmwave_pointcloud_from_mat(
        args.mat, max_points=args.max_points, cfar_min_db=args.min_db,
    )
    out_path = args.out or args.mat.with_suffix(".npy")
    np.save(out_path, pts)
    if len(pts):
        db_min = float(pts[:, 3].min()); db_max = float(pts[:, 3].max())
        r = np.linalg.norm(pts[:, :3], axis=1)
        print(f"[OK] {args.mat.name}: pts={len(pts)}  hdg0={hdg0:.1f}°  "
              f"dB=[{db_min:.1f},{db_max:.1f}]  R=[{r.min():.0f},{r.max():.0f}]m  "
              f"-> {out_path}")
    else:
        print(f"[WARN] {args.mat.name}: 无 CFAR 检测点 (尝试降低 --min-db).")


if __name__ == "__main__":
    _main()
