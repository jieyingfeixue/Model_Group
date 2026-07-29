"""端到端验证：mat -> 点云 -> OSM 语义标注 -> BEV 可视化.

用法
----
    python test_semantic_labeling.py <mat_file_or_csv_frame_id>
        --seg-dir <segment_dir>
        --mmw-dir <mmwave_mat_dir>
        [--cache-dir temp/osm_cache]
        [--save out.png] [--show]

示例
----
    # 直接指定 mat
    python test_semantic_labeling.py \
        <path>/AntFrame12_FZ123-456.mat \
        --seg-dir D:\\Dataset\\LH_2026-04-27\\bag1.1\\segment_000_... \
        --mmw-dir D:\\Dataset\\LH_2026-04-27\\mmwave_mat_1218style \
        --show

    # 按图像 frame stem 通过 CSV 查 mat
    python test_semantic_labeling.py \
        hikrobot_camera__DA8679038__image_raw_t12345.123456 \
        --seg-dir <seg_dir> --mmw-dir <mmw_dir> --show
"""
from __future__ import annotations
import argparse, sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from mmwave_cfar_standalone import load_mmwave_layers, mmwave_pointcloud_from_mat
from mmwave_time_align_standalone import pick_mat_for_frame
from osm_semantic_fetcher import fetch, bbox_from_segment
from point_semantic_labeler import (label_points, summarize, OsmLabelConfig,
                                     CLASS_BG, CLASS_BUILDING, CLASS_TOWER, CLASS_WIND)


def get_mat_ref_gps(mat_path: Path):
    """从 mat 抽取参考束 (ts 最小) 的 (lat0, lon0, hdg0)。"""
    layers = load_mmwave_layers(mat_path)
    if not layers: return None
    all_ts = np.concatenate([L["pose"][:, 6] for L in layers])
    all_lat = np.concatenate([L["pose"][:, 2] for L in layers])
    all_lon = np.concatenate([L["pose"][:, 3] for L in layers])
    all_hdg = np.concatenate([L["pose"][:, 5] for L in layers])
    ref = int(np.argmin(all_ts))
    return float(all_lat[ref]), float(all_lon[ref]), float(all_hdg[ref])


def body_to_enu(pts_body, hdg0_deg):
    """参考束体系 (x_right, y_fwd) -> ENU (E, N)。"""
    h0 = np.deg2rad(hdg0_deg)
    c, s = np.cos(h0), np.sin(h0)
    xr, yr = pts_body[:, 0], pts_body[:, 1]
    E = xr * c + yr * s
    N = -xr * s + yr * c
    out = pts_body.copy()
    out[:, 0] = E; out[:, 1] = N
    return out


def plot_bev(pts_enu, labels, osm_data, ref_latlon, save: Path = None, show=False):
    try:
        import matplotlib.pyplot as plt
        from matplotlib.patches import Polygon as MplPoly
    except ImportError:
        print("[WARN] matplotlib not installed; skipping plot"); return

    from point_semantic_labeler import latlon_to_enu, CLASS_NAMES
    lat0, lon0 = ref_latlon
    fig, ax = plt.subplots(figsize=(10, 10))
    colors = {CLASS_BG: "#888", CLASS_BUILDING: "#e54", CLASS_TOWER: "#39e", CLASS_WIND: "#3c3"}

    # buildings as polygons
    for b in osm_data.get("buildings", []):
        lats = [p[0] for p in b["polygon"]]; lons = [p[1] for p in b["polygon"]]
        pe, pn = latlon_to_enu(lats, lons, lat0, lon0)
        ax.add_patch(MplPoly(list(zip(pe, pn)), facecolor="#fcc", edgecolor="#e54",
                              alpha=0.4, linewidth=0.8))
    # towers/winds as markers
    if osm_data.get("towers"):
        tlats = [t["lat"] for t in osm_data["towers"]]
        tlons = [t["lon"] for t in osm_data["towers"]]
        te, tn = latlon_to_enu(tlats, tlons, lat0, lon0)
        ax.scatter(te, tn, marker="^", s=120, edgecolor="#39e", facecolor="none",
                   linewidths=1.5, label="OSM tower")
    if osm_data.get("winds"):
        wlats = [w["lat"] for w in osm_data["winds"]]
        wlons = [w["lon"] for w in osm_data["winds"]]
        we, wn = latlon_to_enu(wlats, wlons, lat0, lon0)
        ax.scatter(we, wn, marker="*", s=180, edgecolor="#3c3", facecolor="none",
                   linewidths=1.5, label="OSM wind")

    # points by class
    for cls, name in CLASS_NAMES.items():
        m = labels == cls
        if not m.any(): continue
        ax.scatter(pts_enu[m, 0], pts_enu[m, 1], s=4, c=colors[cls],
                   label=f"{name} ({int(m.sum())})", alpha=0.7)

    ax.scatter([0], [0], marker="x", c="k", s=80, label="ref GPS")
    ax.set_xlabel("East (m)"); ax.set_ylabel("North (m)")
    ax.set_aspect("equal"); ax.grid(alpha=0.3)
    ax.set_title(f"Semantic Labeling | ref=({lat0:.5f},{lon0:.5f})")
    ax.legend(loc="best", fontsize=8)
    if save:
        save.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save, dpi=120, bbox_inches="tight")
        print(f"[save] {save}")
    if show: plt.show()
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", help="mat 文件路径 或 图像 frame stem")
    ap.add_argument("--seg-dir", type=Path, required=True)
    ap.add_argument("--mmw-dir", type=Path, required=True)
    ap.add_argument("--cache-dir", type=Path, default=Path("temp/osm_cache"))
    ap.add_argument("--pad", type=float, default=200.0)
    ap.add_argument("--save", type=Path, default=None)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--building-pad", type=float, default=1.0)
    ap.add_argument("--tower-radius", type=float, default=3.0)
    ap.add_argument("--wind-radius", type=float, default=8.0)
    args = ap.parse_args()

    # 解析 mat 路径
    p = Path(args.target)
    if p.suffix.lower() == ".mat" and p.exists():
        mat_path = p
    else:
        mat_path = pick_mat_for_frame(args.target, args.seg_dir, args.mmw_dir)
        if not mat_path or not mat_path.exists():
            print(f"[ERROR] cannot resolve mat for: {args.target}"); return
    print(f"[mat] {mat_path.name}")

    # 1) mat -> 点云 (body frame)
    pts_body, hdg0 = mmwave_pointcloud_from_mat(mat_path)
    print(f"[cfar] {len(pts_body)} pts, hdg0={hdg0:.1f}°")
    if len(pts_body) == 0:
        print("[ERROR] empty pointcloud"); return

    # 2) ref GPS
    gps = get_mat_ref_gps(mat_path)
    if not gps: print("[ERROR] no GPS in mat"); return
    lat0, lon0, _ = gps
    print(f"[ref] lat={lat0:.6f} lon={lon0:.6f}")

    # 3) body -> ENU
    pts_enu = body_to_enu(pts_body, hdg0)

    # 4) OSM
    bbox = bbox_from_segment(args.seg_dir, args.pad)
    if not bbox: print("[ERROR] no nav100__state.csv"); return
    osm = fetch(bbox, cache_dir=args.cache_dir)
    print(f"[osm] buildings={len(osm['buildings'])} towers={len(osm['towers'])} winds={len(osm['winds'])}")

    # 5) 标注
    cfg = OsmLabelConfig(building_pad_m=args.building_pad,
                         tower_radius_m=args.tower_radius,
                         wind_radius_m=args.wind_radius)
    labels = label_points(pts_enu[:, :2], (lat0, lon0), osm, cfg)
    s = summarize(labels)
    print(f"[label] total={s['total']}")
    for k, v in s["counts"].items():
        print(f"  {k:<14}: {v:>5}  ({s['ratios'][k]*100:.1f}%)")

    # 6) 可视化
    if args.save or args.show:
        plot_bev(pts_enu, labels, osm, (lat0, lon0), save=args.save, show=args.show)


if __name__ == "__main__":
    main()
