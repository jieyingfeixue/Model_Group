"""OSM 语义数据获取器.

从 Overpass API 拉取 bbox 范围内的 building 多边形 / power=tower 点 /
wind generator 点，规整成简单 dict 并缓存到本地 JSON。

数据结构:
    {
      "bbox": [s, w, n, e],
      "buildings": [{"id": int, "polygon": [[lat, lon], ...]}, ...],
      "towers":    [{"id": int, "lat": float, "lon": float}, ...],
      "winds":     [{"id": int, "lat": float, "lon": float}, ...]
    }

CLI:
    python osm_semantic_fetcher.py --lat 31.994 --lon 118.601 --radius 500 \
                                   --cache-dir <dir>
    python osm_semantic_fetcher.py --seg-dir <segment_dir> --pad 200 \
                                   --cache-dir <dir>
"""
from __future__ import annotations
import argparse, csv, json, math, time, urllib.request, urllib.error
from pathlib import Path
from typing import Optional

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

def bbox_from_center(lat, lon, radius_m):
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * math.cos(math.radians(lat)))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)

def bbox_from_segment(seg_dir: Path, pad_m: float = 200.0):
    cands = list(seg_dir.glob("nav100_state/**/nav100__state.csv"))
    if not cands: cands = list(seg_dir.glob("**/nav100__state.csv"))
    if not cands: return None
    lats, lons = [], []
    with open(cands[0], newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try: lats.append(float(row["latitude"])); lons.append(float(row["longitude"]))
            except (KeyError, ValueError): continue
    if not lats: return None
    lat0 = sum(lats) / len(lats)
    pad_lat = pad_m / 111320.0
    pad_lon = pad_m / (111320.0 * math.cos(math.radians(lat0)))
    return (min(lats)-pad_lat, min(lons)-pad_lon, max(lats)+pad_lat, max(lons)+pad_lon)

def _cache_key(bbox, precision=4):
    s, w, n, e = bbox
    return f"osm_{s:.{precision}f}_{w:.{precision}f}_{n:.{precision}f}_{e:.{precision}f}.json"

def query_overpass(query: str, timeout: int = 60):
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=("data=" + query).encode("utf-8"),
                                         headers={"User-Agent": "osm-semantic-fetcher/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            print(f"  [warn] {url} failed: {e}; retrying...")
            time.sleep(2)
    raise RuntimeError(f"all Overpass endpoints failed: {last_err}")

def build_query(bbox, timeout=60):
    s, w, n, e = bbox
    # out geom -> ways 携带 geometry，无需再请求 nodes
    return f"""[out:json][timeout:{timeout}];
(
  way["building"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
  node["power"="tower"]({s},{w},{n},{e});
  node["power"="generator"]["generator:source"="wind"]({s},{w},{n},{e});
);
out body geom;"""

def _parse(data):
    buildings, towers, winds = [], [], []
    for el in data.get("elements", []):
        tags = el.get("tags", {})
        etype = el.get("type"); eid = el.get("id")
        if etype == "way" and "building" in tags:
            geom = el.get("geometry") or []
            poly = [(g["lat"], g["lon"]) for g in geom if "lat" in g and "lon" in g]
            if len(poly) >= 3:
                buildings.append({"id": eid, "polygon": poly})
        elif etype == "relation" and "building" in tags:
            # relation 由多个 way 组成，简化为外环（取第一个 outer way）
            for m in el.get("members", []):
                if m.get("role") == "outer" and "geometry" in m:
                    poly = [(g["lat"], g["lon"]) for g in m["geometry"]]
                    if len(poly) >= 3:
                        buildings.append({"id": eid, "polygon": poly}); break
        elif etype == "node":
            lat, lon = el.get("lat"), el.get("lon")
            if lat is None or lon is None: continue
            if tags.get("power") == "tower":
                towers.append({"id": eid, "lat": lat, "lon": lon})
            elif tags.get("power") == "generator" and tags.get("generator:source") == "wind":
                winds.append({"id": eid, "lat": lat, "lon": lon})
    return buildings, towers, winds

def fetch(bbox, cache_dir: Optional[Path] = None, force: bool = False):
    """主接口。返回 dict。若 cache_dir 给定，自动读写缓存。"""
    cache_path = None
    if cache_dir is not None:
        cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / _cache_key(bbox)
        if cache_path.exists() and not force:
            with open(cache_path, encoding="utf-8") as fh:
                return json.load(fh)

    data = query_overpass(build_query(bbox))
    buildings, towers, winds = _parse(data)
    result = {"bbox": list(bbox), "buildings": buildings,
              "towers": towers, "winds": winds}
    if cache_path is not None:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
        print(f"  [cache] saved -> {cache_path}")
    return result

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seg-dir", type=Path)
    g.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--radius", type=float, default=500.0)
    ap.add_argument("--pad", type=float, default=200.0, help="seg-dir 模式下 bbox 外扩 (m)")
    ap.add_argument("--cache-dir", type=Path, default=Path("temp/osm_cache"))
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if args.seg_dir:
        bbox = bbox_from_segment(args.seg_dir, args.pad)
        if not bbox: print("[ERROR] no nav100__state.csv"); return
    else:
        if args.lon is None: print("[ERROR] --lon required"); return
        bbox = bbox_from_center(args.lat, args.lon, args.radius)

    print(f"BBox: {bbox}")
    r = fetch(bbox, cache_dir=args.cache_dir, force=args.force)
    print(f"  buildings : {len(r['buildings'])}")
    print(f"  towers    : {len(r['towers'])}")
    print(f"  winds     : {len(r['winds'])}")

if __name__ == "__main__":
    main()
