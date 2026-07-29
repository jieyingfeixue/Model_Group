"""多源 语义标注 - 框架集成模块.

数据源 (按优先级累加, 后写入的覆盖前面的 background 标签):
  1. OpenStreetMap (Overpass API, 扩展标签集)
       建筑面 → CLASS_BUILDING:
         * way["building"] / way["building:part"] / relation["building"]
         * way["man_made"="storage_tank"]
         * way["power"="substation"]
       塔类点 → CLASS_TOWER:
         * node["power"~"^(tower|pole)$"]
         * node/way["man_made"~"^(tower|water_tower|chimney|silo|
                                  communications_tower|antenna|mast|
                                  cooling_tower)$"] (way 取中心点)
       风机 → CLASS_WIND:
         * node["power"="generator"]["generator:source"="wind"]
         * node/way["man_made"="wind_turbine"]
  2. 手动地图标注 (geo_annotations.json, 可选, OSM 无覆盖时兜底)

输出: ENU 点云上的 4 类逐点标签:
  0 = background, 1 = building, 2 = tower, 3 = wind_turbine

特性:
  * Per-segment OSM 数据自动缓存到 ``temp/osm_cache/`` (JSON, 30 天 TTL).
  * 半径自适应: 按 nav100 HDOP 缩放 tower / wind 圆形掩膜.
  * 手动标注从 ``<capture>/geo_annotations.json`` 自动读取.

NB: 不包含 railway -- 平面投影下铁路上方有任何回波都会被误标.

被 ``src/io/adapters/lh_adapter.py`` 在 load_frame 末尾调用,
将标签写入 ``frame.meta['radar_semantic_labels']`` (numpy int32 (N,)).
"""
from __future__ import annotations
import csv, json, logging, math, time, urllib.request, urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import numpy as np

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────
CLASS_BG = 0
CLASS_BUILDING = 1
CLASS_TOWER = 2
CLASS_WIND = 3
CLASS_NAMES = {CLASS_BG: "background", CLASS_BUILDING: "building",
               CLASS_TOWER: "tower", CLASS_WIND: "wind_turbine"}

_OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

_CACHE_TTL_SEC = 30 * 24 * 3600   # 30 天


@dataclass
class OsmSemanticConfig:
    enabled: bool = True
    cache_dir: Path = Path("temp/osm_cache")
    bbox_pad_m: float = 2000.0          # 与雷达最大量程匹配; 4km 雷达取 2km 安全
    building_pad_m: float = 3.0
    tower_radius_base_m: float = 15.0   # 电塔脚架 ~10m + GPS 误差 + 方位分辨率扩展
    wind_radius_base_m: float = 25.0    # 风机叶片半径 ~40m
    # 半径自适应: radius = base + hdop_gain * (hdop - 1)
    hdop_gain_m: float = 8.0
    hdop_cap_m: float = 30.0            # 自适应上限增量
    # 高德街道瓦片建筑源: 从 webrd0*.is.autonavi.com style=8 提取建筑轮廓
    # 无需 API key; 瓦片缓存到 temp/tile_cache/; 网络不通时静默跳过
    gaode_tile_buildings: bool = True

    @classmethod
    def from_dict(cls, d: Optional[dict]) -> "OsmSemanticConfig":
        if not d: return cls()
        kw = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        if "cache_dir" in kw: kw["cache_dir"] = Path(kw["cache_dir"])
        return cls(**kw)


# ── Overpass 拉取 + 缓存 ────────────────────────────────────────────────────

def _cache_key(bbox, precision=4):
    s, w, n, e = bbox
    return f"osm_{s:.{precision}f}_{w:.{precision}f}_{n:.{precision}f}_{e:.{precision}f}.json"


def _query_overpass(query: str, timeout: int = 60):
    last_err = None
    for url in _OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(
                url, data=("data=" + query).encode("utf-8"),
                headers={"User-Agent": "lh-semantic-osm/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            logger.warning("Overpass %s failed: %s; retrying", url, e)
            time.sleep(2)
    raise RuntimeError(f"all Overpass endpoints failed: {last_err}")


def _build_query(bbox, timeout=60):
    s, w, n, e = bbox
    # 注意: 故意不包含 railway -- BEV 标注会把铁路上方任何回波误标
    # 扩大召回: 覆盖国内 OSM 常见的雷达可见结构 (man_made 高大设施、变电站、电杆)
    # 以降低对手工标注的依赖
    _M = "tower|water_tower|chimney|silo|storage_tank|communications_tower|antenna|mast|cooling_tower"
    return f"""[out:json][timeout:{timeout}];
(
  way["building"]({s},{w},{n},{e});
  way["building:part"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
  way["man_made"~"^({_M})$"]({s},{w},{n},{e});
  way["power"="substation"]({s},{w},{n},{e});
  node["power"="tower"]({s},{w},{n},{e});
  node["power"="pole"]({s},{w},{n},{e});
  node["man_made"~"^({_M})$"]({s},{w},{n},{e});
  node["power"="generator"]["generator:source"="wind"]({s},{w},{n},{e});
  node["man_made"="wind_turbine"]({s},{w},{n},{e});
  way["man_made"="wind_turbine"]({s},{w},{n},{e});
);
out body geom;"""


# man_made 中视为塔类点目标 (狭窄、垂直、雷达单点回波)
_MANMADE_TOWER = {
    "tower", "water_tower", "chimney", "silo",
    "communications_tower", "antenna", "mast", "cooling_tower",
}
# man_made 中视为建筑面目标 (有水平面积、雷达多点回波)
_MANMADE_BUILDING_AREA = {"storage_tank"}


def _parse_overpass(data):
    buildings, towers, winds = [], [], []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        etype = el.get("type"); eid = el.get("id")
        if etype == "way":
            geom = el.get("geometry") or []
            poly = [(g["lat"], g["lon"]) for g in geom if "lat" in g and "lon" in g]
            if len(poly) < 3:
                continue
            mm = tags.get("man_made", "")
            if "building" in tags or "building:part" in tags or tags.get("power") == "substation":
                buildings.append({"id": eid, "polygon": poly})
            elif mm in _MANMADE_BUILDING_AREA:
                buildings.append({"id": eid, "polygon": poly})
            elif mm in _MANMADE_TOWER:
                # 多边形足迹的塔结构: 用中心点视为单塔
                clat = sum(p[0] for p in poly) / len(poly)
                clon = sum(p[1] for p in poly) / len(poly)
                towers.append({"id": eid, "lat": clat, "lon": clon})
            elif mm == "wind_turbine":
                clat = sum(p[0] for p in poly) / len(poly)
                clon = sum(p[1] for p in poly) / len(poly)
                winds.append({"id": eid, "lat": clat, "lon": clon})
        elif etype == "relation" and "building" in tags:
            for m in el.get("members", []):
                if m.get("role") == "outer" and "geometry" in m:
                    poly = [(g["lat"], g["lon"]) for g in m["geometry"]]
                    if len(poly) >= 3:
                        buildings.append({"id": eid, "polygon": poly}); break
        elif etype == "node":
            lat, lon = el.get("lat"), el.get("lon")
            if lat is None or lon is None: continue
            mm = tags.get("man_made", "")
            if tags.get("power") in ("tower", "pole"):
                towers.append({"id": eid, "lat": lat, "lon": lon})
            elif mm in _MANMADE_TOWER:
                towers.append({"id": eid, "lat": lat, "lon": lon})
            elif mm == "wind_turbine":
                winds.append({"id": eid, "lat": lat, "lon": lon})
            elif tags.get("power") == "generator" and tags.get("generator:source") == "wind":
                winds.append({"id": eid, "lat": lat, "lon": lon})
    return {"buildings": buildings, "towers": towers, "winds": winds}


# 模块级 in-memory 缓存 (key=cache_path str)
_MEM_CACHE: dict[str, dict] = {}

# 默认配置单例 (从 default.yaml semantic_osm 段读取)
_DEFAULT_CFG: Optional["OsmSemanticConfig"] = None


def get_default_config() -> "OsmSemanticConfig":
    """从 default.yaml 的 semantic_osm 段读取配置 (惰性 + 缓存)。"""
    global _DEFAULT_CFG
    if _DEFAULT_CFG is not None:
        return _DEFAULT_CFG
    try:
        from src.core.config import load_config
        cfg_dict = load_config().get("semantic_osm", {})
        _DEFAULT_CFG = OsmSemanticConfig.from_dict(cfg_dict)
    except Exception as exc:
        logger.debug("load semantic_osm config failed: %s; using defaults", exc)
        _DEFAULT_CFG = OsmSemanticConfig()
    return _DEFAULT_CFG


def fetch_osm(bbox, cache_dir: Path, force: bool = False) -> dict:
    """获取 bbox 内的 OSM 数据; 三层缓存: 内存 -> 磁盘 JSON -> Overpass。"""
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / _cache_key(bbox)
    cache_key = str(cache_path)

    if not force and cache_key in _MEM_CACHE:
        return _MEM_CACHE[cache_key]

    if not force and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < _CACHE_TTL_SEC:
            try:
                with open(cache_path, encoding="utf-8") as fh:
                    data = json.load(fh)
                _MEM_CACHE[cache_key] = data
                return data
            except Exception as e:
                logger.warning("OSM cache read failed (%s); refetching", e)

    logger.info("Fetching OSM bbox=%s", bbox)
    data = _query_overpass(_build_query(bbox))
    result = {"bbox": list(bbox), **_parse_overpass(data)}
    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
    except Exception as e:
        logger.warning("OSM cache write failed: %s", e)
    _MEM_CACHE[cache_key] = result
    return result


# ── bbox / hdop 辅助 ────────────────────────────────────────────────────────

def bbox_from_segment(seg_dir: Path, pad_m: float = 2000.0):
    """从 nav100__state.csv 读取轨迹 bbox 并外扩 pad_m 米。"""
    cands = list(seg_dir.glob("nav100_state/**/nav100__state.csv"))
    if not cands: cands = list(seg_dir.glob("**/nav100__state.csv"))
    if not cands: return None
    lats, lons = [], []
    try:
        with open(cands[0], newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try: lats.append(float(row["latitude"])); lons.append(float(row["longitude"]))
                except (KeyError, ValueError): continue
    except Exception as e:
        logger.warning("nav100 bbox load failed: %s", e); return None
    if not lats: return None
    lat0 = sum(lats) / len(lats)
    pad_lat = pad_m / 111320.0
    pad_lon = pad_m / (111320.0 * math.cos(math.radians(lat0)))
    return (min(lats)-pad_lat, min(lons)-pad_lon, max(lats)+pad_lat, max(lons)+pad_lon)


_HDOP_CACHE: dict[Path, object] = {}  # seg_dir -> (t_arr, hdop_arr) | None

def load_hdop_series(seg_dir: Path):
    """读取 nav100__state.csv 的 (relative_time_sec, hdop)。"""
    if seg_dir in _HDOP_CACHE: return _HDOP_CACHE[seg_dir]
    cands = list(seg_dir.glob("nav100_state/**/nav100__state.csv"))
    if not cands: cands = list(seg_dir.glob("**/nav100__state.csv"))
    if not cands:
        _HDOP_CACHE[seg_dir] = None; return None
    t, h = [], []
    try:
        with open(cands[0], newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                try:
                    t.append(float(row["relative_time_sec"]))
                    h.append(float(row["hdop"]))
                except (KeyError, ValueError): continue
    except Exception:
        _HDOP_CACHE[seg_dir] = None; return None
    if not t: _HDOP_CACHE[seg_dir] = None; return None
    out = (np.asarray(t, np.float64), np.asarray(h, np.float64))
    _HDOP_CACHE[seg_dir] = out
    return out


def hdop_at(seg_dir: Path, t_sec: float) -> float:
    """t_sec 时刻插值 HDOP。无数据时返回 1.0 (无加成)。"""
    s = load_hdop_series(seg_dir)
    if s is None: return 1.0
    t, h = s
    return float(np.interp(t_sec, t, h))


# ── 几何标注 ────────────────────────────────────────────────────────────────

def _latlon_to_enu(lats, lons, lat0, lon0):
    """局部等矩形投影 (~<1km 误差 <0.1m)。"""
    cos_lat0 = math.cos(math.radians(lat0))
    e = (np.asarray(lons, np.float64) - lon0) * 111320.0 * cos_lat0
    n = (np.asarray(lats, np.float64) - lat0) * 111320.0
    return e, n


def _points_in_polygon(xs, ys, poly_xs, poly_ys):
    n = len(poly_xs)
    inside = np.zeros(len(xs), dtype=bool)
    j = n - 1
    for i in range(n):
        xi, yi = poly_xs[i], poly_ys[i]
        xj, yj = poly_xs[j], poly_ys[j]
        denom = (yj - yi)
        if denom == 0:
            j = i; continue
        cond1 = (yi > ys) != (yj > ys)
        xints = (xj - xi) * (ys - yi) / denom + xi
        inside ^= (cond1 & (xs < xints))
        j = i
    return inside


def _expand_polygon(poly_xs, poly_ys, pad):
    if pad <= 0: return poly_xs, poly_ys
    cx = float(np.mean(poly_xs)); cy = float(np.mean(poly_ys))
    dx = poly_xs - cx; dy = poly_ys - cy
    r = np.sqrt(dx*dx + dy*dy); r = np.where(r < 1e-6, 1.0, r)
    return poly_xs + dx / r * pad, poly_ys + dy / r * pad


def label_points_enu(pts_enu, ref_latlon, osm_data, *,
                     building_pad: float = 1.0,
                     tower_radius: float = 3.0,
                     wind_radius: float = 8.0) -> np.ndarray:
    """主标注函数; pts_enu (N,>=2) ENU 米制. 返回 (N,) int32 标签。"""
    pts = np.asarray(pts_enu, np.float64)
    n_pts = pts.shape[0]
    if n_pts == 0: return np.zeros(0, np.int32)
    xs, ys = pts[:, 0], pts[:, 1]
    lat0, lon0 = ref_latlon
    labels = np.zeros(n_pts, np.int32)
    pxmin, pxmax = float(xs.min()), float(xs.max())
    pymin, pymax = float(ys.min()), float(ys.max())

    # buildings
    for b in osm_data.get("buildings", []):
        poly = b["polygon"]
        lats = [p[0] for p in poly]; lons = [p[1] for p in poly]
        pe, pn = _latlon_to_enu(lats, lons, lat0, lon0)
        if pe.max() < pxmin - building_pad or pe.min() > pxmax + building_pad: continue
        if pn.max() < pymin - building_pad or pn.min() > pymax + building_pad: continue
        if building_pad > 0: pe, pn = _expand_polygon(pe, pn, building_pad)
        mask = _points_in_polygon(xs, ys, pe, pn)
        labels[mask] = CLASS_BUILDING

    # towers
    if osm_data.get("towers"):
        tlats = [t["lat"] for t in osm_data["towers"]]
        tlons = [t["lon"] for t in osm_data["towers"]]
        te, tn = _latlon_to_enu(tlats, tlons, lat0, lon0)
        r2 = tower_radius ** 2
        for i in range(len(te)):
            if te[i] < pxmin - tower_radius or te[i] > pxmax + tower_radius: continue
            if tn[i] < pymin - tower_radius or tn[i] > pymax + tower_radius: continue
            d2 = (xs - te[i]) ** 2 + (ys - tn[i]) ** 2
            labels[(d2 <= r2) & (labels == CLASS_BG)] = CLASS_TOWER

    # winds
    if osm_data.get("winds"):
        wlats = [w["lat"] for w in osm_data["winds"]]
        wlons = [w["lon"] for w in osm_data["winds"]]
        we, wn = _latlon_to_enu(wlats, wlons, lat0, lon0)
        r2 = wind_radius ** 2
        for i in range(len(we)):
            if we[i] < pxmin - wind_radius or we[i] > pxmax + wind_radius: continue
            if wn[i] < pymin - wind_radius or wn[i] > pymax + wind_radius: continue
            d2 = (xs - we[i]) ** 2 + (ys - wn[i]) ** 2
            labels[(d2 <= r2) & (labels == CLASS_BG)] = CLASS_WIND

    return labels


# ── 主入口: 集成到 lh_adapter 的便捷函数 ────────────────────────────────────

def annotate_frame(*, pts_body, body_heading_deg, ref_lat, ref_lon,
                   seg_dir, t_ref, cfg: OsmSemanticConfig) -> Optional[np.ndarray]:
    """对当前帧 body-frame 雷达点云做 OSM 语义标注。

    参数
    ----
    pts_body : (N,>=2) 雷达点云, 列 0/1 = x_right, y_fwd (米); 已 heading-corrected
               到当前相机帧 (即 body 朝向 == 当前 gps 航向 body_heading_deg)。
    body_heading_deg : 当前帧航向 (°, 北起顺时针)。用于 body -> ENU 旋转。
    ref_lat, ref_lon : ENU 原点 (建议传 fd.meta['gps_lat'/'gps_lon'])。
    seg_dir : segment 目录, 用于 nav100 bbox + hdop 自适应。
    t_ref   : 当前帧 relative_time_sec, 用于 hdop 插值。
    cfg     : OsmSemanticConfig.

    返回
    ----
    labels : (N,) int32 或 None (失败/禁用时)。
    """
    if not cfg.enabled or pts_body is None or pts_body.shape[0] == 0:
        return None

    bbox = bbox_from_segment(seg_dir, cfg.bbox_pad_m)
    if bbox is None:
        logger.debug("annotate_frame: no nav100 bbox"); return None

    try:
        osm = fetch_osm(bbox, cfg.cache_dir)
    except Exception as exc:
        logger.warning("OSM fetch failed: %s", exc); return None

    # ── 本地大规模建筑足迹源 (Overture / Geofabrik / 用户自带 GeoJSON) ──
    # 由 tools/extract_overture_buildings.py 离线生成的
    # temp/buildings_local/buildings.geojson 是 FeatureCollection,
    # 每个 feature 是 Polygon, 几何为 [lon, lat]. 适合补全 China 区域
    # OSM 楼房稀疏的问题. 文件不存在时静默跳过 (零开销).
    try:
        extra_b = _load_local_buildings(bbox)
        if extra_b:
            osm = dict(osm)  # don't mutate cached dict
            osm["buildings"] = list(osm.get("buildings", [])) + extra_b
            logger.info("local-buildings: +%d (within bbox)", len(extra_b))
    except Exception as exc:
        logger.debug("local-buildings load failed: %s", exc)

    # ── 高德地图街道瓦片建筑源 ──────────────────────────────────────────
    # 从高德街道瓦片 (style=8) 提取建筑轮廓, 无需 API key.
    # 颜色阈值分割 + OpenCV 轮廓提取 → WGS-84 多边形.
    # 瓦片缓存到 temp/tile_cache/ (1小时 TTL); 网络不通时静默跳过.
    if cfg.gaode_tile_buildings:
        try:
            from src.io.gaode_buildings import fetch_gaode_buildings
            lat_min, lon_min, lat_max, lon_max = bbox
            tile_b = fetch_gaode_buildings(lat_min, lon_min, lat_max, lon_max)
            if tile_b:
                osm = dict(osm) if not isinstance(osm, dict) else osm
                osm["buildings"] = list(osm.get("buildings", [])) + tile_b
                logger.info("gaode-tile-buildings: +%d (within bbox)", len(tile_b))
        except Exception as exc:
            logger.debug("gaode-tile-buildings load failed: %s", exc)

    # body -> ENU
    h0 = math.radians(body_heading_deg)
    c, s = math.cos(h0), math.sin(h0)
    xr = np.asarray(pts_body[:, 0], np.float64)
    yr = np.asarray(pts_body[:, 1], np.float64)
    E = xr * c + yr * s
    N = -xr * s + yr * c

    # 自适应半径
    hdop = hdop_at(seg_dir, t_ref) if t_ref is not None else 1.0
    bonus = min(cfg.hdop_gain_m * max(hdop - 1.0, 0.0), cfg.hdop_cap_m)
    tower_r = cfg.tower_radius_base_m + bonus
    wind_r  = cfg.wind_radius_base_m + bonus
    bld_pad = cfg.building_pad_m + 0.5 * bonus

    pts_enu = np.column_stack([E, N])
    labels = label_points_enu(pts_enu, (ref_lat, ref_lon), osm,
                              building_pad=bld_pad,
                              tower_radius=tower_r,
                              wind_radius=wind_r)

    # ── 多源协同: 叠加手动地图标注 (geo_annotations.json) ────────────
    # 用户在 MapPanel 上画的多边形会持久化到 capture 目录, 用于补全
    # OSM 中缺失的 building (国内 OSM 楼房稀疏问题). 这里把这些手画
    # 多边形作为 "高优先级" 源, 覆盖背景标签.
    try:
        manual = _load_manual_annotations(seg_dir)
        if manual:
            _apply_manual_polygons(labels, pts_enu, ref_lat, ref_lon, manual)
    except Exception as exc:
        logger.debug("manual annotations merge failed: %s", exc)

    return labels


# ── 手动标注源 ─────────────────────────────────────────────────────────────

def _find_geo_annotations_file(seg_dir: Path) -> Optional[Path]:
    """向上查找 geo_annotations.json.

    MapPanel 把它保存在 ``<capture_dir>/geo_annotations.json``,
    其中 capture_dir = mat_path.parent.parent.parent (mat 在
    segment/radar_mmwave/.../xxx.mat). 不同布局下 capture_dir 相对
    seg_dir 的层级不一致, 因此向上找最多 4 层.
    """
    p = Path(seg_dir).resolve()
    for _ in range(5):
        f = p / "geo_annotations.json"
        if f.exists():
            return f
        if p.parent == p:
            break
        p = p.parent
    return None


# ── 本地建筑足迹源 (Overture / Geofabrik / 自带 GeoJSON) ───────────────────
# 文件路径: <project>/temp/buildings_local/buildings.geojson
# 由 tools/extract_overture_buildings.py 离线产出.
# 格式: GeoJSON FeatureCollection, 每 feature 几何 Polygon ([lon, lat]).

_LOCAL_BUILDINGS_PATH = Path("temp/buildings_local/buildings.geojson")
_LOCAL_BUILDINGS_CACHE: Optional[list] = None  # 全部 polygons (lat, lon)
_LOCAL_BUILDINGS_MTIME: float = 0.0


def _load_local_buildings_all() -> list:
    """加载本地 GeoJSON 建筑足迹 (内存缓存; 按 mtime 自动失效)."""
    global _LOCAL_BUILDINGS_CACHE, _LOCAL_BUILDINGS_MTIME
    f = _LOCAL_BUILDINGS_PATH
    if not f.exists():
        return []
    try:
        mt = f.stat().st_mtime
    except OSError:
        return []
    if _LOCAL_BUILDINGS_CACHE is not None and mt == _LOCAL_BUILDINGS_MTIME:
        return _LOCAL_BUILDINGS_CACHE
    try:
        with open(f, encoding="utf-8") as fh:
            gj = json.load(fh)
    except Exception as exc:
        logger.warning("local buildings load failed: %s", exc)
        return []
    out = []
    for i, feat in enumerate(gj.get("features", [])):
        geom = feat.get("geometry") or {}
        gtype = geom.get("type")
        coords = geom.get("coordinates")
        if not coords:
            continue
        if gtype == "Polygon":
            rings = [coords[0]]
        elif gtype == "MultiPolygon":
            rings = [c[0] for c in coords]
        else:
            continue
        for ring in rings:
            poly = [(float(p[1]), float(p[0])) for p in ring if len(p) >= 2]
            if len(poly) >= 3:
                out.append({"id": f"local_{i}", "polygon": poly})
    _LOCAL_BUILDINGS_CACHE = out
    _LOCAL_BUILDINGS_MTIME = mt
    logger.info("local buildings loaded: %d polygons from %s", len(out), f)
    return out


def _load_local_buildings(bbox) -> list:
    """返回与 bbox 相交的本地建筑足迹."""
    all_b = _load_local_buildings_all()
    if not all_b:
        return []
    s, w, n, e = bbox
    out = []
    for b in all_b:
        lats = [p[0] for p in b["polygon"]]
        lons = [p[1] for p in b["polygon"]]
        if max(lats) < s or min(lats) > n or max(lons) < w or min(lons) > e:
            continue
        out.append(b)
    return out


def _load_manual_annotations(seg_dir: Optional[Path]) -> list:
    """读取手动标注列表. 返回 [{polygon:[(lat,lon),...], class_name:str}, ...]."""
    if seg_dir is None:
        return []
    f = _find_geo_annotations_file(Path(seg_dir))
    if f is None:
        return []
    try:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        logger.warning("read %s failed: %s", f, exc)
        return []
    out = []
    for a in data.get("annotations", []):
        poly = a.get("polygon")
        cls  = a.get("class_name")
        if not poly or not cls:
            continue
        # 兼容 [lat, lon] 嵌套或 (lat, lon) 元组
        try:
            poly_t = [(float(p[0]), float(p[1])) for p in poly if len(p) >= 2]
        except Exception:
            continue
        if len(poly_t) >= 3:
            out.append({"polygon": poly_t, "class_name": str(cls)})
    return out


def _apply_manual_polygons(labels: np.ndarray, pts_enu: np.ndarray,
                           ref_lat: float, ref_lon: float,
                           manual: list) -> None:
    """对每个手动多边形, 把内部 ENU 点的 label 改为对应类别 (in-place).

    优先级: 手动 > OSM. 即手动标注可以覆盖 OSM 给出的 background, 也可
    以从 background 升级到 building/tower/wind. 不会下降到 background.
    """
    if pts_enu.shape[0] == 0:
        return
    xs, ys = pts_enu[:, 0], pts_enu[:, 1]
    _NAME_TO_CLS = {
        # 英文
        "building": CLASS_BUILDING, "tower": CLASS_TOWER,
        "wind_turbine": CLASS_WIND, "wind": CLASS_WIND,
        # 中文 (MapPanel.combo_class 下拉项)
        "建筑物": CLASS_BUILDING, "楼房": CLASS_BUILDING, "楼": CLASS_BUILDING,
        "发电塔": CLASS_WIND, "风机": CLASS_WIND, "风力发电机": CLASS_WIND,
        "输电线塔": CLASS_TOWER, "电塔": CLASS_TOWER, "电杆": CLASS_TOWER,
        "塔": CLASS_TOWER,
    }
    n_applied = 0
    for a in manual:
        cls = _NAME_TO_CLS.get(a["class_name"].lower())
        if cls is None:
            # 尝试不 lower 的中文别名查找
            cls = _NAME_TO_CLS.get(a["class_name"])
        if cls is None:
            continue
        lats = [p[0] for p in a["polygon"]]
        lons = [p[1] for p in a["polygon"]]
        pe, pn = _latlon_to_enu(lats, lons, ref_lat, ref_lon)
        mask = _points_in_polygon(xs, ys, pe, pn)
        # 只升级 background (不覆盖 OSM 已确认的更具体标签如 tower)
        upgrade = mask & (labels == CLASS_BG)
        labels[upgrade] = cls
        n_applied += int(upgrade.sum())
    if n_applied:
        logger.info("manual annotations: %d pts upgraded from bg", n_applied)
