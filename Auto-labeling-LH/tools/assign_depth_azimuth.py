"""
assign_depth_azimuth.py  —  Step 1：方案A 方位角排序匹配深度赋值

将人工标注的相机 2D 框自动赋值深度信息。

算法（方案A + 1D range 聚类）：
  1. 加载 mat 文件 → CA-CFAR 检测点 → BEV (az_deg, range_m)
  2. DBSCAN 聚类 → 每个目标簇: 质心 az、加权中值 range、置信度
  3. 从 mat-相机对应表找相机帧名 → 搜索 LabelMe JSON 标注
  4. 框 u_center → 估算 az_box（用估计 FoV，FoV 误差被 Δaz 吸收）
  5. 全局偏移搜索 Δaz → Hungarian 匹配框 ↔ 簇
  6. 输出 {out_dir}/{mat_stem}.json（含框深度）

用法：
  # 本地数据集（有 mat_to_image_*.csv）
  python tools/assign_depth_azimuth.py \\
      --capture-dir "D:/Dataset/多模态数据库/1" \\
      --annot-root  "D:/path/to/labelme_annotations" \\
      --fov 20

  # LH 网络数据集（有 match_mat_camera.csv）
  python tools/assign_depth_azimuth.py \\
      --capture-dir "L:/LH_data_all_sensor/4_29/with_cameras_capture_20260429_164703" \\
      --annot-root  "L:/path/to/annotations" \\
      --fov 18

  # 无标注时仅输出雷达簇（诊断模式）
  python tools/assign_depth_azimuth.py \\
      --capture-dir "D:/Dataset/多模态数据库/1" \\
      --radar-only
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

# 把 tools/ 加入 sys.path，以便 import mmwave_cfar_standalone
sys.path.insert(0, str(Path(__file__).parent))
from mmwave_cfar_standalone import mmwave_pointcloud_from_mat  # noqa: E402

# ── 常量 ─────────────────────────────────────────────────────────────────────
RANGE_STEP_M     = 6.0       # 每个 range bin 的物理距离（m），来自 mmwave_cfar
AZ_MATCH_TOL_DEG = 5.0       # 方位角匹配容差（°），超出则视为"未匹配"
DBSCAN_EPS_M     = 50.0      # DBSCAN 聚类半径（m）在 BEV Cartesian 空间
DBSCAN_MIN_PTS   = 3         # 最小样本数

# mat-相机对应表：可能的文件名
_MAT_CSV_NAMES = [
    "match_mat_camera.csv",
    "mat_to_image_1to1.csv",
    "mat_to_image_range.csv",
]

_RE_MAT_FZ    = re.compile(r"_AntFrame(\d+)_FZ(\d+)-(\d+)\.mat$", re.IGNORECASE)
_RE_CAM_STEM  = re.compile(r"hikrobot_camera__DA8679037__image_raw")


# ── mat-相机对应表加载 ────────────────────────────────────────────────────────

def load_mat_camera_map(capture_dir: Path) -> dict[str, str]:
    """
    返回 {mat_filename_stem → camera_filename}。
    自动检测 CSV 格式（支持 match_mat_camera.csv 和 mat_to_image_*.csv）。
    """
    for name in _MAT_CSV_NAMES:
        csv_path = capture_dir / name
        if not csv_path.exists():
            continue
        result: dict[str, str] = {}
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cols = reader.fieldnames or []
            # match_mat_camera.csv: mat_name, camera_name, ...
            if "mat_name" in cols and "camera_name" in cols:
                for row in reader:
                    mn = Path(row["mat_name"]).stem
                    cn = row.get("camera_name", "").strip()
                    if cn:
                        result[mn] = cn
            # mat_to_image_*.csv: mat, first_image, ...
            elif "mat" in cols and "first_image" in cols:
                for row in reader:
                    mn = Path(row["mat"]).stem
                    cn = row.get("first_image", "").strip()
                    if cn:
                        result[mn] = cn
        if result:
            print(f"  加载对应表: {name}，共 {len(result)} 条")
            return result
    print("  ⚠ 未找到 mat-相机对应表，无法关联 LabelMe 标注")
    return {}


# ── LabelMe 标注加载 ──────────────────────────────────────────────────────────

_ANNOT_STEM_INDEX: "dict[str, Path] | None" = None


def _build_stem_index(annot_root: Path) -> "dict[str, Path]":
    """
    构建 stem → Path 索引。
    搜索 annot_root 下所有 hikrobot_camera__DA8679037__image_raw 目录中的 JSON。
    """
    cam_dir = "hikrobot_camera__DA8679037__image_raw"
    index: dict[str, Path] = {}
    for p in annot_root.rglob(f"{cam_dir}/*.json"):
        index[p.stem] = p
    return index


def find_annot_json(
    camera_name: str,
    annot_root: Path,
    stem_index: "dict[str, Path] | None" = None,
) -> "Path | None":
    """
    在 annot_root 下搜索与 camera_name 对应的 LabelMe JSON。
    若提供 stem_index（_build_stem_index 的结果），直接查表（最快）；
    否则退回到候选路径检查。
    """
    stem = Path(camera_name).stem
    if stem_index is not None:
        return stem_index.get(stem)
    candidates = [
        annot_root / f"{stem}.json",
        annot_root / "hikrobot_camera__DA8679037__image_raw" / f"{stem}.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_labelme_boxes(json_path: Path) -> list[dict]:
    """
    解析 LabelMe JSON，返回矩形框列表。
    每项：{'label': str, 'bbox_xyxy': [x0,y0,x1,y1], 'img_w': int, 'img_h': int}
    """
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    img_w = data.get("imageWidth", 0)
    img_h = data.get("imageHeight", 0)
    boxes = []
    for shape in data.get("shapes", []):
        pts = shape.get("points", [])
        stype = shape.get("shape_type", "rectangle")
        if stype not in ("rectangle", "polygon"):
            continue
        if len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append({
            "label": shape.get("label", ""),
            "bbox_xyxy": [min(xs), min(ys), max(xs), max(ys)],
            "img_w": img_w,
            "img_h": img_h,
        })
    return boxes


# ── 雷达点云 → BEV 聚类 ───────────────────────────────────────────────────────

def pointcloud_to_bev_clusters(
    pts: np.ndarray,          # (N, 4): [x_right, y_fwd, z_up, power_dB]
    eps_m: float = DBSCAN_EPS_M,
    min_pts: int = DBSCAN_MIN_PTS,
) -> list[dict]:
    """
    BEV DBSCAN 聚类，返回簇列表。
    每项：{'az_deg', 'range_m', 'confidence', 'n_pts', 'az_std_deg'}

    confidence = n_pts * mean(power_lin) / (1 + range_m²)  归一化到 [0,1]
    """
    if len(pts) == 0:
        return []

    xy = pts[:, :2].astype(np.float64)   # (N, 2)
    pwr = pts[:, 3].astype(np.float64)

    # ── DBSCAN（优先 sklearn，无则自实现）──
    try:
        from sklearn.cluster import DBSCAN
        labels = DBSCAN(eps=eps_m, min_samples=min_pts).fit_predict(xy)
    except ImportError:
        labels = _simple_dbscan(xy, eps_m, min_pts)

    clusters = []
    for cid in np.unique(labels):
        if cid == -1:
            continue
        mask = labels == cid
        cx, cy = xy[mask, 0], xy[mask, 1]
        cp     = pwr[mask]
        n      = int(mask.sum())

        range_m  = float(np.sqrt(cx ** 2 + cy ** 2).mean())
        az_rad   = np.arctan2(cx, cy)        # atan2(x_right, y_fwd) → az right=positive
        az_deg   = float(np.degrees(np.average(az_rad, weights=10 ** (cp / 10))))
        az_std   = float(np.degrees(np.std(az_rad)))

        pwr_lin  = 10 ** (cp / 10)
        conf_raw = n * float(pwr_lin.mean()) / (1.0 + range_m ** 2 / 1e6)
        clusters.append({
            "az_deg":     az_deg,
            "range_m":    range_m,
            "confidence": conf_raw,
            "n_pts":      n,
            "az_std_deg": az_std,
        })

    # 归一化 confidence
    if clusters:
        max_c = max(c["confidence"] for c in clusters)
        if max_c > 0:
            for c in clusters:
                c["confidence"] = round(c["confidence"] / max_c, 4)

    # 按 range 升序排列
    clusters.sort(key=lambda c: c["range_m"])
    return clusters


def _simple_dbscan(xy: np.ndarray, eps: float, min_pts: int) -> np.ndarray:
    """无 sklearn 时的简易 DBSCAN。复杂度 O(N²)，仅用于点数不多时。"""
    n = len(xy)
    labels = np.full(n, -1, dtype=np.int32)
    visited = np.zeros(n, dtype=bool)
    cluster_id = 0

    def region_query(i):
        return np.where(np.linalg.norm(xy - xy[i], axis=1) <= eps)[0]

    for i in range(n):
        if visited[i]:
            continue
        visited[i] = True
        nbrs = region_query(i)
        if len(nbrs) < min_pts:
            continue
        labels[i] = cluster_id
        seed = list(nbrs)
        j = 0
        while j < len(seed):
            q = seed[j]
            if not visited[q]:
                visited[q] = True
                qnbrs = region_query(q)
                if len(qnbrs) >= min_pts:
                    seed.extend(qnbrs.tolist())
            if labels[q] == -1:
                labels[q] = cluster_id
            j += 1
        cluster_id += 1

    return labels


# ── 方位角匹配 ────────────────────────────────────────────────────────────────

def boxes_to_azimuths(boxes: list[dict], fov_deg: float) -> np.ndarray:
    """
    将 2D 框 u_center → 估算方位角（°）。

    az_box = (u_center / img_w - 0.5) * fov_deg
    （正 = 右，负 = 左）
    """
    azs = []
    for b in boxes:
        x0, _y0, x1, _y1 = b["bbox_xyxy"]
        u_center = (x0 + x1) / 2.0
        img_w = b["img_w"] or 1920
        azs.append((u_center / img_w - 0.5) * fov_deg)
    return np.array(azs, dtype=np.float64)


def find_best_delta_az(
    box_az: np.ndarray,
    cluster_az: np.ndarray,
    fov_deg: float,
    tol_deg: float = AZ_MATCH_TOL_DEG,
) -> float:
    """
    在 ±fov_deg/2 范围内搜索全局偏移 Δaz（0.2° 步长），
    使 box_az + Δaz 与 cluster_az 最近邻匹配数最多。
    """
    if len(box_az) == 0 or len(cluster_az) == 0:
        return 0.0

    # Search window limited to ±max_search_deg (extrinsics say camera ≈ body_y).
    # The small tolerance absorbs mounting and GPS heading calibration errors.
    max_search = max(min(fov_deg, AZ_MATCH_TOL_DEG), 3.0)
    best_delta = 0.0
    best_count = 0
    for delta in np.arange(-max_search, max_search + 0.1, 0.2):
        adj = box_az + delta
        count = 0
        for a in adj:
            diffs = np.abs(cluster_az - a)
            if diffs.min() <= tol_deg:
                count += 1
        if count > best_count:
            best_count = count
            best_delta = float(delta)

    return best_delta


def hungarian_match(
    box_az: np.ndarray,
    cluster_az: np.ndarray,
    delta_az: float,
    tol_deg: float = AZ_MATCH_TOL_DEG,
) -> list[int]:
    """
    Hungarian 匹配 box_az+delta_az → cluster_az，
    超过 tol_deg 的匹配标记为 -1（未匹配）。

    返回 match_ids: match_ids[i] = 对应 cluster 的索引，或 -1。
    """
    from scipy.optimize import linear_sum_assignment  # 标准库 scipy

    adj = box_az + delta_az
    nb = len(adj)
    nc = len(cluster_az)
    if nb == 0 or nc == 0:
        return [-1] * nb

    # 代价矩阵：绝对方位角差（°）
    cost = np.abs(adj[:, None] - cluster_az[None, :])   # (nb, nc)
    row_ind, col_ind = linear_sum_assignment(cost)

    match_ids = [-1] * nb
    for r, c in zip(row_ind, col_ind):
        if cost[r, c] <= tol_deg:
            match_ids[r] = int(c)

    return match_ids


# ── 单帧处理 ─────────────────────────────────────────────────────────────────

def process_one_mat(
    mat_path: Path,
    camera_name: str,
    annot_root: "Path | None",
    fov_deg: float,
    out_dir: Path,
    radar_only: bool = False,
    stem_index: "dict[str, Path] | None" = None,
) -> dict:
    """处理一个 mat 文件，返回结果字典（同时写入 out_dir/mat_stem.json）。"""

    mat_stem = mat_path.stem

    # ── 1. 提取雷达点云 + 聚类 ──
    try:
        pts, hdg0 = mmwave_pointcloud_from_mat(mat_path)
    except Exception as e:
        return {"error": str(e), "mat_name": mat_path.name}

    clusters = pointcloud_to_bev_clusters(pts)

    result: dict = {
        "mat_name":    mat_path.name,
        "camera_name": camera_name,
        "hdg0_deg":    round(float(hdg0), 2),
        "n_radar_pts": int(len(pts)),
        "clusters":    [
            {
                "az_deg":     round(c["az_deg"], 2),
                "range_m":    round(c["range_m"], 1),
                "confidence": c["confidence"],
                "n_pts":      c["n_pts"],
            }
            for c in clusters
        ],
        "boxes": [],
    }

    # ── 2. 若 radar_only 或无标注根目录，跳过匹配 ──
    if radar_only or annot_root is None or not camera_name:
        _write_result(result, out_dir, mat_stem)
        return result

    # ── 3. 找 LabelMe JSON ──
    json_path = find_annot_json(camera_name, annot_root, stem_index)
    if json_path is None:
        result["annot_note"] = "no_labelme_json"
        _write_result(result, out_dir, mat_stem)
        return result

    boxes = load_labelme_boxes(json_path)
    if not boxes:
        result["annot_note"] = "empty_annotation"
        _write_result(result, out_dir, mat_stem)
        return result

    # ── 4. 方位角匹配 ──
    box_az      = boxes_to_azimuths(boxes, fov_deg)
    cluster_az  = np.array([c["az_deg"] for c in clusters])

    delta_az    = find_best_delta_az(box_az, cluster_az, fov_deg)
    match_ids   = hungarian_match(box_az, cluster_az, delta_az)

    out_boxes = []
    for i, (box, mid) in enumerate(zip(boxes, match_ids)):
        entry: dict = {
            "label":     box["label"],
            "bbox_xyxy": [round(v, 1) for v in box["bbox_xyxy"]],
            "az_box_deg": round(float(box_az[i]), 2),
        }
        if mid >= 0:
            c = clusters[mid]
            entry["depth_m"]          = round(c["range_m"], 1)
            entry["confidence"]       = c["confidence"]
            entry["az_match_delta_deg"] = round(float(delta_az), 2)
            entry["radar_n_pts"]      = c["n_pts"]
            entry["method"]           = "azimuth_match"
        else:
            entry["depth_m"]    = None
            entry["confidence"] = 0.0
            entry["method"]     = "no_match"
        out_boxes.append(entry)

    result["boxes"]       = out_boxes
    result["delta_az_deg"] = round(float(delta_az), 2)

    _write_result(result, out_dir, mat_stem)
    return result


def _write_result(result: dict, out_dir: Path, stem: str) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{stem}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


# ── capture 目录扫描 ──────────────────────────────────────────────────────────

def _find_mat_dir(capture_dir: Path) -> Path | None:
    """搜索 capture 目录下的 mat 文件夹（支持两种命名约定）。"""
    candidates = [
        capture_dir / "mmwave_mat_1218style",
    ]
    # 匹配 *_mmwave_udp_radar/ 或 *_radar/ 风格
    for d in capture_dir.iterdir():
        if d.is_dir() and (d.name.endswith("_radar") or "mmwave_udp_radar" in d.name):
            candidates.append(d)
    for d in candidates:
        if d.exists() and any(d.glob("*.mat")):
            return d
    return None


def process_capture(
    capture_dir: Path,
    annot_root: Path | None,
    fov_deg: float,
    radar_only: bool,
) -> None:
    print(f"\n[{capture_dir.name}]")

    mat_dir = _find_mat_dir(capture_dir)
    if mat_dir is None:
        print("  ⚠ 未找到 mat 文件夹，跳过")
        return

    mat_files = sorted(mat_dir.glob("*.mat"))
    print(f"  mat 目录: {mat_dir.name}  ({len(mat_files)} 个 mat)")

    mat_cam_map = load_mat_camera_map(capture_dir)
    out_dir = capture_dir / "depth_labels"

    # 预构建 stem 索引
    _stem_index: "dict[str, Path] | None" = None
    if annot_root is not None and not radar_only:
        _cap_annot = annot_root / capture_dir.parent.name / capture_dir.name
        _base = _cap_annot if _cap_annot.exists() else annot_root
        _stem_index = _build_stem_index(_base)
        print(f"  [标注索引] 共 {len(_stem_index)} 个 JSON in {_base.name}")

    n_ok = n_miss = n_annot = 0
    for mat_path in mat_files:
        camera_name = mat_cam_map.get(mat_path.stem, "")
        res = process_one_mat(
            mat_path, camera_name, annot_root, fov_deg, out_dir, radar_only, _stem_index
        )
        n_ok += 1
        if not camera_name:
            n_miss += 1
        matched = sum(1 for b in res.get("boxes", []) if b.get("depth_m") is not None)
        total   = len(res.get("boxes", []))
        if total > 0:
            n_annot += 1
            print(f"    {mat_path.name[-40:]}  簇={len(res['clusters'])}  框={total}  命中={matched}")

    print(f"  完成: {n_ok} mat，无相机对应={n_miss}，有标注框={n_annot}")
    print(f"  输出目录: {out_dir}")


def process_capture_dir(
    capture_dir: Path,
    annot_root: "Path | None" = None,
    fov_deg: float = 20.0,
    radar_only: bool = True,
    verbose: bool = True,
    extra_annot_roots: "list[Path] | None" = None,
) -> int:
    """供 startup_check.py 调用的 API 封装，返回生成的 JSON 数量。

    extra_annot_roots: 额外的标注根目录（如 autofill_root），与 annot_root 合并建索引。
    """
    mat_dir = _find_mat_dir(capture_dir)
    if mat_dir is None:
        return 0
    mat_files = sorted(mat_dir.glob("*.mat"))
    mat_cam_map = load_mat_camera_map(capture_dir)
    out_dir = capture_dir / "depth_labels"

    # 预构建 stem 索引（避免对每个 mat 重复 rglob 搜索）
    _stem_index: "dict[str, Path] | None" = None
    if annot_root is not None and not radar_only:
        _ann_candidates: list[Path] = []
        # 主标注根
        _cap_annot = annot_root / capture_dir.parent.name / capture_dir.name
        _ann_candidates.append(_cap_annot if _cap_annot.exists() else annot_root)
        # 额外标注根（如 autofill_root）
        for _extra in (extra_annot_roots or []):
            if _extra and _extra.exists():
                _extra_cap = _extra / capture_dir.parent.name / capture_dir.name
                _ann_candidates.append(_extra_cap if _extra_cap.exists() else _extra)
        _stem_index = {}
        for _base in _ann_candidates:
            _stem_index.update(_build_stem_index(_base))
        if verbose:
            print(f"  [标注索引] 共 {len(_stem_index)} 个 JSON (来源: {len(_ann_candidates)} 个根)")

    n_ok = 0
    for mat_path in mat_files:
        camera_name = mat_cam_map.get(mat_path.stem, "")
        process_one_mat(mat_path, camera_name, annot_root, fov_deg, out_dir,
                        radar_only, _stem_index)
        n_ok += 1
    if verbose:
        print(f"[{capture_dir.name}] depth_labels: {n_ok} 个 JSON 写出")
    return n_ok


# ── 入口 ─────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="方案A：方位角匹配为相机 2D 框赋深度")
    ap.add_argument("--capture-dir", required=True, type=Path,
                    help="单个 capture 目录路径")
    ap.add_argument("--annot-root", type=Path, default=None,
                    help="LabelMe 标注根目录（含 .json 文件）。若不指定则为诊断模式")
    ap.add_argument("--fov", type=float, default=8.8,
                    help="相机水平 FoV（°），用于 u → 方位角。长焦常用 8-10°（默认 8.8°）")
    ap.add_argument("--radar-only", action="store_true",
                    help="仅输出雷达聚类，不做框匹配（诊断/调试用）")
    ap.add_argument("--root", type=Path, default=None,
                    help="批量处理：遍历 root 下所有含 mat 的 capture 目录")
    args = ap.parse_args()

    if args.root:
        # 批量模式：root/{date}/{capture}/
        cap_dirs = []
        for date_dir in sorted(args.root.iterdir()):
            if not date_dir.is_dir():
                continue
            for cap_dir in sorted(date_dir.iterdir()):
                if cap_dir.is_dir() and _find_mat_dir(cap_dir):
                    cap_dirs.append(cap_dir)
        print(f"找到 {len(cap_dirs)} 个 capture 目录")
        for cap_dir in cap_dirs:
            process_capture(cap_dir, args.annot_root, args.fov, args.radar_only)
    else:
        process_capture(args.capture_dir, args.annot_root, args.fov, args.radar_only)

    print("\n全部完成。")


if __name__ == "__main__":
    main()
