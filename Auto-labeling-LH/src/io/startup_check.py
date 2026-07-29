"""LH 数据集启动检查: bin→mat 转换 + 雷达-相机匹配。

在应用启动时调用 run_startup_check() 以确保:
1. 所有 *_mmwave_udp.bin 均已转换到同级 {bin_stem}_radar/ 文件夹
2. 每个 radar 目录均有最新的 radar_camera_match.json

设计为可无界面运行 (progress_cb=None) 或接受回调 (用于 GUI 进度条)。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path
from typing import Callable

_RADAR_SUFFIX = "_radar"
_TIMETABLE    = "_timetable.json"
_MATCH_JSON   = "radar_camera_match.json"
_MATCH_CSV    = "radar_camera_match_ts.csv"   # per-segment CSV (新格式)
_LOCAL_CACHE_REL = Path("temp") / "radar_match_cache"


def _local_csv_cache_path(seg_dir: Path) -> Path:
    """返回 segment 对应的本地缓存 CSV 路径。"""
    project_root = Path(__file__).resolve().parents[2]
    cache_dir = project_root / _LOCAL_CACHE_REL
    seg_key = hashlib.sha1(str(seg_dir).lower().encode("utf-8")).hexdigest()[:16]
    safe_name = re_sub_non_alnum(seg_dir.name)
    return cache_dir / f"{safe_name}_{seg_key}.csv"


def re_sub_non_alnum(text: str) -> str:
    """将文件名中非常规字符替换为下划线, 便于跨平台缓存命名。"""
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


# ── 检测函数 ─────────────────────────────────────────────────────────────────

def find_all_bins(root: Path) -> list[Path]:
    """递归查找所有 *_mmwave_udp.bin."""
    return sorted(root.rglob("*_mmwave_udp.bin"))


def radar_dir_for(bin_path: Path) -> Path:
    """返回 bin 对应的 radar 文件夹路径 (不检查是否存在)."""
    return bin_path.parent / (bin_path.stem + _RADAR_SUFFIX)


def count_expected_mats(bin_path: Path) -> int:
    """从 timetable.json 读取预期 mat 数量; 若不存在或解析失败返回 -1."""
    import json as _json
    tbl = radar_dir_for(bin_path) / _TIMETABLE
    if not tbl.exists():
        return -1
    try:
        data = _json.loads(tbl.read_text(encoding="utf-8"))
        return len(data)
    except Exception:
        return -1


def count_actual_mats(bin_path: Path) -> int:
    """统计实际已生成的 mat 文件数量."""
    rdir = radar_dir_for(bin_path)
    if not rdir.exists():
        return 0
    return sum(1 for _ in rdir.glob("*.mat"))


def needs_conversion(bin_path: Path) -> bool:
    """判断 bin 是否还未完整转换 (目录不存在、缺 timetable 或 mat 数不足)."""
    rdir = radar_dir_for(bin_path)
    if not rdir.exists():
        return True
    if not (rdir / _TIMETABLE).exists():
        return True
    # 比较 mat 数量与 timetable 期望数量
    expected = count_expected_mats(bin_path)
    actual   = count_actual_mats(bin_path)
    if expected > 0 and actual < expected:
        return True
    return actual == 0


def needs_matching(bin_path: Path) -> bool:
    """判断 bin 对应的 capture 是否缺少雷达-相机匹配数据 (旧格式 JSON).

    满足以下任一条件则视为已匹配：
    1. radar 目录下存在 radar_camera_match.json（旧格式）
    2. capture 目录下至少一个 segment_* 目录存在 radar_camera_match_ts.csv（新格式）
    """
    rdir = radar_dir_for(bin_path)
    if not rdir.exists():
        return False   # 还没有 radar 目录, 等转换完再说

    # 旧格式 JSON
    if (rdir / _MATCH_JSON).exists():
        return False

    # 新格式 CSV: 扫描 capture 下所有 segment_* 子目录
    cap_dir = bin_path.parent
    for seg in cap_dir.rglob("segment_*"):
        if seg.is_dir() and (seg / _MATCH_CSV).exists():
            return False
        if seg.is_dir() and _local_csv_cache_path(seg).exists():
            return False

    return True


def needs_csv_match(bin_path: Path) -> bool:
    """判断 bin 对应 capture 下是否有 segment 缺少 radar_camera_match_ts.csv.

    框架 (lh_adapter.list_frames) 依赖该 CSV; 仅有 JSON 无法点亮帧列表.
    需要 radar 目录已存在且含 mat (由 needs_conversion 完成).
    """
    rdir = radar_dir_for(bin_path)
    if not rdir.exists():
        return False
    if not any(rdir.glob("*.mat")):
        return False
    cap_dir = bin_path.parent
    has_segment = False
    for seg in cap_dir.rglob("segment_*"):
        if not seg.is_dir():
            continue
        has_segment = True
        if not (seg / _MATCH_CSV).exists() and not _local_csv_cache_path(seg).exists():
            return True
    return False   # 无 segment 或所有 segment 均有 CSV


def needs_depth_labels(cap_dir: Path, annot_root: "Path | None" = None) -> bool:
    """判断 capture 是否需要生成 depth_labels。

    仅当 radar 目录存在 mat 且 depth_labels/ 目录不存在或为空时才需要生成。
    若提供 annot_root，还检查已有 JSON 是否为 cluster-only 格式（boxes 为空），
    若是则也返回 True（需要重新生成带标注匹配的深度标注）。
    """
    # 寻找 mat 目录
    mat_found = False
    for d in cap_dir.iterdir():
        if not d.is_dir():
            continue
        if d.name.endswith("_radar") or d.name == "mmwave_mat_1218style":
            if any(d.glob("*.mat")):
                mat_found = True
                break
    if not mat_found:
        return False
    depth_dir = cap_dir / "depth_labels"
    if not depth_dir.exists() or not any(depth_dir.glob("*.json")):
        return True
    # 若提供 annot_root，检查首个 JSON 是否为 cluster-only（boxes 为空）
    if annot_root is not None and annot_root.exists():
        import json as _json
        sample = next(depth_dir.glob("*.json"), None)
        if sample is not None:
            try:
                data = _json.loads(sample.read_text(encoding="utf-8"))
                if not data.get("boxes"):   # cluster-only → 需要重新生成
                    return True
            except Exception:
                pass
    return False


def needs_target_db(cap_dir: Path) -> bool:
    """判断 capture 是否需要（重新）构建 GPS 目标深度数据库。

    当 depth_labels/ 有 JSON 且 target_depth_db.json 不存在或比 depth_labels 旧时返回 True。
    """
    depth_dir = cap_dir / "depth_labels"
    if not depth_dir.exists() or not any(depth_dir.glob("*.json")):
        return False  # 还没有雷达种子数据
    db_path = cap_dir / "target_depth_db.json"
    if not db_path.exists():
        return True
    # 若 depth_labels 中有比 db 更新的 JSON → 需要重建
    try:
        db_mtime = db_path.stat().st_mtime
        return any(j.stat().st_mtime > db_mtime
                   for j in depth_dir.glob("*.json"))
    except Exception:
        return True


def needs_depth_from_db(cap_dir: Path) -> bool:
    """判断 capture 是否需要用 GPS 数据库补全/更新深度标注。

    当 target_depth_db.json 存在，且 depth_labels/.db_applied 不存在
    或比 target_depth_db.json 旧时返回 True。
    """
    db_path = cap_dir / "target_depth_db.json"
    if not db_path.exists():
        return False
    marker = cap_dir / "depth_labels" / ".db_applied"
    if not marker.exists():
        return True
    try:
        if int(marker.read_text(encoding="ascii").strip() or "0") < 2:
            return True
        return db_path.stat().st_mtime > marker.stat().st_mtime
    except (OSError, ValueError):
        return True
    """判断 capture 是否需要生成 W12 锚点匹配 CSV。

    当 radar 目录已有 mat 文件，且 capture 根目录下不存在
    match_radar_camera_anchor.csv 时返回 True。
    """
    rdir = radar_dir_for(bin_path)
    if not rdir.exists() or not any(rdir.glob("*.mat")):
        return False  # mat 还未生成，等转换后再做
    cap_dir = bin_path.parent
    return not (cap_dir / "match_radar_camera_anchor.csv").exists()


def needs_mat_camera_csv(bin_path: Path) -> bool:
    """判断 capture 是否需要生成 mat→camera CSV（依赖 W12 锚点 CSV 存在）。"""
    cap_dir = bin_path.parent
    if not (cap_dir / "match_radar_camera_anchor.csv").exists():
        return False  # 锚点 CSV 尚未生成
    return not (cap_dir / "match_mat_camera.csv").exists()


def anchor_to_seg_csvs(cap_dir: Path) -> int:
    """将 match_mat_camera.csv 转换为各 segment 下的 radar_camera_match_ts.csv。

    读取 {cap_dir}/match_mat_camera.csv（列：mat_name, camera_name, ...），
    遍历 cap_dir 下所有 part_*/segment_* 目录，为每个 segment 中的相机帧
    建立 camera_filename→mat_filename 映射，写入各 segment 的 _MATCH_CSV。

    返回所有 segment 合计写入的行数。
    """
    import csv as _csv_mod

    _CAM_SUBDIR = "hikrobot_camera__DA8679037__image_raw"
    anchor_csv = cap_dir / "match_mat_camera.csv"
    if not anchor_csv.exists():
        return 0

    # 构建 camera_filename → mat_name 查找表
    cam_to_mat: dict[str, str] = {}
    with open(anchor_csv, newline='', encoding='utf-8') as fh:
        for row in _csv_mod.DictReader(fh):
            cam = row.get('camera_name', '').strip()
            mat = row.get('mat_name', '').strip()
            if cam and mat:
                cam_to_mat[cam] = mat

    if not cam_to_mat:
        return 0

    total_rows = 0
    for part_dir in sorted(cap_dir.iterdir()):
        if not part_dir.is_dir() or '_part' not in part_dir.name:
            continue
        for seg_dir in sorted(part_dir.iterdir()):
            if not seg_dir.is_dir() or not seg_dir.name.startswith('segment_'):
                continue
            cam_dir = seg_dir / 'images' / _CAM_SUBDIR
            if not cam_dir.exists():
                continue
            cam_images = sorted(cam_dir.glob('*.jpg'))
            if not cam_images:
                continue
            rows = []
            for img in cam_images:
                mat_name = cam_to_mat.get(img.name)
                if mat_name:
                    rows.append({'camera_filename': img.name,
                                 'mat_filename': mat_name})
            if rows:
                out_csv = seg_dir / _MATCH_CSV
                with open(out_csv, 'w', newline='', encoding='utf-8') as fh:
                    writer = _csv_mod.DictWriter(
                        fh, fieldnames=['camera_filename', 'mat_filename'])
                    writer.writeheader()
                    writer.writerows(rows)
                total_rows += len(rows)

    return total_rows


# ── 执行函数 ─────────────────────────────────────────────────────────────────

def run_startup_check(
    root: Path,
    progress_cb: Callable[[str], None] | None = None,
    step_cb: "Callable[[int, int], None] | None" = None,
) -> None:
    """检查并按需执行 bin→mat 转换 + 匹配 JSON 生成.

    Parameters
    ----------
    root:        数据集根目录
    progress_cb: 可选回调, 接受一个状态字符串 (用于 GUI 日志)
    step_cb:     可选回调 ``(current, total)`` 用于确定性进度条更新
    """
    def _log(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)
        else:
            print(msg, flush=True)

    if not root.exists():
        _log(f"[跳过] 数据集根目录不存在: {root}")
        return

    bins = find_all_bins(root)
    if not bins:
        _log("[跳过] 未找到任何 *_mmwave_udp.bin")
        return

    # ── 提前读取 annotation 根目录（供 depth 生成使用）─────────────────────
    _annot_root_for_depth: "Path | None" = None
    _autofill_root_for_depth: "Path | None" = None
    try:
        from src.core.config import load_config as _lc_pre
        _cfg_pre = _lc_pre()
        _ann_cfg = _cfg_pre.get("annotations", {})
        _ar_pre = _ann_cfg.get("labelme_root", "")
        if _ar_pre:
            _p = Path(_ar_pre)
            if _p.exists():
                _annot_root_for_depth = _p
        _af_pre = _ann_cfg.get("autofill_root", "")
        if _af_pre:
            _pf = Path(_af_pre)
            if _pf.exists():
                _autofill_root_for_depth = _pf
    except Exception:
        pass

    # ── Step 1: bin → mat 转换 ─────────────────────────────────────────────
    pending_conv   = [b for b in bins if needs_conversion(b)]
    pending_csv    = [b for b in bins if needs_csv_match(b)]
    pending_anchor = [b for b in bins if needs_anchor_match(b)]
    pending_matcam = [b for b in bins if needs_mat_camera_csv(b)]
    # 收集需要处理的 capture 目录（去重）
    _seen_cap: set[Path] = set()
    pending_depth_caps:  list[Path] = []
    pending_target_db:   list[Path] = []
    pending_db_apply:    list[Path] = []
    for b in bins:
        cap = b.parent
        if cap not in _seen_cap:
            _seen_cap.add(cap)
            if needs_depth_labels(cap, _annot_root_for_depth):
                pending_depth_caps.append(cap)
            if needs_target_db(cap):
                pending_target_db.append(cap)
            if needs_depth_from_db(cap):
                pending_db_apply.append(cap)
    # 计算总操作步数 (用于进度条)
    total_steps = (
        len(pending_conv)
        + len([b for b in bins if needs_matching(b)])
        + len(pending_anchor)
        + len(pending_matcam)
        + len(pending_csv)
        + len(pending_depth_caps)
        + len(pending_target_db)
        + len(pending_db_apply)
    )
    step_done = 0
    if step_cb and total_steps > 0:
        step_cb(0, total_steps)

    if pending_conv:
        # 展示各 bin 的缺 mat 详情
        for bp in pending_conv:
            expected = count_expected_mats(bp)
            actual   = count_actual_mats(bp)
            if expected < 0:
                _log(f"  · {bp.name}: 尚未生成 (无 timetable)")
            else:
                _log(f"  · {bp.name}: 已有 {actual}/{expected} 个 mat")
        _log(f"[转换] 发现 {len(pending_conv)} 个 bin 需要转换 mat ...")
        try:
            # 懒导入, 避免在没有 scipy/numpy 时阻断启动
            from tools.tools.batch_convert_bins import convert_bin
        except ImportError:
            # 尝试直接路径导入
            import importlib.util, os
            _here = Path(__file__).parent.parent.parent / "tools" / "tools" / "batch_convert_bins.py"
            spec = importlib.util.spec_from_file_location("batch_convert_bins", _here)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            convert_bin = mod.convert_bin

        for i, bin_path in enumerate(pending_conv, 1):
            rdir = radar_dir_for(bin_path)
            rdir.mkdir(parents=True, exist_ok=True)
            _log(f"  [{i}/{len(pending_conv)}] 转换: {bin_path.name} → {rdir.name}/")

            # 用 list 存储以便 closure 修改
            _mat_progress: list[int] = [0, 0]

            def _cb(done: int, total: int, mat_name: str,
                    _bp=bin_path, _p=_mat_progress) -> None:
                _p[0], _p[1] = done, total
                _log(f"    {done}/{total} {mat_name}")
                if step_cb and total > 0:
                    # 当前 bin 内进度 + 前面已完成的 bin 数
                    frac_done = step_done + (done / total)
                    step_cb(int(frac_done), total_steps)

            try:
                convert_bin(bin_path, rdir, progress_cb=_cb)
            except Exception as exc:
                _log(f"  [错误] {bin_path.name}: {exc}")

            step_done += 1
            if step_cb:
                step_cb(step_done, total_steps)
    else:
        _log("[转换] 所有 bin 均已转换 ✓")

    # ── Step 2: 雷达-相机匹配 ──────────────────────────────────────────────
    pending_match = [b for b in bins if needs_matching(b)]
    if pending_match:
        _log(f"[匹配] 发现 {len(pending_match)} 个 capture 需要生成匹配 JSON ...")
        try:
            from tools.tools.match_radar_camera import process_capture
        except ImportError:
            import importlib.util
            _here = Path(__file__).parent.parent.parent / "tools" / "tools" / "match_radar_camera.py"
            spec = importlib.util.spec_from_file_location("match_radar_camera", _here)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            process_capture = mod.process_capture

        done_caps: set[Path] = set()
        for i, bin_path in enumerate(pending_match, 1):
            cap_dir = bin_path.parent
            if cap_dir in done_caps:
                continue
            done_caps.add(cap_dir)
            _log(f"  [{i}/{len(pending_match)}] 匹配: {cap_dir.name}")

            try:
                process_capture(cap_dir, root,
                                overwrite=False, verbose=False)
                _log(f"    → {_MATCH_JSON} 已写出")
            except Exception as exc:
                _log(f"  [错误] {cap_dir.name}: {exc}")

            step_done += 1
            if step_cb:
                step_cb(step_done, total_steps)
    else:
        _log("[匹配] 所有 capture 均已有匹配 JSON ✓")

    # ── Step 2b: W12 锚点匹配 CSV ─────────────────────────────────────────
    if pending_anchor:
        _log(f"[W12锚点] 发现 {len(pending_anchor)} 个 capture 需要生成锚点匹配 CSV ...")
        try:
            from tools.match_radar_camera_anchor import (
                process_bin as _anchor_proc,
                load_capture as _load_cap,
            )
        except ImportError:
            import importlib.util
            _here = Path(__file__).parent.parent.parent / "tools" / "match_radar_camera_anchor.py"
            _spec = importlib.util.spec_from_file_location("match_radar_camera_anchor", _here)
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _anchor_proc = _mod.process_bin
            _load_cap = _mod.load_capture

        for i, bin_path in enumerate(pending_anchor, 1):
            cap_dir = bin_path.parent
            _log(f"  [{i}/{len(pending_anchor)}] W12锚点: {cap_dir.name}")
            try:
                parts = _load_cap(cap_dir)
                if not parts:
                    _log(f"    [警告] 无 part 目录，跳过")
                else:
                    out = _anchor_proc(bin_path, parts)
                    if out:
                        _log(f"    → 写出: {out.name}")
                    else:
                        _log(f"    [警告] process_bin 返回 None")
            except Exception as exc:
                _log(f"  [错误] {cap_dir.name}: {exc}")
            step_done += 1
            if step_cb:
                step_cb(step_done, total_steps)
    else:
        _log("[W12锚点] 所有 capture 均已有 match_radar_camera_anchor.csv ✓")

    # ── Step 2c: mat → camera CSV ─────────────────────────────────────────
    # 若 Step 2b 新生成了锚点 CSV，则重新计算 pending_matcam
    _fresh_matcam = [b for b in bins if needs_mat_camera_csv(b)]
    if _fresh_matcam:
        _log(f"[mat→camera] 发现 {len(_fresh_matcam)} 个 capture 需要生成 match_mat_camera.csv ...")
        try:
            from tools.match_mat_camera import process_capture as _matcam_proc
        except ImportError:
            import importlib.util
            _here = Path(__file__).parent.parent.parent / "tools" / "match_mat_camera.py"
            _spec = importlib.util.spec_from_file_location("match_mat_camera", _here)
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _matcam_proc = _mod.process_capture

        for i, bin_path in enumerate(_fresh_matcam, 1):
            cap_dir = bin_path.parent
            _log(f"  [{i}/{len(_fresh_matcam)}] mat→camera: {cap_dir.name}")
            try:
                _matcam_proc(cap_dir)
            except Exception as exc:
                _log(f"  [错误] {cap_dir.name}: {exc}")
            step_done += 1
            if step_cb:
                step_cb(step_done, total_steps)
    else:
        _log("[mat→camera] 所有 capture 均已有 match_mat_camera.csv ✓")

    # ── Step 3: per-segment radar_camera_match_ts.csv (新格式, 框架必需) ──
    # 重新计算（W12步骤可能刚刚生成了 match_mat_camera.csv，影响此列表）
    pending_csv = [b for b in bins if needs_csv_match(b)]
    if pending_csv:
        _log(f"[CSV] 发现 {len(pending_csv)} 个 capture 需要生成 segment CSV ...")
        try:
            from tools.gen_radar_camera_match import process_capture as _csv_proc
        except ImportError:
            import importlib.util
            _here = Path(__file__).parent.parent.parent / "tools" / "gen_radar_camera_match.py"
            spec = importlib.util.spec_from_file_location("gen_radar_camera_match", _here)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            _csv_proc = mod.process_capture

        for i, bin_path in enumerate(pending_csv, 1):
            cap_dir = bin_path.parent
            _log(f"  [{i}/{len(pending_csv)}] CSV: {cap_dir.name}")
            try:
                # 优先使用 W12 锚点数据（match_mat_camera.csv → per-segment CSV）
                if (cap_dir / "match_mat_camera.csv").exists():
                    n = anchor_to_seg_csvs(cap_dir)
                    _log(f"    [W12] → 写入 {n} 行（来自锚点匹配）")
                else:
                    n = _csv_proc(cap_dir, tz_offset_h=0.0, dry_run=False)
                    if n == 0:
                        # 多模态数据库 bin 时间戳可能是 CST, nav100 为 UTC, 需要 -8 偏移
                        _log("    [重试] 0 行匹配, 尝试 tz_offset=-8 (CST→UTC)")
                        n = _csv_proc(cap_dir, tz_offset_h=-8.0, dry_run=False)
                    _log(f"    → 写入 {n} 行")
            except Exception as exc:
                _log(f"  [错误] {cap_dir.name}: {exc}")
            step_done += 1
            if step_cb:
                step_cb(step_done, total_steps)
    else:
        _log("[CSV] 所有 segment 均已有 radar_camera_match_ts.csv ✓")

    # ── Step 4: 深度标注生成 (assign_depth_azimuth) ─────────────────────
    if pending_depth_caps:
        _log(f"[深度标注] 发现 {len(pending_depth_caps)} 个 capture 需要生成 depth_labels ...")
        try:
            from tools.assign_depth_azimuth import process_capture_dir as _depth_proc
            _depth_import_ok = True
        except ImportError:
            _depth_import_ok = False
            try:
                import importlib.util
                _here = Path(__file__).parent.parent.parent / "tools" / "assign_depth_azimuth.py"
                spec = importlib.util.spec_from_file_location("assign_depth_azimuth", _here)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _depth_proc = mod.process_capture_dir
                _depth_import_ok = True
            except Exception as exc:
                _log(f"  [错误] 无法导入 assign_depth_azimuth: {exc}")
                _depth_import_ok = False

        if _depth_import_ok:
            for i, cap_dir in enumerate(pending_depth_caps, 1):
                _log(f"  [{i}/{len(pending_depth_caps)}] 深度标注: {cap_dir.name}")
                try:
                    _use_annot = _annot_root_for_depth
                    _extra = [_autofill_root_for_depth] if _autofill_root_for_depth else []
                    n = _depth_proc(cap_dir,
                                    annot_root=_use_annot,
                                    radar_only=(_use_annot is None),
                                    fov_deg=8.78, verbose=False,
                                    extra_annot_roots=_extra)
                    _log(f"    → 方位角法生成 {n} 个 depth_labels JSON")
                except Exception as exc:
                    _log(f"  [错误] {cap_dir.name}: {exc}")
                # GPS 射线法补充（为无 mat 匹配的相机帧生成深度）
                try:
                    from tools.assign_depth_gps import process_capture_gps as _gps_proc
                    _gps_extra = [_autofill_root_for_depth] if _autofill_root_for_depth else []
                    n_gps = _gps_proc(cap_dir,
                                      annot_root=_annot_root_for_depth,
                                      fov_deg=8.78, verbose=False,
                                      extra_annot_roots=_gps_extra or None)
                    _log(f"    → GPS射线法补充 {n_gps} 个 depth_labels JSON")
                except Exception as exc:
                    _log(f"  [GPS] {cap_dir.name}: {exc}")
                step_done += 1
                if step_cb:
                    step_cb(step_done, total_steps)
    else:
        _log("[深度标注] 所有 capture 均已有 depth_labels ✓")

    # ── Step 5: GPS 目标深度数据库构建 (build_target_db) ────────────────────
    # Step 4 可能新生成了 depth_labels，重新计算 pending_target_db
    _seen_cap2: set[Path] = set(b.parent for b in bins)
    pending_target_db = [c for c in _seen_cap2 if needs_target_db(c)]
    if pending_target_db:
        _log(f"[目标DB] 发现 {len(pending_target_db)} 个 capture 需要构建 GPS 目标数据库 ...")
        try:
            from tools.build_target_db import process_capture as _db_build
        except ImportError:
            import importlib.util
            _here = Path(__file__).parent.parent.parent / "tools" / "build_target_db.py"
            _spec = importlib.util.spec_from_file_location("build_target_db", _here)
            _mod  = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _db_build = _mod.process_capture

        for i, cap_dir in enumerate(pending_target_db, 1):
            _log(f"  [{i}/{len(pending_target_db)}] 构建目标DB: {cap_dir.name}")
            try:
                db = _db_build(cap_dir, verbose=False)
                n_tgt = len(db.get("targets", [])) if db else 0
                _log(f"    → {n_tgt} 个目标")
            except Exception as exc:
                _log(f"  [错误] {cap_dir.name}: {exc}")
            step_done += 1
            if step_cb:
                step_cb(step_done, total_steps)
    else:
        _log("[目标DB] 所有 capture 均已有 target_depth_db.json ✓")

    # ── Step 6: GPS 数据库全量深度赋值 (assign_depth_from_db) ───────────────
    # 从 config 读取标注根目录
    _annot_roots: list[Path] = []
    try:
        from src.core.config import load_config as _lc
        _cfg = _lc()
        _ar = _cfg.get("annotations", {}).get("labelme_root", "")
        if _ar:
            _annot_roots.append(Path(_ar))
        _ar2 = _cfg.get("annotations", {}).get("autofill_root", "")
        if _ar2:
            _annot_roots.append(Path(_ar2))
    except Exception:
        pass

    # Step 5 可能新建了 target_depth_db，重新计算 pending_db_apply
    pending_db_apply = [c for c in _seen_cap2 if needs_depth_from_db(c)]
    if pending_db_apply and _annot_roots:
        _log(f"[GPS赋值] 发现 {len(pending_db_apply)} 个 capture 需要 GPS 深度赋值 ...")
        try:
            from tools.assign_depth_from_db import process_capture as _db_apply
        except ImportError:
            import importlib.util
            _here = Path(__file__).parent.parent.parent / "tools" / "assign_depth_from_db.py"
            _spec = importlib.util.spec_from_file_location("assign_depth_from_db", _here)
            _mod  = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            _db_apply = _mod.process_capture

        for i, cap_dir in enumerate(pending_db_apply, 1):
            _log(f"  [{i}/{len(pending_db_apply)}] GPS赋值: {cap_dir.name}")
            for annot_root in _annot_roots:
                if not annot_root.exists():
                    continue
                try:
                    n = _db_apply(cap_dir, annot_root,
                                  overwrite=False, verbose=False)
                    _log(f"    [{annot_root.name}] → {n} 帧")
                except Exception as exc:
                    _log(f"  [错误] {annot_root.name}: {exc}")
            step_done += 1
            if step_cb:
                step_cb(step_done, total_steps)
    elif pending_db_apply and not _annot_roots:
        _log("[GPS赋值] 跳过：config 中未配置 annotations.labelme_root")
    else:
        _log("[GPS赋值] 所有 capture 均已完成 GPS 深度赋值 ✓")
        step_cb(total_steps, total_steps)
    _log("[启动检查完成]")
