"""
validate_anchor_timing.py  ---  anchor 时序精度三重验证

原理分析：
  anchor 方法的误差主要来自两个环节：
    A. nav100 的 GPS→rel_time 映射精度（每个W12锚点的绝对误差）
    B. 锚点间线性插值的合法性（同一GPS秒内包速率是否恒定）

  本脚本的三项检验：
  [1] nav100 大步长留一验证（用每段nav100每隔10行做一次跳步插值）
      跳过5行 → 跨越~100ms GPS间隔的插值，直接量化 nav100 插值误差。
      由于 nav100 rel_time 有抖动（OS调度），这是anchor方法误差的主要来源。
      MAE < 5ms 正常；5~20ms 可接受（10fps相机帧间距100ms）；>20ms 需注意。

  [2] nav100 时钟斜率（每段线性回归 rel_time = a*gps + b）
      斜率 a 偏离 1.0 → GPS时钟与 ROS时钟有漂移 → 积累误差。
      max_dev < 0.001 → 1s 积累误差 < 1ms。

  [3] nav100 快速抖动分析（相邻行rel_time增量分布）
      直接显示 nav100 发布时间戳的抖动，帮助理解误差来源。
      理想情况：每行增量 ≈ 10ms（100Hz），实际若分布不均则说明 OS 抖动大。

用法：
    python validate_anchor_timing.py
    python validate_anchor_timing.py --cap <cap_dir>
"""

from __future__ import annotations
import argparse, csv
from pathlib import Path

import numpy as np

L_ROOT    = Path("L:/LH_data_all_sensor")
ANCHOR_CSV_NAME = "match_radar_camera_anchor.csv"


def _load_seg_nav(nav_csv: Path):
    gps_list, rel_list = [], []
    with open(nav_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                g = (int(row["gps_hour"])    * 3600
                     + int(row["gps_minute"]) * 60
                     + int(row["gps_second"])
                     + int(row["gps_millisecond"]) / 1000.0
                     + 28800.0)
                r = float(row["relative_time_sec"])
                gps_list.append(g); rel_list.append(r)
            except (KeyError, ValueError):
                pass
    if len(gps_list) < 20:
        return None
    g = np.array(gps_list, np.float64); r = np.array(rel_list, np.float64)
    o = np.argsort(g)
    return g[o], r[o]


def _iter_nav_segs(cap_dir: Path):
    for pdir in sorted(cap_dir.iterdir()):
        if not pdir.is_dir() or "_part" not in pdir.name:
            continue
        for seg in sorted(pdir.iterdir()):
            if not seg.is_dir() or not seg.name.startswith("segment_"):
                continue
            nav_csv = seg / "nav100_state" / "nav100__state" / "nav100__state.csv"
            if not nav_csv.exists():
                continue
            data = _load_seg_nav(nav_csv)
            if data is not None:
                yield data


# ── [1] nav100 大步长留一验证 ─────────────────────────────────────────────────

def check_nav100_holdout(cap_dir: Path, step: int = 5) -> dict:
    """
    每隔 step 行抽取一个"测试行"，用其两侧 step 步之外的邻居线性插值预测它，
    量化 nav100 在 ~100ms GPS 跨度上的插值误差（anchor 方法的主要误差来源）。
    """
    all_err = []
    for g_arr, r_arr in _iter_nav_segs(cap_dir):
        n = len(g_arr)
        if n < 3 * step:
            continue
        idxs = np.arange(step, n - step, step)
        g_l = g_arr[idxs - step]; r_l = r_arr[idxs - step]
        g_r = g_arr[idxs + step]; r_r = r_arr[idxs + step]
        g_m = g_arr[idxs];        r_m = r_arr[idxs]
        spans = g_r - g_l
        ok = spans > 1e-9
        frac = np.where(ok, (g_m[ok] - g_l[ok]) / spans[ok], 0.5)
        pred  = r_l[ok] + frac * (r_r[ok] - r_l[ok])
        all_err.extend(((pred - r_m[ok]) * 1000).tolist())

    if len(all_err) < 10:
        return {}
    e = np.abs(np.array(all_err))
    return {
        "n"         : len(e),
        "mae_ms"    : float(e.mean()),
        "p50_ms"    : float(np.percentile(e, 50)),
        "p95_ms"    : float(np.percentile(e, 95)),
        "max_ms"    : float(e.max()),
    }


# ── [2] nav100 时钟斜率 ───────────────────────────────────────────────────────

def check_nav100_slope(cap_dir: Path) -> dict:
    slopes = []
    for g_arr, r_arr in _iter_nav_segs(cap_dir):
        g_c = g_arr - g_arr.mean()
        d = float(np.sum(g_c ** 2))
        if d < 1e-9: continue
        slopes.append(float(np.sum(g_c * r_arr) / d))
    if not slopes:
        return {}
    s = np.array(slopes)
    devs = np.abs(s - 1.0)
    return {
        "n_segs"  : len(s),
        "mean"    : float(s.mean()),
        "max_dev" : float(devs.max()),
        "err_ms"  : float(devs.max() * 1000),
    }


# ── [3] nav100 抖动分析 ───────────────────────────────────────────────────────

def check_nav100_jitter(cap_dir: Path) -> dict:
    """相邻行的 rel_time 增量分布，揭示 OS 抖动。"""
    all_dt = []
    for g_arr, r_arr in _iter_nav_segs(cap_dir):
        dt = np.diff(r_arr) * 1000  # ms
        all_dt.extend(dt[(dt > 0) & (dt < 500)].tolist())  # 过滤明显异常
    if len(all_dt) < 10:
        return {}
    d = np.array(all_dt)
    return {
        "n"       : len(d),
        "mean_ms" : float(d.mean()),
        "std_ms"  : float(d.std()),
        "p5_ms"   : float(np.percentile(d, 5)),
        "p95_ms"  : float(np.percentile(d, 95)),
        "max_ms"  : float(d.max()),
    }


# ── 输出 ─────────────────────────────────────────────────────────────────────

def validate_capture(cap_dir: Path) -> None:
    r1 = check_nav100_holdout(cap_dir)
    r2 = check_nav100_slope(cap_dir)
    r3 = check_nav100_jitter(cap_dir)

    label = f"{cap_dir.parent.name}/{cap_dir.name}"[-65:]
    print(f"\n{'─'*75}")
    print(f"  {label}")
    print(f"{'─'*75}")

    if r1:
        m = r1["mae_ms"]
        flag = "OK" if m < 5 else ("!" if m < 20 else "ERR")
        print(f"  [1] nav100插值精度(5步跳=~100ms跨度): n={r1['n']}, "
              f"MAE={m:.2f}ms, p50={r1['p50_ms']:.2f}ms, "
              f"p95={r1['p95_ms']:.2f}ms, max={r1['max_ms']:.1f}ms  [{flag}]")
        print(f"      → anchor每W12锚点时序误差估计: ±{r1['p95_ms']:.1f}ms(p95)")
    else:
        print("  [1] nav100插值精度: 无数据")

    if r2:
        d = r2["max_dev"]
        flag = "OK" if d < 0.001 else ("!" if d < 0.005 else "ERR")
        print(f"  [2] nav100时钟斜率: {r2['n_segs']}段, "
              f"mean_slope={r2['mean']:.7f}, "
              f"max_dev={r2['max_dev']:.6f}, "
              f"每秒积累误差<{r2['err_ms']:.2f}ms  [{flag}]")
    else:
        print("  [2] nav100时钟斜率: 无数据")

    if r3:
        d = r3["std_ms"]
        flag = "OK" if d < 5 else ("!" if d < 20 else "ERR")
        print(f"  [3] nav100发布抖动: mean={r3['mean_ms']:.2f}ms, "
              f"std={r3['std_ms']:.2f}ms, "
              f"p5={r3['p5_ms']:.2f}ms, p95={r3['p95_ms']:.2f}ms, "
              f"max={r3['max_ms']:.1f}ms  [{flag}]")
    else:
        print("  [3] nav100发布抖动: 无数据")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap",  type=Path, default=None)
    ap.add_argument("--root", type=Path, default=L_ROOT)
    args = ap.parse_args()

    cap_dirs = ([args.cap] if args.cap else
                sorted({p.parent for p in args.root.rglob(ANCHOR_CSV_NAME)}))
    print(f"共 {len(cap_dirs)} 个 capture 目录\n")

    for cap_dir in cap_dirs:
        try:
            validate_capture(cap_dir)
        except Exception as e:
            import traceback
            print(f"  [错误] {cap_dir.name}: {e}")
            traceback.print_exc()

    print(f"\n{'─'*75}")
    print("  [OK]=正常  [!]=可接受  [ERR]=需注意")
    print("  [1] anchor时序精度: MAE<5ms优秀 / 5~20ms可接受(10fps相机帧间100ms) / >20ms需审查")
    print("  [2] 斜率偏差: max_dev<0.001 优秀 / <0.005 可接受")
    print("  [3] nav100发布抖动: std<5ms优秀(OS调度正常) / >20ms说明nav100时间戳可靠性差")


if __name__ == "__main__":
    main()