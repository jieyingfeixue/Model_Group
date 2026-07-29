"""自动标注雷达 (Radar-only auto-labeling).

利用毫米波雷达点云 + OSM 语义标签 (building/tower/wind_turbine) 自动生成
3D 框. 不依赖图像/SAM/depth, 适合远距离/夜间/恶劣天气场景.

流程:
    radar pts (body frame) ─►  按语义标签分组
                                │
                                ▼
                       BEV 网格连通域聚类 (纯 numpy)
                                │
                                ▼
                   AABB + 类别默认高度 → Label3D
                                │
                                ▼
                        NMS (BEV IoU) 去重

类别默认尺寸 (L, W, H, m):
    tower         : 3 × 3 × 30   (输电铁塔)
    wind_turbine  : 5 × 5 × 80   (风机塔筒)
    building      : 由 BEV 实际范围决定, 高度 8m
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np

from src.core.types import FrameData, Label3D

logger = logging.getLogger(__name__)

# 与 semantic_osm.CLASS_* 对齐 (避免循环导入, 硬编码)
_CLASS_BG          = 0
_CLASS_BUILDING    = 1
_CLASS_TOWER       = 2
_CLASS_WIND        = 3
_CLASS_NAMES       = {1: "building", 2: "tower", 3: "wind_turbine"}

# 每类的默认几何 (米) 与聚类参数
_DEFAULTS: dict[int, dict] = {
    _CLASS_TOWER:    dict(L=3.0,  W=3.0,  H=30.0, cluster_r=8.0,  min_pts=2),
    _CLASS_WIND:     dict(L=5.0,  W=5.0,  H=80.0, cluster_r=15.0, min_pts=2),
    _CLASS_BUILDING: dict(L=None, W=None, H=8.0,  cluster_r=4.0,  min_pts=3),
}


def _bev_grid_cluster(xy: np.ndarray, radius: float, min_pts: int) -> list[np.ndarray]:
    """BEV 网格连通域聚类 (纯 numpy, 无 scipy 依赖).

    Parameters
    ----------
    xy : (N,2) float
    radius : 等价于网格大小; 同 cell 或 8 邻接 cell 内的点视为同一类
    min_pts : 聚类最少点数, 小于此数的簇丢弃

    Returns
    -------
    list[np.ndarray]   每项是该簇成员的索引数组 (相对于 xy 的行号)
    """
    if xy.shape[0] == 0:
        return []
    cell = max(radius, 1e-3)
    ij = np.floor(xy / cell).astype(np.int64)
    # 按 (i, j) 分桶
    buckets: dict[tuple[int, int], list[int]] = {}
    for k, (i, j) in enumerate(ij):
        buckets.setdefault((int(i), int(j)), []).append(k)

    # 8-邻接并查集
    parent: dict[tuple[int, int], tuple[int, int]] = {key: key for key in buckets}

    def _find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a, b):
        ra, rb = _find(a), _find(b)
        if ra != rb:
            parent[ra] = rb

    neigh = [(dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
    for key in list(buckets.keys()):
        for dx, dy in neigh:
            nb = (key[0] + dx, key[1] + dy)
            if nb in buckets:
                _union(key, nb)

    # 汇集每个根的所有点
    groups: dict[tuple[int, int], list[int]] = {}
    for key, idxs in buckets.items():
        root = _find(key)
        groups.setdefault(root, []).extend(idxs)

    return [np.asarray(v, dtype=np.int64) for v in groups.values()
            if len(v) >= min_pts]


def _box_from_cluster(pts: np.ndarray, cls: int, score: float) -> Label3D:
    """从一个簇 (M,3) 生成 Label3D. cls 为语义类别整数 (1/2/3)."""
    cfg = _DEFAULTS.get(cls, _DEFAULTS[_CLASS_TOWER])
    xy_min = pts[:, :2].min(axis=0)
    xy_max = pts[:, :2].max(axis=0)
    xy_ctr = (xy_min + xy_max) / 2.0

    if cfg["L"] is None:
        # 建筑物: 按 AABB 实际范围 (加余量), 保证 >= 5m
        L = float(max(5.0, xy_max[0] - xy_min[0] + 1.0))
        W = float(max(5.0, xy_max[1] - xy_min[1] + 1.0))
    else:
        L, W = float(cfg["L"]), float(cfg["W"])
    H = float(cfg["H"])

    # 中心 z = 类别默认高度的一半 (用户指明不考虑 z, 故只是占位)
    center = np.array([xy_ctr[0], xy_ctr[1], H / 2.0], dtype=np.float64)
    dims   = np.array([L, W, H], dtype=np.float64)

    box = Label3D(
        class_name=_CLASS_NAMES.get(cls, f"class_{cls}"),
        center=center,
        dimensions=dims,
        rotation=0.0,
        score=float(score),
        source="auto_radar",
    )
    box.attributes = dict(
        n_points=int(pts.shape[0]),
        semantic_class=int(cls),
        height_fixed=True,
    )
    return box


def _bev_iou(a: Label3D, b: Label3D) -> float:
    a_l, a_w = float(a.dimensions[0]), float(a.dimensions[1])
    b_l, b_w = float(b.dimensions[0]), float(b.dimensions[1])
    a_x, a_y = float(a.center[0]), float(a.center[1])
    b_x, b_y = float(b.center[0]), float(b.center[1])
    ax1, ay1 = a_x - a_l / 2, a_y - a_w / 2
    ax2, ay2 = a_x + a_l / 2, a_y + a_w / 2
    bx1, by1 = b_x - b_l / 2, b_y - b_w / 2
    bx2, by2 = b_x + b_l / 2, b_y + b_w / 2
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    union = a_l * a_w + b_l * b_w - inter
    return inter / union if union > 1e-6 else 0.0


def _nms(boxes: list[Label3D], iou_thr: float = 0.4) -> list[Label3D]:
    boxes = sorted(boxes, key=lambda b: -b.score)
    kept: list[Label3D] = []
    for b in boxes:
        if all(b.class_name != k.class_name or _bev_iou(b, k) < iou_thr for k in kept):
            kept.append(b)
    return kept


def run_auto_label_radar(
    frame: FrameData,
    app_config: dict | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> list[Label3D]:
    """对单帧执行雷达-语义自动标注. 不需要图像/depth/SAM.

    Returns
    -------
    list[Label3D]  按 (类别, score) 排序; 空帧/无语义时返回 [].
    """
    _ = app_config  # 暂未使用; 保留签名兼容
    if frame is None or "radar_mmwave" not in frame.pointclouds:
        return []
    pts = frame.pointclouds["radar_mmwave"]
    labels = frame.meta.get("radar_semantic_labels")
    if pts is None or pts.shape[0] == 0 or labels is None:
        return []
    if pts.shape[0] != labels.shape[0]:
        logger.warning("auto_label_radar: pts/labels size mismatch (%d vs %d)",
                       pts.shape[0], labels.shape[0])
        return []

    out: list[Label3D] = []
    n_cls = len(_DEFAULTS)
    for ci, cls in enumerate(sorted(_DEFAULTS.keys())):
        if progress:
            progress(f"cluster/{_CLASS_NAMES[cls]}", int(ci / n_cls * 70))
        mask = (labels == cls)
        if not mask.any():
            continue
        cls_pts = pts[mask, :3]
        cfg = _DEFAULTS[cls]
        clusters = _bev_grid_cluster(cls_pts[:, :2], cfg["cluster_r"], cfg["min_pts"])
        if not clusters:
            continue
        for idxs in clusters:
            cluster_pts = cls_pts[idxs]
            # score: 点数饱和到 [0.3, 0.95]
            n_pts = cluster_pts.shape[0]
            score = float(min(0.95, 0.3 + 0.05 * n_pts))
            out.append(_box_from_cluster(cluster_pts, cls, score))

    # ── OSM-free fallback 已移除 ───────────────────────────────────────
    # 用户要求仅依赖地图标注源 (OSM/手动多边形). 若发现 building 缺失,
    # 应通过 MapPanel 的 "标注" 功能手动在地图上画多边形, 或扩充
    # OSM building 数据 (参见 semantic_osm._build_query).

    if progress:
        progress("nms", 90)
    out = _nms(out, iou_thr=0.4)
    out.sort(key=lambda b: (b.class_name, -b.score))
    if progress:
        progress("done", 100)
    logger.info("auto_label_radar: %d boxes from %d radar pts",
                len(out), pts.shape[0])
    return out
