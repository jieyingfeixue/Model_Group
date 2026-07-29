"""从高德地图街道瓦片提取建筑轮廓.

原理
----
1. 按给定 bbox 下载高德街道瓦片 (style=8, GCJ-02, zoom 17).
2. 拼合成一张马赛克图像.
3. 用 HSV 颜色阈值分割建筑像素:
   - 背景地面: warm beige (252,249,242), V≈252, S≈10
   - 道路白色: (254,254,254), V≈254, S≈0
   - 建筑灰米色: (230-244,228-242,222-236), V≈228-244, S≈8-18
4. 形态学去噪 → findContours → 多边形近似.
5. 像素坐标 → GCJ-02 → WGS-84 返回多边形列表.

依赖: PIL, numpy, cv2 (均已在 venv 安装)
缓存: temp/tile_cache/ (按 bbox 哈希分区)

被 semantic_osm.py 调用, 返回值格式与 _load_local_buildings 相同:
  [{"id": str, "polygon": [(lat, lon), ...], "source": "gaode_tile"}, ...]
"""
from __future__ import annotations

import hashlib
import io
import logging
import math
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────────────────────

_TILE_CACHE_DIR = Path("temp/tile_cache")
_TILE_ZOOM = 17

# 高德街道瓦片 URL (GCJ-02 / Web Mercator)
_GAODE_SERVERS = [1, 2, 3, 4]
_GAODE_URL = (
    "https://webrd0{n}.is.autonavi.com/appmaptile"
    "?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"
)

# 建筑 HSV 阈值 (OpenCV H:0-180, S:0-255, V:0-255)
# 背景地面: warm beige V~252 S~10
# 建筑: 稍暗 V~228-244, S~8-18, H~14-22
# 道路:  near-white V~252-255, S~0-5
_BLD_S_MIN = 5    # 饱和度下限 (去除纯白道路)
_BLD_S_MAX = 22   # 饱和度上限 (去除绿地/水体)
_BLD_V_MIN = 180  # 亮度下限 (去除阴影/文字)
_BLD_V_MAX = 247  # 亮度上限 (去除背景/道路)

_MIN_AREA_PX = 100   # 最小轮廓面积 (像素²), 过滤地图标注噪声
_CONTOUR_EPSILON = 3  # 多边形近似精度 (像素)
_REQUEST_TIMEOUT = 15  # 单瓦片下载超时 (秒)


# ── GCJ-02 ↔ WGS-84 ─────────────────────────────────────────────────────────

def _gcj02_to_wgs84(lat: float, lon: float) -> tuple[float, float]:
    """GCJ-02 → WGS-84 (近似逆变换)."""
    a, ee = 6_378_245.0, 0.006_693_421_622_965_943
    x = lon - 105.0
    y = lat - 35.0
    dlat = (
        -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * abs(x) ** 0.5
        + (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
        + (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
        + (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    )
    dlon = (
        300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * abs(x) ** 0.5
        + (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
        + (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
        + (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    )
    rad = math.radians(lat)
    magic = 1 - ee * math.sin(rad) ** 2
    sq = math.sqrt(magic)
    dlat = dlat * 180 / ((a * (1 - ee)) / (magic * sq) * math.pi)
    dlon = dlon * 180 / (a / sq * math.cos(rad) * math.pi)
    # 正变换偏移量取负得近似逆变换
    return lat - dlat, lon - dlon


def _wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02."""
    a, ee = 6_378_245.0, 0.006_693_421_622_965_943
    x = lon - 105.0
    y = lat - 35.0
    dlat = (
        -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * abs(x) ** 0.5
        + (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
        + (20 * math.sin(y * math.pi) + 40 * math.sin(y / 3 * math.pi)) * 2 / 3
        + (160 * math.sin(y / 12 * math.pi) + 320 * math.sin(y * math.pi / 30)) * 2 / 3
    )
    dlon = (
        300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * abs(x) ** 0.5
        + (20 * math.sin(6 * x * math.pi) + 20 * math.sin(2 * x * math.pi)) * 2 / 3
        + (20 * math.sin(x * math.pi) + 40 * math.sin(x / 3 * math.pi)) * 2 / 3
        + (150 * math.sin(x / 12 * math.pi) + 300 * math.sin(x / 30 * math.pi)) * 2 / 3
    )
    rad = math.radians(lat)
    magic = 1 - ee * math.sin(rad) ** 2
    sq = math.sqrt(magic)
    dlat = dlat * 180 / ((a * (1 - ee)) / (magic * sq) * math.pi)
    dlon = dlon * 180 / (a / sq * math.cos(rad) * math.pi)
    return lat + dlat, lon + dlon


# ── 瓦片坐标 ─────────────────────────────────────────────────────────────────

def _ll2tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    """GCJ-02 经纬度 → 瓦片 (tx, ty)."""
    n = 2 ** z
    tx = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    ty = int((1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n)
    return tx, ty


def _tile2ll_topleft(tx: int, ty: int, z: int) -> tuple[float, float]:
    """瓦片左上角 GCJ-02 经纬度."""
    n = 2 ** z
    lon = tx / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    return lon, lat


def _pixel_to_gcj02(px: float, py: float, tx0: int, ty0: int, z: int) -> tuple[float, float]:
    """马赛克内像素坐标 → GCJ-02 (lat, lon)."""
    n = 2 ** z
    tile_x = tx0 + px / 256
    tile_y = ty0 + py / 256
    lon = tile_x / n * 360 - 180
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * tile_y / n))))
    return lat, lon


# ── 瓦片下载 ─────────────────────────────────────────────────────────────────

_HDRS = {"User-Agent": "Mozilla/5.0 (compatible; AutoLabel/1.0)"}


def _tile_path(tx: int, ty: int, z: int) -> Path:
    return _TILE_CACHE_DIR / f"z{z}" / f"{tx}_{ty}.png"


def _download_tile(tx: int, ty: int, z: int, retry: int = 3) -> Optional[bytes]:
    path = _tile_path(tx, ty, z)
    if path.exists():
        return path.read_bytes()
    n = (tx + ty) % len(_GAODE_SERVERS) + 1
    url = _GAODE_URL.format(n=n, x=tx, y=ty, z=z)
    for attempt in range(retry):
        try:
            req = urllib.request.Request(url, headers=_HDRS)
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                data = resp.read()
            if len(data) < 200:
                log.debug("tile %d/%d/%d empty (%d bytes)", z, ty, tx, len(data))
                return None
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return data
        except Exception as exc:
            if attempt < retry - 1:
                time.sleep(0.5 * (attempt + 1))
            else:
                log.warning("tile %d/%d/%d download failed: %s", z, ty, tx, exc)
    return None


# ── 建筑分割 ─────────────────────────────────────────────────────────────────

def _segment_buildings(mosaic_rgb: np.ndarray) -> np.ndarray:
    """从 RGB 马赛克提取建筑掩码 (uint8, 255=building)."""
    import cv2
    hsv = cv2.cvtColor(mosaic_rgb, cv2.COLOR_RGB2HSV)
    s = hsv[:, :, 1].astype(np.int16)
    v = hsv[:, :, 2].astype(np.int16)
    mask = (
        (s >= _BLD_S_MIN) & (s <= _BLD_S_MAX) &
        (v >= _BLD_V_MIN) & (v <= _BLD_V_MAX)
    ).astype(np.uint8) * 255

    # 形态学: 先腐蚀去细线 (地图边框), 再膨胀补洞
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    kernel2 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel2, iterations=2)
    return mask


def _extract_contours(mask: np.ndarray) -> list[np.ndarray]:
    """提取外轮廓并做多边形近似."""
    import cv2
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    result = []
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < _MIN_AREA_PX:
            continue
        # 多边形近似减少点数
        peri = cv2.arcLength(cnt, True)
        approx = cv2.approxPolyDP(cnt, _CONTOUR_EPSILON * peri / 100, True)
        if len(approx) >= 3:
            result.append(approx.reshape(-1, 2))  # shape (N, 2) = (px, py)
    return result


# ── 主接口 ────────────────────────────────────────────────────────────────────

_BUILDINGS_CACHE: dict[str, list[dict]] = {}
_CACHE_MTIME: dict[str, float] = {}
_CACHE_TTL = 3600  # 1 小时重新下载


def fetch_gaode_buildings(
    lat_min: float, lon_min: float, lat_max: float, lon_max: float,
    zoom: int = _TILE_ZOOM,
    cache_dir: Optional[Path] = None,
) -> list[dict]:
    """返回 bbox 内从高德街道瓦片提取的建筑多边形列表.

    Parameters
    ----------
    lat_min, lon_min, lat_max, lon_max : float
        WGS-84 边界框.
    zoom : int
        瓦片缩放级别 (默认 17 ≈ 300m/tile).
    cache_dir : Path | None
        瓦片缓存目录 (None → temp/tile_cache).

    Returns
    -------
    list[dict]  每个 dict 有 "id", "polygon" [(lat, lon), ...], "source" 字段.
    """
    import cv2
    from PIL import Image

    global _TILE_CACHE_DIR
    if cache_dir is not None:
        _TILE_CACHE_DIR = Path(cache_dir)

    # 缓存键
    cache_key = f"{lat_min:.4f},{lon_min:.4f},{lat_max:.4f},{lon_max:.4f},{zoom}"
    now = time.time()
    if cache_key in _BUILDINGS_CACHE:
        if now - _CACHE_MTIME.get(cache_key, 0) < _CACHE_TTL:
            return _BUILDINGS_CACHE[cache_key]

    # WGS-84 → GCJ-02 (高德坐标系)
    gcj_lat_min, gcj_lon_min = _wgs84_to_gcj02(lat_min, lon_min)
    gcj_lat_max, gcj_lon_max = _wgs84_to_gcj02(lat_max, lon_max)

    # 确定覆盖瓦片范围
    tx_min, ty_max = _ll2tile(gcj_lon_min, gcj_lat_min, zoom)
    tx_max, ty_min = _ll2tile(gcj_lon_max, gcj_lat_max, zoom)
    # 各方向外扩 1 tile 保证覆盖
    tx_min -= 1; ty_min -= 1; tx_max += 1; ty_max += 1

    n_tiles_x = tx_max - tx_min + 1
    n_tiles_y = ty_max - ty_min + 1
    log.debug("downloading %d×%d tiles at z%d", n_tiles_x, n_tiles_y, zoom)

    # 下载并拼合马赛克
    W, H = n_tiles_x * 256, n_tiles_y * 256
    mosaic = np.full((H, W, 3), 252, dtype=np.uint8)  # 背景米白

    for dy in range(n_tiles_y):
        for dx in range(n_tiles_x):
            tx = tx_min + dx
            ty = ty_min + dy
            data = _download_tile(tx, ty, zoom)
            if data is None:
                continue
            try:
                tile = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
                mosaic[dy * 256:(dy + 1) * 256, dx * 256:(dx + 1) * 256] = tile
            except Exception as exc:
                log.debug("tile parse error %d/%d/%d: %s", zoom, ty, tx, exc)

    # 建筑分割
    mask = _segment_buildings(mosaic)

    # 提取轮廓
    contours = _extract_contours(mask)
    log.debug("extracted %d building contours", len(contours))

    # 像素 → WGS-84 多边形
    buildings: list[dict] = []
    for i, cnt in enumerate(contours):
        poly = []
        for pt in cnt:
            px, py = float(pt[0]), float(pt[1])
            gcj_lat, gcj_lon = _pixel_to_gcj02(px, py, tx_min, ty_min, zoom)
            wgs_lat, wgs_lon = _gcj02_to_wgs84(gcj_lat, gcj_lon)
            poly.append((wgs_lat, wgs_lon))
        # 滤掉 bbox 之外的轮廓
        lats = [p[0] for p in poly]
        lons = [p[1] for p in poly]
        if max(lats) < lat_min or min(lats) > lat_max:
            continue
        if max(lons) < lon_min or min(lons) > lon_max:
            continue
        buildings.append({
            "id": f"gaode_tile_{zoom}_{i}",
            "polygon": poly,
            "source": "gaode_tile",
        })

    log.info("gaode_tile buildings for bbox: %d polygons (tiles: %d×%d)",
             len(buildings), n_tiles_x, n_tiles_y)

    _BUILDINGS_CACHE[cache_key] = buildings
    _CACHE_MTIME[cache_key] = now
    return buildings


def visualize_buildings(
    lat_min: float, lon_min: float, lat_max: float, lon_max: float,
    out_path: str = "temp/gaode_building_result.png",
    zoom: int = _TILE_ZOOM,
) -> None:
    """调试用: 可视化提取的建筑轮廓叠加到原始瓦片上."""
    import cv2
    from PIL import Image, ImageDraw

    # 先触发提取 (会缓存)
    buildings = fetch_gaode_buildings(lat_min, lon_min, lat_max, lon_max, zoom)

    # 重建马赛克 (已缓存, 速度快)
    gcj_lat_min, gcj_lon_min = _wgs84_to_gcj02(lat_min, lon_min)
    gcj_lat_max, gcj_lon_max = _wgs84_to_gcj02(lat_max, lon_max)
    tx_min, ty_max = _ll2tile(gcj_lon_min, gcj_lat_min, zoom)
    tx_max, ty_min = _ll2tile(gcj_lon_max, gcj_lat_max, zoom)
    tx_min -= 1; ty_min -= 1; tx_max += 1; ty_max += 1
    n_tiles_x = tx_max - tx_min + 1
    n_tiles_y = ty_max - ty_min + 1
    W, H = n_tiles_x * 256, n_tiles_y * 256
    mosaic = np.full((H, W, 3), 252, dtype=np.uint8)
    for dy in range(n_tiles_y):
        for dx in range(n_tiles_x):
            data = _download_tile(tx_min + dx, ty_min + dy, zoom)
            if data:
                try:
                    tile = np.array(Image.open(io.BytesIO(data)).convert("RGB"))
                    mosaic[dy*256:(dy+1)*256, dx*256:(dx+1)*256] = tile
                except Exception:
                    pass

    vis = Image.fromarray(mosaic)
    draw = ImageDraw.Draw(vis)
    for bld in buildings:
        pts_gcj = [_wgs84_to_gcj02(lat, lon) for lat, lon in bld["polygon"]]
        pixels = []
        for glat, glon in pts_gcj:
            n2 = 2 ** zoom
            px = (glon + 180) / 360 * n2 * 256 - tx_min * 256
            lat_r = math.radians(glat)
            py = (1 - math.log(math.tan(lat_r) + 1 / math.cos(lat_r)) / math.pi) / 2 * n2 * 256 - ty_min * 256
            pixels.append((px, py))
        if len(pixels) >= 3:
            draw.polygon(pixels, outline=(255, 0, 0), width=2)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    vis.save(out_path)
    log.info("saved visualization to %s (%d buildings)", out_path, len(buildings))


# ── CLI 测试入口 ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.DEBUG)
    p = argparse.ArgumentParser()
    p.add_argument("--bbox", nargs=4, type=float, default=[31.99, 118.59, 32.00, 118.61],
                   metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"))
    p.add_argument("--vis", default="temp/gaode_building_result.png")
    p.add_argument("--zoom", type=int, default=17)
    a = p.parse_args()
    lat_min, lon_min, lat_max, lon_max = a.bbox
    blds = fetch_gaode_buildings(lat_min, lon_min, lat_max, lon_max, zoom=a.zoom)
    print(f"found {len(blds)} buildings")
    for b in blds[:5]:
        print(f"  {b['id']}: {len(b['polygon'])} points")
    visualize_buildings(lat_min, lon_min, lat_max, lon_max, a.vis, a.zoom)
    print(f"visualization saved to {a.vis}")
