"""离线提取 Overture Maps 建筑足迹 (China bbox) → 本地 GeoJSON 缓存.

用法
----
    # 默认: 江苏南京 (含本数据集) 200x200km
    python tools/extract_overture_buildings.py

    # 自定义 bbox (lat_min lon_min lat_max lon_max)
    python tools/extract_overture_buildings.py --bbox 31.0 117.5 33.0 119.5

    # 自定义输出文件
    python tools/extract_overture_buildings.py --out temp/buildings_local/buildings.geojson

数据来源
--------
Overture Maps Foundation 公开数据集 (CC-BY 4.0), 由 Microsoft / Meta /
Amazon / TomTom 等贡献, 覆盖全球包含中国大陆. 通过匿名 S3 访问.

依赖
----
    pip install pyarrow

性能
----
* 扫描全部 ~512 个 parquet 文件的 row-group 统计做空间裁剪
* 100x100 km bbox 约 5–15 分钟 (取决于网络)
* 一次性运行, 结果缓存到 temp/buildings_local/buildings.geojson
* 在 LH 项目运行时 semantic_osm.py 会自动读取该文件作为
  CLASS_BUILDING 数据源补全 (与 OSM 叠加)
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("extract_overture")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bbox", nargs=4, type=float,
                   default=[31.0, 117.5, 33.0, 119.5],
                   metavar=("LAT_MIN", "LON_MIN", "LAT_MAX", "LON_MAX"),
                   help="经纬度边界 (默认覆盖南京周边)")
    p.add_argument("--out", type=Path,
                   default=Path("temp/buildings_local/buildings.geojson"),
                   help="输出 GeoJSON 路径")
    p.add_argument("--release", type=str, default="",
                   help="Overture release tag (默认: 最新)")
    p.add_argument("--max-files", type=int, default=0,
                   help="最多扫描的 parquet 文件数 (0=全部)")
    return p.parse_args()


def _wkb_polygon_rings(wkb: bytes):
    """简易 WKB 解析器: 仅处理 (Multi)Polygon, 返回 [outer_ring_lon_lat, ...].

    WKB layout: byte_order(1) + geom_type(4 uint32, 1=Point/3=Polygon/6=MultiPolygon)
                + ... 见 https://en.wikipedia.org/wiki/Well-known_binary
    """
    import struct
    if not wkb or len(wkb) < 5:
        return []
    bo = "<" if wkb[0] == 1 else ">"
    gtype = struct.unpack(bo + "I", wkb[1:5])[0] & 0xFF
    off = 5
    out = []
    if gtype == 3:  # Polygon
        nrings = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4
        for _ in range(nrings):
            npts = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4
            coords = struct.unpack(bo + f"{2 * npts}d", wkb[off:off + 16 * npts])
            off += 16 * npts
            ring = [(coords[2 * i], coords[2 * i + 1]) for i in range(npts)]
            if out:
                break  # only outer ring
            out.append(ring)
    elif gtype == 6:  # MultiPolygon
        npoly = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4
        for _ in range(npoly):
            off += 5  # skip sub-polygon header
            nrings = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4
            for r in range(nrings):
                npts = struct.unpack(bo + "I", wkb[off:off + 4])[0]; off += 4
                coords = struct.unpack(bo + f"{2 * npts}d", wkb[off:off + 16 * npts])
                off += 16 * npts
                if r == 0:
                    ring = [(coords[2 * i], coords[2 * i + 1]) for i in range(npts)]
                    out.append(ring)
    return out


def main() -> int:
    args = parse_args()
    try:
        import pyarrow.dataset as pads
        import pyarrow.fs as pafs
        import pyarrow.compute as pc
    except ImportError:
        log.error("需要安装 pyarrow: pip install pyarrow")
        return 1

    lat_min, lon_min, lat_max, lon_max = args.bbox
    log.info("bbox: lat[%.4f, %.4f] lon[%.4f, %.4f]", lat_min, lat_max, lon_min, lon_max)

    fs = pafs.S3FileSystem(anonymous=True, region="us-west-2")
    release = args.release
    if not release:
        log.info("listing Overture releases ...")
        infos = fs.get_file_info(pafs.FileSelector("overturemaps-us-west-2/release", recursive=False))
        rels = sorted(i.base_name for i in infos if i.type == pafs.FileType.Directory)
        release = rels[-1]
    log.info("using release: %s", release)

    base = f"overturemaps-us-west-2/release/{release}/theme=buildings/type=building"
    log.info("listing parquet files ...")
    files = fs.get_file_info(pafs.FileSelector(base, recursive=False))
    parquet_files = sorted(f.path for f in files if f.path.endswith(".parquet"))
    log.info("found %d parquet files", len(parquet_files))
    if args.max_files > 0:
        parquet_files = parquet_files[:args.max_files]
        log.info("limited to first %d files", len(parquet_files))

    filt = (
        (pc.field("bbox", "xmin") < lon_max) & (pc.field("bbox", "xmax") > lon_min) &
        (pc.field("bbox", "ymin") < lat_max) & (pc.field("bbox", "ymax") > lat_min)
    )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    features: list = []
    t_start = time.time()
    # 分批扫描以打印进度
    BATCH = 16
    total = len(parquet_files)
    for i in range(0, total, BATCH):
        chunk = parquet_files[i:i + BATCH]
        ds = pads.dataset(chunk, filesystem=fs, format="parquet")
        try:
            tbl = ds.to_table(columns=["id", "geometry", "subtype", "class", "height"], filter=filt)
        except Exception as exc:
            log.warning("batch %d failed: %s", i, exc); continue
        if tbl.num_rows:
            ids = tbl.column("id").to_pylist()
            geoms = tbl.column("geometry").to_pylist()
            heights = tbl.column("height").to_pylist()
            classes = tbl.column("class").to_pylist()
            for fid, wkb, h, cls in zip(ids, geoms, heights, classes):
                rings = _wkb_polygon_rings(wkb if isinstance(wkb, (bytes, bytearray)) else bytes(wkb))
                for ring in rings:
                    features.append({
                        "type": "Feature",
                        "properties": {"id": fid, "height": h, "class": cls},
                        "geometry": {"type": "Polygon", "coordinates": [ring]},
                    })
        elapsed = time.time() - t_start
        log.info("[%4d/%d files] features so far: %d  elapsed: %.0fs",
                 min(i + BATCH, total), total, len(features), elapsed)

    log.info("writing %d features -> %s", len(features), args.out)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh)
    log.info("done in %.0fs", time.time() - t_start)
    return 0


if __name__ == "__main__":
    sys.exit(main())
