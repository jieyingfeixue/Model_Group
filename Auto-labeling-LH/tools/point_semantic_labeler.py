"""逐点语义标注器.

输入：
  pts_enu     (N, 2+) numpy 数组，前两列为 x_east, y_north (米)
  ref_latlon  (lat0, lon0) 局部切平面原点
  osm_data    osm_semantic_fetcher.fetch() 返回的 dict
  cfg         OsmLabelConfig (各类半径阈值，可选)

输出：
  labels      (N,) int 数组：0=background, 1=building, 2=tower, 3=wind_turbine

依赖：仅 numpy。
"""
from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np

CLASS_BG = 0; CLASS_BUILDING = 1; CLASS_TOWER = 2; CLASS_WIND = 3
CLASS_NAMES = {CLASS_BG: "background", CLASS_BUILDING: "building",
               CLASS_TOWER: "tower", CLASS_WIND: "wind_turbine"}

@dataclass
class OsmLabelConfig:
    building_pad_m: float = 1.0   # 多边形外扩，吸收 GPS/描绘误差
    tower_radius_m: float = 3.0   # 电塔点 -> 圆形掩膜半径
    wind_radius_m: float = 8.0    # 风机叶片半径


def latlon_to_enu(lats, lons, lat0, lon0):
    """简化局部切平面 (equirectangular)，对 <1km 范围 <0.1m 误差。"""
    lat0_rad = math.radians(lat0)
    cos_lat0 = math.cos(lat0_rad)
    e = (np.asarray(lons, np.float64) - lon0) * 111320.0 * cos_lat0
    n = (np.asarray(lats, np.float64) - lat0) * 111320.0
    return e, n


def _points_in_polygon(xs, ys, poly_xs, poly_ys):
    """raycast point-in-polygon, 矢量化对所有 (xs,ys) 测试单个多边形。返回 bool[N]."""
    n = len(poly_xs)
    inside = np.zeros(len(xs), dtype=bool)
    j = n - 1
    for i in range(n):
        xi, yi = poly_xs[i], poly_ys[i]
        xj, yj = poly_xs[j], poly_ys[j]
        cond1 = (yi > ys) != (yj > ys)
        denom = (yj - yi)
        if denom == 0:
            j = i; continue
        xints = (xj - xi) * (ys - yi) / denom + xi
        cond2 = xs < xints
        inside ^= (cond1 & cond2)
        j = i
    return inside


def _expand_polygon(poly_xs, poly_ys, pad):
    """简化外扩：朝多边形重心反方向平移每个顶点 pad 米。"""
    if pad <= 0: return poly_xs, poly_ys
    cx = float(np.mean(poly_xs)); cy = float(np.mean(poly_ys))
    dx = poly_xs - cx; dy = poly_ys - cy
    r = np.sqrt(dx*dx + dy*dy)
    r = np.where(r < 1e-6, 1.0, r)
    return poly_xs + dx / r * pad, poly_ys + dy / r * pad


def label_points(pts_enu, ref_latlon, osm_data, cfg: OsmLabelConfig = None):
    """主函数。pts_enu (N,>=2)。返回 (N,) int labels。"""
    if cfg is None: cfg = OsmLabelConfig()
    pts = np.asarray(pts_enu, np.float64)
    n_pts = pts.shape[0]
    if n_pts == 0: return np.zeros(0, np.int32)
    xs, ys = pts[:, 0], pts[:, 1]
    lat0, lon0 = ref_latlon
    labels = np.zeros(n_pts, np.int32)

    # bbox 粗筛：将点的 (xmin..xmax, ymin..ymax) 给后续多边形/点判断剔除
    pxmin, pxmax = float(xs.min()), float(xs.max())
    pymin, pymax = float(ys.min()), float(ys.max())

    # ---- buildings ----
    for b in osm_data.get("buildings", []):
        poly = b["polygon"]
        lats = [p[0] for p in poly]; lons = [p[1] for p in poly]
        pe, pn = latlon_to_enu(lats, lons, lat0, lon0)
        # bbox 剔除：多边形完全在点云包围盒外 -> skip
        if pe.max() < pxmin - cfg.building_pad_m or pe.min() > pxmax + cfg.building_pad_m:
            continue
        if pn.max() < pymin - cfg.building_pad_m or pn.min() > pymax + cfg.building_pad_m:
            continue
        if cfg.building_pad_m > 0:
            pe, pn = _expand_polygon(pe, pn, cfg.building_pad_m)
        mask = _points_in_polygon(xs, ys, pe, pn)
        labels[mask] = CLASS_BUILDING

    # ---- towers (点 + 半径) ----
    if osm_data.get("towers"):
        tlats = [t["lat"] for t in osm_data["towers"]]
        tlons = [t["lon"] for t in osm_data["towers"]]
        te, tn = latlon_to_enu(tlats, tlons, lat0, lon0)
        r2 = cfg.tower_radius_m ** 2
        for i in range(len(te)):
            if te[i] < pxmin - cfg.tower_radius_m or te[i] > pxmax + cfg.tower_radius_m: continue
            if tn[i] < pymin - cfg.tower_radius_m or tn[i] > pymax + cfg.tower_radius_m: continue
            d2 = (xs - te[i]) ** 2 + (ys - tn[i]) ** 2
            labels[(d2 <= r2) & (labels == CLASS_BG)] = CLASS_TOWER

    # ---- wind turbines ----
    if osm_data.get("winds"):
        wlats = [w["lat"] for w in osm_data["winds"]]
        wlons = [w["lon"] for w in osm_data["winds"]]
        we, wn = latlon_to_enu(wlats, wlons, lat0, lon0)
        r2 = cfg.wind_radius_m ** 2
        for i in range(len(we)):
            if we[i] < pxmin - cfg.wind_radius_m or we[i] > pxmax + cfg.wind_radius_m: continue
            if wn[i] < pymin - cfg.wind_radius_m or wn[i] > pymax + cfg.wind_radius_m: continue
            d2 = (xs - we[i]) ** 2 + (ys - wn[i]) ** 2
            labels[(d2 <= r2) & (labels == CLASS_BG)] = CLASS_WIND

    return labels


def summarize(labels):
    counts = {name: int(np.sum(labels == cls)) for cls, name in CLASS_NAMES.items()}
    total = int(labels.size)
    return {"total": total, "counts": counts,
            "ratios": {k: (v / total if total else 0.0) for k, v in counts.items()}}


if __name__ == "__main__":
    # 简单 self-test
    osm = {
        "buildings": [{"id": 1, "polygon": [(31.9941, 118.6011), (31.9942, 118.6011),
                                             (31.9942, 118.6013), (31.9941, 118.6013)]}],
        "towers": [{"id": 2, "lat": 31.9942, "lon": 118.6015}],
        "winds": [],
    }
    pts = np.array([[0, 0, 0], [10, 10, 0], [50, 0, 0]], np.float64)
    out = label_points(pts, (31.99415, 118.6012), osm)
    print("labels =", out)
    print("summary =", summarize(out))
