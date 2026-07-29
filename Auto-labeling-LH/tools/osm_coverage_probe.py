"""OSM 覆盖率探测脚本.

向 Overpass API 发起 bbox 查询，统计目标 segment 区域内
building / power=tower / wind generator 的数量，判断 OSM 数据是否够用。

CLI:
    python osm_coverage_probe.py --lat 31.994 --lon 118.601 --radius 1000
    python osm_coverage_probe.py --seg-dir <segment_dir>   # 从 nav100 自动取 bbox
"""
from __future__ import annotations
import argparse, csv, json, math, time, urllib.request, urllib.error
from pathlib import Path

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.fr/api/interpreter",
]

def bbox_from_center(lat, lon, radius_m):
    """以 (lat, lon) 为中心、半径 radius_m 米的近似 WGS84 bbox (s,w,n,e)."""
    dlat = radius_m / 111320.0
    dlon = radius_m / (111320.0 * math.cos(math.radians(lat)))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)

def bbox_from_segment(seg_dir: Path):
    """从 segment_dir/nav100_state/.../nav100__state.csv 读取 GPS 轨迹 bbox。"""
    cands = list(seg_dir.glob("nav100_state/**/nav100__state.csv"))
    if not cands:
        cands = list(seg_dir.glob("**/nav100__state.csv"))
    if not cands:
        return None
    lats, lons = [], []
    with open(cands[0], newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            try:
                lats.append(float(row["latitude"])); lons.append(float(row["longitude"]))
            except (KeyError, ValueError):
                continue
    if not lats: return None
    return (min(lats), min(lons), max(lats), max(lons))

def query_overpass(query: str, timeout: int = 60):
    last_err = None
    for url in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(url, data=("data=" + query).encode("utf-8"),
                                         headers={"User-Agent": "osm-coverage-probe/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last_err = e
            print(f"  [warn] {url} failed: {e}; retrying...")
            time.sleep(2)
    raise RuntimeError(f"all Overpass endpoints failed: {last_err}")

def build_query(bbox, timeout=60):
    s, w, n, e = bbox
    return f"""[out:json][timeout:{timeout}];
(
  way["building"]({s},{w},{n},{e});
  relation["building"]({s},{w},{n},{e});
  node["power"="tower"]({s},{w},{n},{e});
  node["power"="pole"]({s},{w},{n},{e});
  node["power"="generator"]["generator:source"="wind"]({s},{w},{n},{e});
);
out tags center;"""

def summarize(elements):
    n_bld = n_tower = n_pole = n_wind = n_other = 0
    sample = {"building": [], "tower": [], "wind": []}
    for el in elements:
        tags = el.get("tags", {})
        if "building" in tags:
            n_bld += 1
            if len(sample["building"]) < 3:
                sample["building"].append(tags.get("building"))
        elif tags.get("power") == "tower":
            n_tower += 1
            if len(sample["tower"]) < 3: sample["tower"].append(tags)
        elif tags.get("power") == "pole":
            n_pole += 1
        elif tags.get("power") == "generator" and tags.get("generator:source") == "wind":
            n_wind += 1
            if len(sample["wind"]) < 3: sample["wind"].append(tags)
        else:
            n_other += 1
    return {"building": n_bld, "power_tower": n_tower, "power_pole": n_pole,
            "wind_turbine": n_wind, "other": n_other, "samples": sample}

def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--seg-dir", type=Path, help="segment 目录，自动从 nav100 取 bbox")
    g.add_argument("--lat", type=float, help="中心纬度")
    ap.add_argument("--lon", type=float, help="中心经度（与 --lat 配合）")
    ap.add_argument("--radius", type=float, default=500.0, help="半径（米），与 --lat/--lon 配合")
    args = ap.parse_args()

    if args.seg_dir:
        bbox = bbox_from_segment(args.seg_dir)
        if not bbox:
            print("[ERROR] nav100__state.csv not found or empty"); return
        print(f"BBox from {args.seg_dir.name}: S={bbox[0]:.5f} W={bbox[1]:.5f} N={bbox[2]:.5f} E={bbox[3]:.5f}")
        # expand by ~200 m so radar range (~150 m) is covered
        pad = 200 / 111320.0
        bbox = (bbox[0]-pad, bbox[1]-pad, bbox[2]+pad, bbox[3]+pad)
    else:
        if args.lon is None:
            print("[ERROR] --lon required with --lat"); return
        bbox = bbox_from_center(args.lat, args.lon, args.radius)
        print(f"BBox (center {args.lat},{args.lon} r={args.radius}m): "
              f"S={bbox[0]:.5f} W={bbox[1]:.5f} N={bbox[2]:.5f} E={bbox[3]:.5f}")

    q = build_query(bbox)
    print("Querying Overpass...")
    t0 = time.time()
    data = query_overpass(q)
    dt = time.time() - t0
    els = data.get("elements", [])
    print(f"Got {len(els)} elements in {dt:.1f}s")

    s = summarize(els)
    print("\n=== Coverage ===")
    print(f"  building     : {s['building']:>5}")
    print(f"  power=tower  : {s['power_tower']:>5}")
    print(f"  power=pole   : {s['power_pole']:>5}")
    print(f"  wind turbine : {s['wind_turbine']:>5}")
    print(f"  other        : {s['other']:>5}")

    print("\n=== Samples ===")
    for k, v in s["samples"].items():
        if v: print(f"  {k}: {v}")

    print("\n=== Verdict ===")
    if s["building"] >= 10:
        print(f"  ✓ Buildings: {s['building']} (sufficient)")
    elif s["building"] >= 3:
        print(f"  ~ Buildings: {s['building']} (sparse, but usable)")
    else:
        print(f"  ✗ Buildings: {s['building']} (very low, OSM coverage poor here)")

    if s["power_tower"] + s["wind_turbine"] == 0:
        print("  - No power towers / wind turbines in this bbox (may be normal for urban scene)")

if __name__ == "__main__":
    main()
