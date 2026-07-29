"""LH (多模态数据库) dataset adapter.

Directory layout (L:/LH_data_all_sensor)::

    {dataset_root}/                         # 例如  L:/LH_data_all_sensor
        {date}/                             # 4_29, 4_30, 5_9 ...
            {capture}/                      # with_cameras_capture_YYYYMMDD_HHMMSS
                {capture}_mmwave_udp.bin    # 原始毫米波 UDP 包
                mmwave_mat_1218style/       # 由 batch_convert_bins.py 生成
                    mmwave_*_AntFrame{NNN}_FZ{xxxxxx}-{yyyyyy}.mat
                {capture}_part{NNN}_{ts}/   # 分段子目录 (每个 bin 可有多个)
                    segment_{idx}_{t_start}_{t_end}/
                        images/
                            hikrobot_camera__DA8679037__image_raw/*.jpg
                            hikrobot_camera__DA8679038__image_raw/*.jpg
                        gps/         heading/        nav100_state/

序列粒度 (FrameLoader.list_sequences 返回项):
    "{date}/{capture}/{part}/{segment}"   <-- 唯一标识 (相对于 dataset_root)

    例如: "4_29/with_cameras_capture_20260429_164703/
            with_cameras_capture_20260429_164703_part000_2026-04-29-16-47-10/
            segment_000_000062.000_000239.000"

帧 ID:
    主相机 (DA8679038) jpg 文件名 stem, 例如
    "hikrobot_camera__DA8679038__image_raw_000001_t000076.011"

Capture 目录 (mmwave mat/bin 所在层) = seq_id 前两个路径分量:
    dataset_root/{date}/{capture}
"""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import math
import re
from collections import OrderedDict
from pathlib import Path

import cv2
import numpy as np

from src.core.types import CalibrationBundle, CameraIntrinsics, FrameData
from src.io.sensor_profile import SensorProfile

logger = logging.getLogger(__name__)

# ── Windows long path helper ──────────────────────────────────────────────
def _long_path(p: "Path") -> "Path":
    """Prepend long path prefix on Windows to bypass 260-char MAX_PATH limit."""
    import platform
    if platform.system() == "Windows":
        s = str(p)
        _PREFIX = "\\?\\"
        if not s.startswith(_PREFIX):
            return type(p)(_PREFIX + s)
    return p

# ── 传感器目录约定 ────────────────────────────────────────────────────────────
_CAMERA_DIRS: dict[str, str] = {
    # profile sensor key  →  segment 内子目录名
    # 主视图显示左目 DA8679037. CSV frame_id 基于 DA8679038, 图像加载用时间戳最近邻匹配.
    "camera_main_left":  "hikrobot_camera__DA8679037__image_raw",  # 037 = left cam (annotated camera)
    "camera_main_right": "hikrobot_camera__DA8679038__image_raw",  # 038 = right cam (fallback visible light)
}
# Fallback camera directories: if primary camera has no image, try these
_CAMERA_FALLBACK_DIRS: list[str] = [
    "hikrobot_camera__DA8679038__image_raw",  # 038 right cam
]
_LIDAR_SUBDIR = "pointclouds/at360__points"
_LIDAR_PREFIX = "at360__points"
_RADAR_SUFFIX    = "_radar"           # capture 下的 {bin_stem}_radar/ 文件夹
_MATCH_JSON_NAME = "radar_camera_match.json"  # 雷达-相机匹配表 (旧格式, 已废弃)
_MATCH_CSV_NAME  = "radar_camera_match_ts.csv"  # per-segment GPS时间对齐 CSV (新格式)
_ANCHOR_MAT_CSV_NAME = "match_mat_camera.csv"  # capture级：MAT中间包真实时间
_LOCAL_CSV_CACHE_REL = Path("temp") / "radar_match_cache"
_RIGHTCAM_CALIB_NAME = "rightcam(1)"  # 位于 dataset_root 下的右相机标定文本文件

# 帧 ID 锁定的相机 (用于 list_frames / load_frame 中 frame_id 的语义)
# DA8679037 即 mat_to_image_range.csv 中引用的相机, 也是 rightcam(1) 标定对应相机
_PRIMARY_CAMERA_KEY = "camera_main_left"

# 模块级缓存
_MATCH_CACHE: dict[Path, dict] = {}
_CSV_MATCH_CACHE: dict[Path, dict[str, str]] = {}  # seg_dir → {cam_stem: mat_filename}
_CSV_MATCH_ROWS_CACHE: dict[Path, tuple[bool, list[tuple[float, str]]]] = {}
_ANCHOR_MAT_TIME_CACHE: dict[Path, list[tuple[float, str]]] = {}
_CALIB_CACHE: dict[Path, dict] = {}
# capture 级时间范围缓存: capture_dir → (t_start_sec, t_end_sec) | None
_CAPTURE_TRANGE_CACHE: dict[Path, tuple[float, float] | None] = {}
# capture 级 GPS 地图缓存: capture_dir → (lat_arr, lon_arr, rel_arr) | None
_CAPTURE_GPS_MAP_CACHE: dict[Path, object] = {}
# mat 级相对时间缓存: mat_path → rel_time_sec | None
_MAT_RELTIME_CACHE: dict[Path, object] = {}
_CAPTURE_DEPTH_MAP_CACHE: dict[Path, np.ndarray] = {}
_CAPTURE_ALL_POINTS_CACHE: dict[Path, np.ndarray] = {}
_CAPTURE_BIN_DETECTION_CACHE: dict[tuple[Path, str], dict] = {}
_MMWAVE_LAYERS_CACHE: "OrderedDict[Path, list[dict]]" = OrderedDict()
_SEGMENT_NAV_CACHE: dict[Path, dict[str, np.ndarray]] = {}
_PART_GPS_TRACK_CACHE: dict[Path, np.ndarray] = {}
_PART_TAKEOFF_ALT_CACHE: dict[Path, float | None] = {}
_CAPTURE_OVERRIDE_CACHE: dict | None = None
# JSON 缓存文件名 (存于 mmwave_mat_1218style 目录下)
_MAT_TIMES_JSON = ".mat_times_cache.json"

# 文件名内嵌时间戳正则:  _tNNNNNN.NNN
_TS_REGEX = re.compile(r"_t(\d+\.\d+)")
# Image filename embeds 6-digit frame index _NNNNNN_t (037/038 synced, same index)
_IDX_REGEX = re.compile(r"_(\d{6})_t\d+\.\d+$")

# LabelMe 标注全局缓存: {str(root) → {seg_name → sorted [(t_float, json_path)]}}
# 支持多路标注根目录同时缓存，首次访问时扫描整个根目录并缓存，后续帧二分查找最近邻。
# DA8679037 与 DA8679038 帧索引不同步，必须用时间戳匹配。
_LABELME_MULTI_CACHE: "dict[str, dict[str, list]]" = {}
_LABELME_SEGMENT_CACHE: "dict[tuple[str, str], list]" = {}
_LABELME_MAX_DT: float = 1.0   # 最大允许时间差（秒）


def _camera_heading_offset_deg(seq_id: str) -> float:
    """Return the camera heading offset for a sequence.

    LH normally uses nav100 heading - 90 degrees. Dataset-specific optical-axis
    corrections are kept outside the source data and may be set per capture or
    per segment, with the segment rule taking precedence.
    """
    global _CAPTURE_OVERRIDE_CACHE
    if _CAPTURE_OVERRIDE_CACHE is None:
        path = Path(__file__).resolve().parents[3] / "profiles" / (
            "lh_capture_overrides.json"
        )
        try:
            _CAPTURE_OVERRIDE_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.exception("LH: failed to load capture heading overrides: %s", path)
            _CAPTURE_OVERRIDE_CACHE = {}

    key = str(seq_id).replace("\\", "/").strip("/")
    correction = 0.0
    capture_parts = key.split("/")[:2]
    capture_key = "/".join(capture_parts)
    capture_rule = _CAPTURE_OVERRIDE_CACHE.get("captures", {}).get(capture_key, {})
    segment_rule = _CAPTURE_OVERRIDE_CACHE.get("segments", {}).get(key, {})
    try:
        correction = float(
            segment_rule.get(
                "camera_heading_correction_deg",
                capture_rule.get("camera_heading_correction_deg", 0.0),
            )
        )
    except (TypeError, ValueError):
        logger.warning("LH: invalid camera heading correction for %s", key)
    return -90.0 + correction


def _safe_cache_name(text: str) -> str:
    out: list[str] = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out)


def _local_csv_cache_path(seg_dir: Path) -> Path:
    project_root = Path(__file__).resolve().parents[3]
    cache_dir = project_root / _LOCAL_CSV_CACHE_REL
    seg_key = hashlib.sha1(str(seg_dir).lower().encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{_safe_cache_name(seg_dir.name)}_{seg_key}.csv"


def _get_labelme_cache(annot_root: Path) -> "dict[str, list]":
    """扫描 annot_root 下所有 DA8679037 标注 JSON，
    构建 {完整 segment 相对路径 → [(t_float, json_path), ...]} 缓存。
    支持两种结构: {segment}/{cam_dir}/ 和 {segment}/images/{cam_dir}/"""
    global _LABELME_MULTI_CACHE
    root_str = str(annot_root)
    if root_str in _LABELME_MULTI_CACHE:
        return _LABELME_MULTI_CACHE[root_str]
    cache: dict[str, list] = {}
    ts_re = re.compile(r"_t(\d+\.\d+)$")
    try:
        for jf in annot_root.rglob("hikrobot_camera__DA8679037__image_raw/*.json"):
            mt = ts_re.search(jf.stem)
            if mt is None:
                continue
            t_val = float(mt.group(1))
            seg_key: str | None = None
            rel_parts = jf.relative_to(annot_root).parts
            for index, part in enumerate(rel_parts):
                if part.startswith("segment_"):
                    seg_key = Path(*rel_parts[:index + 1]).as_posix()
                    break
            if seg_key:
                cache.setdefault(seg_key, []).append((t_val, jf))
    except Exception as exc:
        logger.warning("LH: LabelMe cache scan failed: %s", exc)
    # 每个 segment 按时间排序
    total = 0
    for seg_key in cache:
        cache[seg_key].sort(key=lambda x: x[0])
        total += len(cache[seg_key])
    _LABELME_MULTI_CACHE[root_str] = cache
    logger.info("LH: LabelMe cache built: %d annotations from %s", total, annot_root)
    return cache


def _get_labelme_segment_entries(
    annot_root: Path,
    seq_id: str,
) -> list[tuple[float, Path]]:
    """Index only one segment instead of recursively scanning the whole root."""
    key = (str(annot_root), str(seq_id).replace("\\", "/"))
    cached = _LABELME_SEGMENT_CACHE.get(key)
    if cached is not None:
        return cached
    segment_dir = annot_root / Path(key[1])
    candidates = [
        segment_dir / "hikrobot_camera__DA8679037__image_raw",
        segment_dir / "images" / "hikrobot_camera__DA8679037__image_raw",
    ]
    entries: list[tuple[float, Path]] = []
    for camera_dir in candidates:
        try:
            if not camera_dir.exists():
                continue
            json_paths = list(camera_dir.glob("*.json"))
        except OSError as exc:
            logger.warning(
                "LH: skipping unreadable annotation directory %s: %s",
                camera_dir,
                exc,
            )
            continue
        for json_path in json_paths:
            timestamp = _parse_timestamp(json_path.stem)
            if timestamp is not None:
                entries.append((timestamp, json_path))
    entries.sort(key=lambda item: item[0])
    _LABELME_SEGMENT_CACHE[key] = entries
    return entries


def _load_labelme_annotations(fd: "FrameData", seg_dir: "Path | None", frame_id: str) -> None:
    """查找与 frame_id 时间最近的 DA8679037 LabelMe JSON，
    解析后写入 fd.meta['labelme_shapes'] 和 fd.meta['labelme_image_size']。
    同时尝试 labelme_root 和 autofill_root（按优先级顺序，labelme_root 优先）。"""
    try:
        from src.core.config import load_config
        ann_cfg = load_config().get("annotations", {})
    except Exception:
        return

    # 从帧名中提取时间戳
    mt = _TS_REGEX.search(frame_id)
    if mt is None:
        return
    t_query = float(mt.group(1))

    seg_key = str(getattr(fd, "seq_id", "")).replace("\\", "/")
    if not seg_key:
        return

    import bisect
    import json as _json

    for key in ("labelme_root", "autofill_root"):
        root_str = ann_cfg.get(key, "")
        if not root_str:
            continue
        annot_root = Path(root_str)
        if not annot_root.exists():
            continue

        entries = _get_labelme_segment_entries(annot_root, seg_key)
        if not entries:
            continue

        # 二分查找最近邻
        ts_list = [e[0] for e in entries]
        pos = bisect.bisect_left(ts_list, t_query)
        best_path: Path | None = None
        best_dt = float("inf")
        for i in (pos - 1, pos):
            if 0 <= i < len(entries):
                dt = abs(entries[i][0] - t_query)
                if dt < best_dt:
                    best_dt = dt
                    best_path = entries[i][1]
        if best_path is None or best_dt > _LABELME_MAX_DT:
            continue

        logger.debug("LH: labelme match t=%.3f → %s (dt=%.3fs, src=%s)",
                     t_query, best_path.name, best_dt, key)
        try:
            j = _json.loads(best_path.read_text(encoding="utf-8"))
            shapes = []
            for source_shape_index, s in enumerate(j.get("shapes", [])):
                if s.get("shape_type") != "rectangle":
                    continue
                pts = s.get("points", [])
                if len(pts) < 2:
                    continue
                shapes.append(
                    {
                        "label": s["label"],
                        "points": pts,
                        "source_shape_index": source_shape_index,
                    }
                )
            if shapes:
                fd.meta["labelme_shapes"] = shapes
                fd.meta["labelme_source_path"] = str(best_path)
                fd.meta["labelme_image_size"] = (
                    j.get("imageWidth", 1920), j.get("imageHeight", 1200))
                depth_root_str = ann_cfg.get("depth_root", "")
                if depth_root_str:
                    depth_path = (
                        Path(depth_root_str)
                        / best_path.relative_to(annot_root)
                    )
                    if depth_path.exists():
                        try:
                            depth_json = _json.loads(
                                depth_path.read_text(encoding="utf-8")
                            )
                            depth_boxes = []
                            for depth_shape in depth_json.get("shapes", []):
                                depth_pts = depth_shape.get("points", [])
                                if len(depth_pts) < 2:
                                    continue
                                xs = [float(point[0]) for point in depth_pts]
                                ys = [float(point[1]) for point in depth_pts]
                                attributes = depth_shape.get("attributes") or {}
                                depth_boxes.append(
                                    {
                                        "label": depth_shape.get("label", ""),
                                        "bbox_xyxy": [
                                            min(xs), min(ys), max(xs), max(ys)
                                        ],
                                        "depth_m": attributes.get("depth_m"),
                                        "method": attributes.get(
                                            "depth_method", "no_metric_anchor"
                                        ),
                                        "confidence": attributes.get(
                                            "depth_confidence", 0.0
                                        ),
                                        "support_points": attributes.get(
                                            "depth_support_points", 0
                                        ),
                                        "target_id": attributes.get(
                                            "depth_target_id"
                                        ),
                                    }
                                )
                            fd.meta["depth_label_data"] = {
                                "method": "hybrid_export_labelme",
                                "boxes": depth_boxes,
                                "clusters": [],
                                "source_path": str(depth_path),
                            }
                            fd.meta["depth_label_source_path"] = str(depth_path)
                        except Exception as exc:
                            logger.debug(
                                "LH: depth LabelMe load failed %s: %s",
                                depth_path,
                                exc,
                            )
                return  # 找到即返回，优先用 labelme_root
        except Exception as exc:
            logger.debug("LH: labelme JSON load failed %s: %s", best_path, exc)


# ── 公共 API ─────────────────────────────────────────────────────────────────

def warmup_labelme_cache() -> None:
    """Compatibility no-op; indexing is now fast and segment-local."""
    return


def _configured_annotation_roots(*, include_autofill: bool = True) -> list[Path]:
    try:
        from src.core.config import load_config
        ann_cfg = load_config().get("annotations", {})
    except Exception:
        logger.exception("LH: failed to read annotation roots")
        return []

    roots: list[Path] = []
    keys = ("labelme_root", "autofill_root") if include_autofill else ("labelme_root",)
    for key in keys:
        value = ann_cfg.get(key, "")
        if value:
            path = Path(value)
            if path.exists():
                roots.append(path)
    return roots


def _capture_has_bin(capture_dir: Path) -> bool:
    try:
        return any(
            path.is_file()
            and (
                path.suffix.lower() == ".bin"
                or path.name == ".remote_bin_available"
            )
            for path in capture_dir.iterdir()
        )
    except OSError:
        return False


def _sequence_has_image_annotations(
    seq_id: str,
    annotation_roots: list[Path],
) -> bool:
    return any(
        _get_labelme_segment_entries(root, seq_id)
        for root in annotation_roots
    )


def list_sequences(root: Path, profile: SensorProfile) -> list[str]:
    """枚举同时具有 capture BIN 和图像标注的 ``segment_*/`` 序列.

    人工标注与自动标注根目录取并集。过滤在场景浏览器建树前完成，
    因此没有 BIN 的 capture 和没有 LabelMe JSON 的 segment 不会显示。

    兼容三种布局:

    - 4 层 (canonical):  ``{root}/{date}/{capture}/{part}/segment_*/``
    - 3 层:              ``{root}/{date}/{capture}/segment_*/``
    - 2 层 (浅层):       ``{root}/{capture}/segment_*/``  ← 例如 D:/Dataset/多模态数据库/1/segment_*

    Returns
    -------
    list[str]
        每项为相对于 root 的路径字符串.
    """
    if not root.exists():
        return []
    # 不进入这些目录 (避免把图像/标定子目录当 capture 遍历)
    _SKIP = {"images", "gps", "heading", "nav100_state", "pointclouds",
             "mmwave_mat_1218style", "tools", "labels", "calibration"}
    seqs: list[str] = []
    seen: set[str] = set()
    annotation_roots = _configured_annotation_roots(include_autofill=False)
    if not annotation_roots:
        logger.warning("LH: no usable annotation roots; no sequences listed")
        return []

    def _emit(seg: Path) -> None:
        rel = seg.relative_to(root).as_posix()
        if rel in seen:
            return
        capture_dir = _capture_dir(root, rel)
        if not _capture_has_bin(capture_dir):
            return
        if not _sequence_has_image_annotations(rel, annotation_roots):
            return
        seen.add(rel)
        seqs.append(rel)

    def _walk(d: Path, depth: int) -> None:
        if depth > 4:
            return
        try:
            children = sorted(d.iterdir(), key=_natural_key)
        except OSError:
            return
        for c in children:
            if not c.is_dir():
                continue
            name = c.name
            if name.startswith("segment_"):
                _emit(c)
                continue   # 不递归进 segment 内部
            if name in _SKIP or name.endswith("_radar"):
                continue
            _walk(c, depth + 1)

    _walk(root, 0)
    seqs.sort(key=_natural_key)
    return seqs


def _list_annotated_frame_ids(seq_id: str, *, include_autofill: bool = True) -> list[str]:
    """返回该 segment 下所有有 LabelMe 标注的帧 ID（DA8679037 图像 stem）。

    直接复用 segment-local 缓存。默认可取 labelme_root/autofill_root 并集；
    场景浏览器传 include_autofill=False 时只显示人工标注关键帧。
    并缓存，后续调用均为 O(1) 字典查找（避免重复 rglob）。
    返回格式: ['stem_t12345.678', ...]  (无扩展名，与 load_frame frame_id 约定一致)
    """
    try:
        from src.core.config import load_config
        ann_cfg = load_config().get("annotations", {})
    except Exception:
        return []

    found: dict[float, str] = {}   # ts → stem

    keys = ("labelme_root", "autofill_root") if include_autofill else ("labelme_root",)
    for key in keys:
        root_str = ann_cfg.get(key, "")
        if not root_str:
            continue
        ann_root = Path(root_str)
        if not ann_root.exists():
            continue
        seg_key = str(seq_id).replace("\\", "/")
        for t_val, jf in _get_labelme_segment_entries(ann_root, seg_key):
            if t_val not in found:
                found[t_val] = jf.stem

    return sorted(found.values(), key=lambda s: _parse_timestamp(s) or 0.0)


def list_frames(root: Path, profile: SensorProfile, seq_id: str) -> list[str]:
    """frame 列表 — 只返回人工 LabelMe 标注关键帧。

    查找策略（优先级由高到低）：
      A. 人工标注根目录（labelme_root）— 用于人工核验与修改
      B. autofill 标注不在界面显示，但会参与深度前后同步

    每帧的雷达 mat 仍由 _pick_mmwave_mat 就近匹配。
    """
    seg_dir = _segment_dir(root, seq_id)
    if seg_dir is None:
        return []

    capture_dir = _capture_dir(root, seq_id)
    return _list_annotated_frame_ids(seq_id, include_autofill=False)


def load_frame(root: Path, profile: SensorProfile, seq_id: str,
               frame_id: str) -> FrameData:
    """加载单帧的所有传感器数据.

    mat 查找策略:
        1. 从 radar_camera_match.json 精确查找 (seq_id, frame_id) → mat 文件名。
        2. 若无 match JSON, 则回退到按时间比例估算的 mat 索引。
    """
    seg_dir = _segment_dir(root, seq_id)
    fd = FrameData(seq_id=seq_id, frame_id=frame_id)
    if seg_dir is None:
        logger.warning("LH: segment dir not found for seq_id=%s", seq_id)
        fd.calibration = _build_calibration_from_profile(profile)
        return fd

    scene_dir = _capture_dir(root, seq_id)

    # 时间戳基准 (来自主相机 jpg 文件名)
    t_ref = _parse_timestamp(frame_id)
    fd.timestamp = t_ref if t_ref is not None else 0.0
    fd.meta["camera_time"] = fd.timestamp

    # ── 相机 ────────────────────────────────────────────────────────────────
    for sensor_key, cam_subdir in _CAMERA_DIRS.items():
        # 跳过被 profile 显式禁用的相机 (例如 IR 默认 enabled=false)
        entry = profile.sensors.get(sensor_key)
        if entry is not None and entry.extra.get("enabled") is False:
            logger.info("LH: camera %s disabled by profile, skipping", sensor_key)
            continue

        cam_dir = seg_dir / "images" / cam_subdir
        if not cam_dir.exists():
            logger.info("LH: camera dir not found: %s (sensor=%s)", cam_dir, sensor_key)
            # 尝试 fallback 目录
            for fb_dir in _CAMERA_FALLBACK_DIRS:
                fb_path = seg_dir / "images" / fb_dir
                if fb_path.exists():
                    logger.info("LH: using fallback camera dir: %s", fb_path)
                    cam_dir = fb_path
                    break
            if not cam_dir.exists():
                continue

        # Strip .jpg / .jpeg / .png extension from frame_id if the web frontend
        # already included it (avoid .jpg.jpg double-extension).
        _fid = frame_id
        for _ext in (".jpg", ".jpeg", ".png", ".bmp"):
            if _fid.lower().endswith(_ext):
                _fid = _fid[: -len(_ext)]
                break

        if sensor_key == _PRIMARY_CAMERA_KEY:
            # 先尝试精确匹配（当主相机与 CSV 为同一相机时有效）
            img_path = cam_dir / f"{_fid}.jpg"
            if not _long_path(img_path).exists() and t_ref is not None:
                # CSV frame_id 来自 DA8679038，而主相机目录为 DA8679037，
                # 文件名前缀不同，退回时间戳最近邻匹配。
                logger.info("LH: exact match failed for %s, trying nearest timestamp (t_ref=%.3f)",
                           img_path.name, t_ref)
                img_path = _nearest_by_timestamp(cam_dir, t_ref, suffix=".jpg")
        else:
            # 副相机文件名前缀不同, 只能按时间戳最近邻匹配
            img_path = _nearest_by_timestamp(cam_dir, t_ref, suffix=".jpg")

        if img_path is None or not _long_path(img_path).exists():
            logger.info("LH: no image found in %s for frame %s (t_ref=%.3f)",
                       cam_dir, _fid, t_ref or 0.0)
            continue
        logger.info("LH: loading image %s for sensor %s", img_path.name, sensor_key)
        img = _imread_unicode(img_path)
        if img is None:
            logger.info("LH: cv2.imread failed for %s", img_path)
            continue
        fd.images[sensor_key] = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        logger.info("LH: loaded %s image %dx%d for sensor %s",
                   img_path.name, img.shape[1], img.shape[0], sensor_key)

    # ── LiDAR: 已禁用 ──────────────────────────────────────────────────────
    # 用户要求 LH 不读 lidar, 仅做相机+毫米波雷达 2D 标注. 跳过 at360 PCD.

    # ── 毫米波雷达 ({bin_stem}_radar/) ─────────────────────────────────────
    mmw_dir = _find_radar_dir(scene_dir)
    if mmw_dir is not None and mmw_dir.exists():
        # Segment CSV is authoritative because camera relative time restarts
        # from zero in each part. Capture-wide nearest-time matching can map
        # part001 images onto part000 MATs.
        has_segment_match, mat_path, match_time = _pick_segment_csv_mat(
            mmw_dir, seg_dir, frame_id
        )
        if mat_path is not None:
            fd.meta["_mat_center_time"] = match_time
            fd.meta["_mat_time_delta"] = abs(
                float(match_time) - float(t_ref or 0.0)
            )
            fd.meta["_mat_time_source"] = "segment_csv"
        elif not has_segment_match:
            mat_path = _pick_mmwave_mat(
                mmw_dir, seg_dir, frame_id, capture_dir=scene_dir
            )
        mat_name: str | None = None
        # Legacy mappings are fallbacks for captures without anchor timing.
        if mat_path is None and not has_segment_match and seg_dir is not None:
            mat_name = _load_seg_csv_match(seg_dir).get(frame_id)
        if mat_path is None and mat_name is None and not has_segment_match:
            match = _load_radar_match(scene_dir)
            if match:
                seg_match = match.get(seq_id, {})
                mat_name = seg_match.get(frame_id)
        if mat_path is None and mat_name:
            cand = mmw_dir / mat_name
            if cand.exists():
                mat_path = cand
        if mat_path is not None:
            fd.meta["_mat_path"] = mat_path   # 供地图模式 ENU 雷达点云使用
            if t_ref is not None and "_mat_time_source" not in fd.meta:
                for mat_time, anchor_name in _load_anchor_mat_times(scene_dir):
                    if anchor_name == mat_path.name:
                        fd.meta["_mat_center_time"] = float(mat_time)
                        fd.meta["_mat_time_delta"] = abs(float(mat_time) - t_ref)
                        fd.meta["_mat_time_source"] = "w12_anchor"
                        break
            try:
                pts, mat_hdg0 = _load_mmwave_pointcloud(mat_path)
                if pts.size > 0:
                    fd.pointclouds["radar_mmwave"] = pts
                    fd.meta["_mat_ref_heading"] = mat_hdg0
            except Exception as exc:
                logger.debug("LH: failed to load mmwave %s: %s", mat_path, exc)
            # ── Depth label (assign_depth_azimuth 输出) ───────────────────
            _load_depth_labels_from_mat(fd, mat_path, scene_dir, frame_id=frame_id)
    # ── GPS 射线深度标签回退（assign_depth_gps.py 输出） ────────────────────
    # 当 mat-based 深度标签不存在或 boxes 为空时，尝试按相机帧 stem 加载
    _load_depth_labels_from_camera(fd, frame_id, scene_dir)
    fd.calibration = _build_calibration_from_profile(profile)
    _apply_rightcam_calibration(fd.calibration, root, profile)

    # ── 标签 (LH 暂无 GT) ─────────────────────────────────────────────────
    fd.labels = []

    # ── GPS + ENU 雷达 meta (供地图模式使用) ──────────────────────────────
    _populate_gps_meta(fd, seg_dir, t_ref)
    _rebuild_mmwave_body_from_point_gps(fd)

    # ── capture_dir 写入 meta（BIN 检测地图由 UI 首次使用时按需加载）──────
    fd.meta["capture_dir"] = str(scene_dir)

    # ── 航向修正: 将雷达点云从参考束坐标系旋转到当前相机帧坐标系 ──────────
    # 参考束体系与相机帧体系之间存在 Δh = h_cam - h_ref 的航向差,
    # 对于 75mm 窄视角相机, 10° 航向差在 100m 处造成约 200px 的偏差。
    if (
        "radar_mmwave" in fd.pointclouds
        and "_mat_ref_heading" in fd.meta
        and not fd.meta.get("_radar_body_from_point_gps")
    ):
        pts = fd.pointclouds["radar_mmwave"]
        if pts.shape[0] > 0 and fd.meta.get("gps_hdg") is not None:
            # nav100 heading has a +90 degree mounting convention relative to
            # the camera/radar forward axis used by the LH projection code.
            camera_body_hdg = float(fd.meta["camera_heading_deg"])
            dh = camera_body_hdg - float(fd.meta["_mat_ref_heading"])
            # 归一化到 (-180, 180]
            dh = (dh + 180.0) % 360.0 - 180.0
            if abs(dh) > 0.5:   # < 0.5° 误差对窄视角影响可忽略
                dh_rad = np.deg2rad(dh)
                cos_dh, sin_dh = float(np.cos(dh_rad)), float(np.sin(dh_rad))
                pts = pts.copy()
                xr, yr = pts[:, 0].copy(), pts[:, 1].copy()
                pts[:, 0] = cos_dh * xr - sin_dh * yr
                pts[:, 1] = sin_dh * xr + cos_dh * yr
                fd.pointclouds["radar_mmwave"] = pts

    # ── OSM 语义标注 (4 类: bg/building/tower/wind_turbine) ────────────────
    try:
        from src.io import semantic_osm as _sem
        sem_cfg = _sem.get_default_config()
        if (sem_cfg.enabled
            and "radar_mmwave" in fd.pointclouds
            and fd.meta.get("gps_lat") is not None
            and fd.meta.get("gps_hdg") is not None):
            labels = _sem.annotate_frame(
                pts_body=fd.pointclouds["radar_mmwave"],
                body_heading_deg=float(fd.meta["gps_hdg"]),
                ref_lat=float(fd.meta["gps_lat"]),
                ref_lon=float(fd.meta["gps_lon"]),
                seg_dir=seg_dir,
                t_ref=t_ref,
                cfg=sem_cfg,
            )
            if labels is not None:
                fd.meta["radar_semantic_labels"] = labels
                fd.meta["radar_semantic_class_names"] = _sem.CLASS_NAMES
    except Exception as exc:
        logger.debug("LH: OSM semantic labeling failed: %s", exc)

    # ── LabelMe 2D 标注叠加 (building / signal tower …) ──────────────────
    _load_labelme_annotations(fd, seg_dir, frame_id)

    return fd



# ── GPS / 地图辅助 ────────────────────────────────────────────────────────────

def _rebuild_mmwave_body_from_point_gps(fd: "FrameData") -> None:
    """Convert the selected MAT's per-point GPS positions to current-frame body.

    The MAT spans several seconds, so rotating a cloud around its first beam
    origin is insufficient for a moving UAV. Each point is instead translated
    from its own absolute GPS position to the camera frame's interpolated GPS
    position, then rotated with the established LH heading convention.
    """
    enu_pts = fd.meta.get("radar_enu_pts")
    gps_lat = fd.meta.get("gps_lat")
    gps_lon = fd.meta.get("gps_lon")
    gps_hdg = fd.meta.get("gps_hdg")
    if (
        enu_pts is None
        or gps_lat is None
        or gps_lon is None
        or gps_hdg is None
    ):
        return

    points = np.asarray(enu_pts, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] < 4 or len(points) == 0:
        return
    valid = np.isfinite(points[:, :4]).all(axis=1)
    if not valid.any():
        return
    points = points[valid]

    lats = points[:, 0]
    lons = points[:, 1]
    altitudes = points[:, 2]
    vehicle_alt = fd.meta.get("gps_alt")
    z_up = (
        altitudes - float(vehicle_alt)
        if vehicle_alt is not None
        else altitudes
    )

    cos_lat = float(np.cos(np.deg2rad(float(gps_lat))))
    east = (
        (lons - float(gps_lon))
        * np.deg2rad(1.0)
        * _R_EARTH_EQ
        * cos_lat
    )
    north = (
        (lats - float(gps_lat))
        * np.deg2rad(1.0)
        * _R_EARTH_POL
    )

    camera_heading = float(
        fd.meta.get("camera_heading_deg", float(gps_hdg) - 90.0)
    )
    heading = np.deg2rad(camera_heading)
    cos_h = float(np.cos(heading))
    sin_h = float(np.sin(heading))
    x_right = east * cos_h - north * sin_h
    y_forward = east * sin_h + north * cos_h

    body = np.column_stack(
        [x_right, y_forward, z_up, points[:, 3]]
    ).astype(np.float32)
    fd.pointclouds["radar_mmwave"] = body
    fd.meta["_radar_body_from_point_gps"] = True
    logger.info(
        "LH: nearest-MAT point-GPS body cloud: mat=%s points=%d "
        "heading=%.1f deg range=[%.0f, %.0f]m",
        Path(fd.meta.get("_mat_path", "")).name,
        len(body),
        camera_heading,
        float(np.hypot(body[:, 0], body[:, 1]).min()),
        float(np.hypot(body[:, 0], body[:, 1]).max()),
    )

def _populate_gps_meta(fd: "FrameData", seg_dir: "Path | None", t_ref: "float | None") -> None:
    """填充 fd.meta 中的 GPS 轨迹、当前帧位置、航向和 ENU 雷达点云.

    键说明:
        gps_lat       float  当前帧纬度
        gps_lon       float  当前帧经度
        gps_hdg       float  航向角 (°, 北起顺时针)
        gps_track     ndarray (N,3) [lat, lon, t_sec] 全段轨迹
        radar_enu_pts ndarray (N,4) [E, N, U, dB] 以 radar_ref 为原点的 ENU
        radar_ref_lat float  ENU 原点纬度
        radar_ref_lon float  ENU 原点经度
    """
    if seg_dir is None or not seg_dir.exists():
        return

    nav = _SEGMENT_NAV_CACHE.get(seg_dir)
    if nav is None:
        nav = {}
        def _rows(path: Path) -> list[dict]:
            with path.open(newline="", encoding="utf-8") as handle:
                return list(csv.DictReader(handle))

        gps_csv = seg_dir / "gps" / "nav100__fix" / "nav100__fix.csv"
        hdg_csv = seg_dir / "heading" / "nav100__heading" / "nav100__heading.csv"
        state_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
        if not gps_csv.exists():
            return
        try:
            rows = _rows(gps_csv)
            nav["gps_t"] = np.asarray(
                [float(row["relative_time_sec"]) for row in rows], dtype=np.float64
            )
            nav["gps_lat"] = np.asarray(
                [float(row["latitude"]) for row in rows], dtype=np.float64
            )
            nav["gps_lon"] = np.asarray(
                [float(row["longitude"]) for row in rows], dtype=np.float64
            )
            nav["gps_alt"] = np.asarray(
                [float(row.get("altitude", 0.0)) for row in rows], dtype=np.float64
            )
            if hdg_csv.exists():
                rows = _rows(hdg_csv)
                nav["heading_t"] = np.asarray(
                    [float(row["relative_time_sec"]) for row in rows], dtype=np.float64
                )
                nav["heading"] = np.asarray(
                    [float(row["value"]) for row in rows], dtype=np.float64
                )
            if state_csv.exists():
                rows = _rows(state_csv)
                nav["state_t"] = np.asarray(
                    [float(row["relative_time_sec"]) for row in rows], dtype=np.float64
                )
                for key in (
                    "pitch", "roll", "yaw",
                    "pitch_rate", "roll_rate", "yaw_rate",
                ):
                    nav[key] = np.asarray(
                        [float(row.get(key, 0.0)) for row in rows], dtype=np.float64
                    )
        except Exception as exc:
            logger.debug("LH: navigation cache load failed: %s", exc)
            return
        _SEGMENT_NAV_CACHE[seg_dir] = nav

    gps_t = nav.get("gps_t")
    if gps_t is None or not len(gps_t):
        return
    t = t_ref if t_ref is not None else float(gps_t[0])
    fd.meta["gps_track"] = _load_part_gps_track(seg_dir)
    if not len(fd.meta["gps_track"]):
        fd.meta["gps_track"] = np.column_stack(
            [nav["gps_lat"], nav["gps_lon"], gps_t]
        )
    fd.meta["gps_lat"] = float(np.interp(t, gps_t, nav["gps_lat"]))
    fd.meta["gps_lon"] = float(np.interp(t, gps_t, nav["gps_lon"]))
    fd.meta["gps_alt"] = float(np.interp(t, gps_t, nav["gps_alt"]))
    takeoff_altitude = _load_part_takeoff_altitude(seg_dir)
    if takeoff_altitude is not None:
        fd.meta["takeoff_ground_elevation_m"] = takeoff_altitude

    if "heading_t" in nav and len(nav["heading_t"]):
        fd.meta["gps_hdg"] = float(
            np.interp(t, nav["heading_t"], nav["heading"])
        )
        heading_offset = _camera_heading_offset_deg(fd.seq_id)
        fd.meta["camera_heading_offset_deg"] = heading_offset
        fd.meta["camera_heading_deg"] = (
            float(fd.meta["gps_hdg"]) + heading_offset
        ) % 360.0
    if "state_t" in nav and len(nav["state_t"]):
        for key in (
            "pitch", "roll", "yaw",
            "pitch_rate", "roll_rate", "yaw_rate",
        ):
            value = float(np.interp(t, nav["state_t"], nav[key]))
            fd.meta[f"gps_{key}_deg"] = float(np.degrees(value))

    # ── 当前 MAT 的绝对 GPS 点云 ────────────────────────────────────────────
    mat_path = fd.meta.get("_mat_path")
    if mat_path is None or not mat_path.exists():
        return
    try:
        enu_pts, ref_lat, ref_lon = _load_mmwave_enu_pts(mat_path)
        fd.meta["radar_enu_pts"] = enu_pts
        fd.meta["radar_ref_lat"] = ref_lat
        fd.meta["radar_ref_lon"] = ref_lon
    except Exception as exc:
        logger.debug("LH: ENU radar pts failed: %s", exc)


def _load_part_gps_track(seg_dir: Path) -> np.ndarray:
    """Return the complete trajectory for the current part, not one segment."""
    part_dir = seg_dir.parent
    cached = _PART_GPS_TRACK_CACHE.get(part_dir)
    if cached is not None:
        return cached
    chunks: list[np.ndarray] = []
    try:
        segments = sorted(
            (
                path for path in part_dir.iterdir()
                if path.is_dir() and path.name.startswith("segment_")
            ),
            key=_natural_key,
        )
    except OSError:
        segments = [seg_dir]
    for segment in segments:
        csv_path = segment / "gps" / "nav100__fix" / "nav100__fix.csv"
        if not csv_path.exists():
            continue
        try:
            with csv_path.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            if rows:
                chunks.append(np.column_stack([
                    np.asarray([float(row["latitude"]) for row in rows]),
                    np.asarray([float(row["longitude"]) for row in rows]),
                    np.asarray([float(row["relative_time_sec"]) for row in rows]),
                ]))
        except Exception as exc:
            logger.debug("LH: part trajectory read failed %s: %s", csv_path, exc)
    if chunks:
        result = np.concatenate(chunks, axis=0)
        result = result[np.argsort(result[:, 2])]
        # Navigation CSVs are high rate. Downsample only for map rendering.
        if len(result) > 10000:
            keep = np.linspace(0, len(result) - 1, 10000, dtype=np.int64)
            result = result[keep]
    else:
        result = np.empty((0, 3), dtype=np.float64)
    _PART_GPS_TRACK_CACHE[part_dir] = result
    return result


def _load_part_takeoff_altitude(seg_dir: Path) -> float | None:
    """Return the first valid GPS altitude recorded in the current part."""
    part_dir = seg_dir.parent
    if part_dir in _PART_TAKEOFF_ALT_CACHE:
        return _PART_TAKEOFF_ALT_CACHE[part_dir]
    result: float | None = None
    try:
        segments = sorted(
            (
                path for path in part_dir.iterdir()
                if path.is_dir() and path.name.startswith("segment_")
            ),
            key=_natural_key,
        )
        for segment in segments:
            csv_path = segment / "gps" / "nav100__fix" / "nav100__fix.csv"
            if not csv_path.exists():
                continue
            with csv_path.open(newline="", encoding="utf-8") as handle:
                for row in csv.DictReader(handle):
                    value = float(row.get("altitude", "nan"))
                    if np.isfinite(value):
                        result = value
                        break
            if result is not None:
                break
    except Exception as exc:
        logger.debug("LH: takeoff altitude read failed for %s: %s", part_dir, exc)
    _PART_TAKEOFF_ALT_CACHE[part_dir] = result
    return result


def _load_mmwave_enu_pts(path: "Path"):
    """从 .mat 生成雷达绝对位置点云 (N,4) [lat_deg, lon_deg, U_m, dB].

    每个点的 lat/lon 基于采集该波束时的真实 GPS 直接计算，
    不做参考帧归一化（无 GPS 差值归零问题）。

    返回: (pts, center_lat, center_lon)
      pts        : (N,4) [lat_deg, lon_deg, U_m, dB]
      center_lat : 全帧 GPS 纬度均值（用于地图定位）
      center_lon : 全帧 GPS 经度均值
    """
    import math
    layers = _load_mmwave_layers(path)
    if not layers:
        return np.empty((0, 4), dtype=np.float32), 0.0, 0.0

    all_lat = np.concatenate([L["pose"][:, 2] for L in layers])
    all_lon = np.concatenate([L["pose"][:, 3] for L in layers])
    center_lat = float(np.mean(all_lat))
    center_lon = float(np.mean(all_lon))

    n_train = _RADAR_CFAR_TRAIN * 2
    alpha = _cfar_alpha(n_train, _RADAR_CFAR_PFA)

    chunks: list = []
    for L in layers:
        el_deg = L["el_deg"]; az_arr = L["az"]
        sd = L["sd"]; pose = L["pose"]
        n_range, n_az = sd.shape
        if pose.shape[0] < n_az:
            n_az = pose.shape[0]; sd = sd[:, :n_az]; az_arr = az_arr[:n_az]
        rng_m = np.arange(1, n_range + 1, dtype=np.float32) * _RADAR_RANGE_STEP_M
        in_range = rng_m < _RADAR_MAX_RANGE_M
        sd_lin = np.power(10.0, sd / 10.0).astype(np.float64)
        for j in range(n_az):
            col = sd_lin[:, j]
            mask = _ca_cfar_1d(col, _RADAR_CFAR_TRAIN, _RADAR_CFAR_GUARD, alpha)
            mask &= sd[:, j] > _RADAR_CFAR_MIN_DB  # 地图模式使用统一 dB 门限
            mask &= in_range
            if not mask.any():
                continue
            ri = np.where(mask)[0]; R = rng_m[ri]
            az_rad = math.radians(float(az_arr[j]))
            el_rad = math.radians(el_deg)
            ce = math.cos(el_rad); se = math.sin(el_rad)
            ca = math.cos(az_rad); sa = math.sin(az_rad)
            xb = R * ce * sa; yb = R * ce * ca; zb = R * se
            # 本束真实 GPS 位姿
            lat_b = float(pose[j, 2]); lon_b = float(pose[j, 3])
            alt_b = float(pose[j, 4]); hdg_b = float(pose[j, 5])
            h = math.radians(hdg_b)
            cos_h = math.cos(h); sin_h = math.sin(h)
            # 束体系 -> ENU (相对于本束 GPS 原点)
            E_local = xb * cos_h + yb * sin_h
            N_local = -xb * sin_h + yb * cos_h
            U_local = zb
            # 直接转换到绝对 lat/lon（不做帧内归一化）
            coslat_b = math.cos(math.radians(lat_b))
            lat_target = lat_b + N_local / _R_EARTH_POL * (180.0 / math.pi)
            lon_target = lon_b + E_local / (_R_EARTH_EQ * coslat_b) * (180.0 / math.pi)
            U_abs = alt_b + U_local
            inten = sd[ri, j].astype(np.float32)
            chunks.append(np.column_stack([
                lat_target.astype(np.float32),
                lon_target.astype(np.float32),
                U_abs.astype(np.float32),
                inten,
            ]))
    if not chunks:
        return np.empty((0, 4), dtype=np.float32), center_lat, center_lon
    out = np.concatenate(chunks, axis=0)
    if len(out) > _RADAR_MAX_POINTS:
        idx = np.argpartition(out[:, 3], -_RADAR_MAX_POINTS)[-_RADAR_MAX_POINTS:]
        out = out[idx]
    return out, center_lat, center_lon


def load_capture_bin_detection_map(
    capture_dir: Path,
    coordinate_mode: str = "nwu",
) -> dict:
    """Load the native BIN powerline/isolated/dense-region world map."""
    capture_dir = Path(capture_dir)
    cache_key = (capture_dir, coordinate_mode)
    cached = _CAPTURE_BIN_DETECTION_CACHE.get(cache_key)
    if cached is not None:
        return cached
    bin_paths = sorted(capture_dir.glob("*_mmwave_udp.bin"), key=_natural_key)
    if not bin_paths:
        return {}
    from src.io.bin_detection_map import (
        load_or_build_bin_detection_world_map,
    )
    project_root = Path(__file__).resolve().parents[3]
    result = load_or_build_bin_detection_world_map(
        bin_paths[0],
        project_root / "temp" / "bin_detection_cache",
        coordinate_mode=coordinate_mode,
    )
    _CAPTURE_BIN_DETECTION_CACHE[cache_key] = result
    return result

# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _natural_key(item) -> list:
    """对 'segment_001' / 'frame_0009' 等做自然排序."""
    s = item.name if isinstance(item, Path) else str(item)
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r"(\d+)", s)]


def _seg_time_range(seg_dir: Path) -> tuple[float, float] | None:
    """从 segment_NNN_TTTT.TTT_UUUU.UUU 目录名解析 [t_start, t_end] 秒.

    例如 segment_000_000062.000_000239.000 → (62.0, 239.0).
    解析失败返回 None.
    """
    parts = seg_dir.name.split("_")
    # segment_NNN_TTTT.TTT_UUUU.UUU → parts[0]='segment', [1]=NNN, [2]=TTTT.TTT, [3]=UUUU.UUU
    if len(parts) >= 4:
        try:
            return float(parts[2]), float(parts[3])
        except ValueError:
            pass
    return None


def _capture_time_range(capture_dir: Path) -> tuple[float, float] | None:
    """从 capture 下所有 segment 目录名取并集, 得到 capture 总时间范围.

    结果缓存到 _CAPTURE_TRANGE_CACHE, 同一 capture 只扫描一次磁盘.
    """
    if capture_dir in _CAPTURE_TRANGE_CACHE:
        return _CAPTURE_TRANGE_CACHE[capture_dir]
    t_min = float("inf")
    t_max = float("-inf")
    found = False
    if capture_dir.exists():
        for child in capture_dir.iterdir():
            if not child.is_dir():
                continue
            # child 可以是 segment_* 本身, 也可以是 part_* 目录
            candidates: list[Path] = (
                [child] if child.name.startswith("segment_")
                else [s for s in child.iterdir()
                      if s.is_dir() and s.name.startswith("segment_")]
            )
            for seg in candidates:
                r = _seg_time_range(seg)
                if r is not None:
                    t_min = min(t_min, r[0])
                    t_max = max(t_max, r[1])
                    found = True
    result: tuple[float, float] | None = (t_min, t_max) if found else None
    _CAPTURE_TRANGE_CACHE[capture_dir] = result
    return result


# ── GPS 绝对时间对齐辅助 ──────────────────────────────────────────────────────

_STATE_CSV_REL_PATH = Path("nav100_state") / "nav100__state" / "nav100__state.csv"


def _build_capture_gps_map(capture_dir: Path):
    """从 capture 下所有 segment 的 nav100__state.csv 构建 GPS 位置→时间映射.

    扫描 capture_dir/*/segment_* 和 capture_dir/segment_* 下的 CSV,
    拼合成 (lat_arr, lon_arr, rel_time_arr) (均按 rel_time 升序排列).

    缓存至 _CAPTURE_GPS_MAP_CACHE; 不存在 CSV 时返回 None.
    """
    if capture_dir in _CAPTURE_GPS_MAP_CACHE:
        return _CAPTURE_GPS_MAP_CACHE[capture_dir]

    all_lat: list[float] = []
    all_lon: list[float] = []
    all_rel: list[float] = []

    if capture_dir.exists():
        for child in sorted(capture_dir.iterdir(), key=_natural_key):
            if not child.is_dir():
                continue
            candidates: list[Path] = (
                [child] if child.name.startswith("segment_")
                else sorted(
                    (s for s in child.iterdir()
                     if s.is_dir() and s.name.startswith("segment_")),
                    key=_natural_key,
                )
            )
            for seg in candidates:
                csv_path = seg / _STATE_CSV_REL_PATH
                if not csv_path.exists():
                    continue
                try:
                    with open(csv_path, newline="", encoding="utf-8") as fh:
                        rdr = csv.DictReader(fh)
                        for row in rdr:
                            all_lat.append(float(row["latitude"]))
                            all_lon.append(float(row["longitude"]))
                            all_rel.append(float(row["relative_time_sec"]))
                except Exception as exc:
                    logger.debug("GPS map: failed to read %s: %s", csv_path, exc)

    result = None
    if all_lat:
        lat_a = np.asarray(all_lat, dtype=np.float64)
        lon_a = np.asarray(all_lon, dtype=np.float64)
        rel_a = np.asarray(all_rel, dtype=np.float64)
        order = np.argsort(rel_a)
        result = (lat_a[order], lon_a[order], rel_a[order])
        logger.info(
            "GPS map [%s]: %d rows  lat=[%.4f,%.4f]  lon=[%.4f,%.4f]  "
            "rel_t=[%.1f,%.1f]s",
            capture_dir.name, len(rel_a),
            float(lat_a.min()), float(lat_a.max()),
            float(lon_a.min()), float(lon_a.max()),
            float(rel_a.min()), float(rel_a.max()),
        )

    _CAPTURE_GPS_MAP_CACHE[capture_dir] = result
    return result


def _mat_center_latlon(mat_path: Path):
    """从 .mat 提取中心 (mean_lat, mean_lon). 失败返回 (None, None).

    使用与 _load_mmwave_layers 相同的解析逻辑提取 lat/lon.
    结果缓存在 _MAT_RELTIME_CACHE (内存级).
    """
    from scipy.io import loadmat as _loadmat  # 局部导入避免顶层依赖

    _latlon_key = ("__latlon__", mat_path)
    if _latlon_key in _MAT_RELTIME_CACHE:
        return _MAT_RELTIME_CACHE[_latlon_key]

    result = (None, None)
    try:
        mat = _loadmat(mat_path, variable_names=["Data_Ori", "BeamPose"],
                       squeeze_me=False, simplify_cells=False)
        data_ori = mat.get("Data_Ori")
        if data_ori is None or data_ori.size == 0:
            _MAT_RELTIME_CACHE[_latlon_key] = result
            return result

        pose_top = mat.get("BeamPose")
        has_beam_pose = pose_top is not None and pose_top.size > 0
        n_layers = data_ori.shape[0]
        if has_beam_pose:
            n_layers = min(n_layers, pose_top.shape[0])

        all_lat: list[np.ndarray] = []
        all_lon: list[np.ndarray] = []
        for k in range(n_layers):
            try:
                sub = data_ori[k, 0].ravel()
                if has_beam_pose:
                    pose = np.asarray(pose_top[k, 0]).astype(np.float64)
                    lats = pose[:, 2]; lons = pose[:, 3]
                else:
                    # batch_convert_bins: meta 在 sub[4], 列 [0,lat,lon,hdg,alt,0,el]
                    meta = np.asarray(sub[4]).astype(np.float64)
                    if meta.ndim < 2 or meta.shape[1] < 3:
                        continue
                    lats = meta[:, 1]; lons = meta[:, 2]
                valid = (lats != 0.0) | (lons != 0.0)
                if valid.any():
                    all_lat.append(lats[valid])
                    all_lon.append(lons[valid])
            except Exception:
                continue

        if all_lat:
            mean_lat = float(np.concatenate(all_lat).mean())
            mean_lon = float(np.concatenate(all_lon).mean())
            result = (mean_lat, mean_lon)
    except Exception as exc:
        logger.debug("_mat_center_latlon: %s → %s", mat_path.name, exc)

    _MAT_RELTIME_CACHE[_latlon_key] = result
    return result


def _latlon_to_reltime(
    mean_lat: float,
    mean_lon: float,
    gps_map: tuple,
    t_hint: float | None = None,
    t_window: float | None = None,
) -> float | None:
    """在 GPS 轨迹地图上找与 (mean_lat, mean_lon) 最近的点, 返回其 relative_time_sec.

    gps_map = (lat_arr, lon_arr, rel_arr) 均为 np.ndarray.
    近似距离使用平面度量 (精度 < 1km 时已足够).

    t_hint / t_window: 若给定, 仅在 [t_hint-t_window, t_hint+t_window] 时间窗内搜索,
    避免轨迹回环时误匹配到其他时刻的相同位置.
    """
    lat_a, lon_a, rel_a = gps_map
    if t_hint is not None and t_window is not None:
        mask = (rel_a >= t_hint - t_window) & (rel_a <= t_hint + t_window)
        if mask.any():
            lat_a = lat_a[mask]
            lon_a = lon_a[mask]
            rel_a = rel_a[mask]
    cos_lat = float(np.cos(np.deg2rad(mean_lat)))
    dist2 = (lat_a - mean_lat) ** 2 + ((lon_a - mean_lon) * cos_lat) ** 2
    best = int(np.argmin(dist2))
    return float(rel_a[best])


def _load_or_build_mat_times(
    mmw_dir: Path,
    capture_dir: Path,
) -> dict[str, float]:
    """返回 {mat_stem: relative_time_sec} 字典.

    优先从 mmw_dir/.mat_times_cache.json 读取 (上次已构建则即时返回).
    若缓存不存在或不完整, 则对缺失的 mat 加载 lat/lon 并与 GPS 地图匹配,
    匹配完成后将结果写回 JSON 文件供下次使用.

    GPS 地图不可用时返回空 dict (由调用方降级到线性插值).
    """
    import json as _json

    cache_file = mmw_dir / _MAT_TIMES_JSON
    # 读取已有 JSON
    stored: dict[str, float] = {}
    if cache_file.exists():
        try:
            with open(cache_file, encoding="utf-8") as fh:
                stored = _json.load(fh)
        except Exception as exc:
            logger.debug("mat_times cache read failed: %s", exc)
            stored = {}

    # 收集所有 mat 文件
    mats = sorted(
        (f for f in mmw_dir.iterdir() if f.suffix.lower() == ".mat"),
        key=_natural_key,
    )
    if not mats:
        return stored

    missing = [m for m in mats if m.stem not in stored]
    if not missing:
        return stored  # 全部命中缓存

    # 需要 GPS 地图才能计算缺失条目
    gps_map = _build_capture_gps_map(capture_dir)
    if gps_map is None:
        logger.debug("mat_times: GPS map unavailable for %s", capture_dir.name)
        return stored  # 无 GPS 数据, 降级

    logger.info(
        "mat_times: building GPS-based times for %d mat(s) in %s "
        "(first run may take ~%.0fs on network drive) ...",
        len(missing), mmw_dir.name, len(missing) * 0.3,
    )

    # 线性估算作为时间窗口基准 (避免轨迹回环导致的误匹配)
    t_cap = _capture_time_range(capture_dir)
    n_mats_total = len(mats)
    mat_idx_map = {m.stem: i for i, m in enumerate(mats)}

    updated = False
    for mat_path in missing:
        mean_lat, mean_lon = _mat_center_latlon(mat_path)
        if mean_lat is None:
            continue
        # 该 mat 的线性时间估算 (作为搜索窗口中心)
        t_hint: float | None = None
        t_window: float | None = None
        if t_cap is not None and n_mats_total > 0:
            idx = mat_idx_map.get(mat_path.stem, 0)
            t_span = t_cap[1] - t_cap[0]
            t_hint = t_cap[0] + (idx + 0.5) / n_mats_total * t_span
            t_window = max(t_span / n_mats_total * 3, 15.0)  # ±3 mat宽度, 最少15s
        t = _latlon_to_reltime(mean_lat, mean_lon, gps_map,
                               t_hint=t_hint, t_window=t_window)
        if t is not None:
            stored[mat_path.stem] = t
            updated = True

    if updated:
        try:
            with open(cache_file, "w", encoding="utf-8") as fh:
                _json.dump(stored, fh, indent=2)
            logger.info("mat_times: saved cache → %s", cache_file)
        except Exception as exc:
            logger.warning("mat_times: failed to save cache: %s", exc)

    return stored


def _segment_dir(root: Path, seq_id: str) -> Path | None:
    """``seq_id`` 为相对于 root 的路径字符串 → 实际 segment 目录.

    支持 2 层 (``{scene}/{segment}``) 和 4 层
    (``{date}/{capture}/{part}/{segment}``) 两种格式.
    """
    seg_dir = root / Path(*seq_id.split("/"))
    return seg_dir if seg_dir.exists() else None


def _capture_dir(root: Path, seq_id: str) -> Path:
    """从 seq_id 提取 capture 级目录 (含 bin 和 mmwave_mat_1218style 的那层).

    seq_id 可能格式:
      - 4 段: ``{date}/{capture}/{part}/{segment}``  → root/date/capture
      - 3 段: ``{date}/{capture}/{segment}``         → root/date/capture
      - 2 段: ``{capture}/{segment}`` (浅层)         → root/capture
    Capture 级 = 去掉末尾的 segment 部分.
    """
    parts = seq_id.split("/")
    # 末尾通常是 segment_*; 找最后一个非 segment 的祖先即 capture
    while parts and parts[-1].startswith("segment_"):
        parts.pop()
    if not parts:
        return root
    # 4 段或 3 段: 保留前 2 段 (date/capture); 2 段: 保留 1 段 (capture)
    if len(parts) >= 2:
        return root / parts[0] / parts[1]
    return root / parts[0]


def _parse_timestamp(name: str) -> float | None:
    m = _TS_REGEX.search(name)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _nearest_by_timestamp(directory: Path, t_ref: float | None,
                          suffix: str) -> Path | None:
    """在 ``directory`` 中按文件名时间戳取距离 ``t_ref`` 最近的文件.

    ``t_ref`` 为 None 时返回名称排序的第一个匹配文件.
    """
    if not directory.exists():
        return None
    files = [f for f in directory.iterdir()
             if f.is_file() and f.suffix.lower() == suffix]
    if not files:
        return None
    if t_ref is None:
        files.sort(key=_natural_key)
        return files[0]
    best: Path | None = None
    best_dt = float("inf")
    for f in files:
        t = _parse_timestamp(f.stem)
        if t is None:
            continue
        dt = abs(t - t_ref)
        if dt < best_dt:
            best_dt = dt
            best = f
    return best


def _pick_mmwave_mat(mmw_dir: Path, seg_dir: Path, frame_id: str,
                     capture_dir: Path | None = None) -> Path | None:
    """根据 frame_id 的时间戳选取中心时刻最近的 mmwave .mat.

    策略 (优先级从高到低):
      1. W12锚点时间: match_radar_camera_anchor.py 推算所有包的真实时间，
         match_mat_camera.csv 记录每个 MAT 中间包的相机相对时间。
      2. GPS位置匹配: 从 .mat_times_cache.json (或实时构建) 取各 mat 的精确
         relative_time_sec, 找与 frame_id 时间戳最近的 mat.
      3. 线性插值: 利用 capture 全局时间轴线性估算 mat 中心时刻.
      4. 回退: 图像在 segment 中的序号比例.
    """
    mats = sorted(
        [f for f in mmw_dir.iterdir() if f.suffix.lower() == ".mat"],
        key=_natural_key,
    )
    if not mats:
        return None

    n_mats = len(mats)
    if n_mats == 1:
        return mats[0]

    t_frame = _parse_timestamp(frame_id)

    # ── 策略 1: W12 锚点推算的 MAT 中间包真实时间 ─────────────────────────
    if t_frame is not None and capture_dir is not None:
        anchor_pairs = _load_anchor_mat_times(capture_dir)
        valid_pairs = [
            (mat_time, mmw_dir / mat_name)
            for mat_time, mat_name in anchor_pairs
            if (mmw_dir / mat_name).exists()
        ]
        if valid_pairs:
            times = np.asarray(
                [mat_time for mat_time, _ in valid_pairs],
                dtype=np.float64,
            )
            best_i = int(np.argmin(np.abs(times - t_frame)))
            best_mat = valid_pairs[best_i][1]
            logger.info(
                "_pick_mmwave_mat [W12 anchor]: frame t=%.3fs -> %s "
                "(mat center t=%.3fs, dt=%.3fs)",
                t_frame,
                best_mat.name,
                float(times[best_i]),
                abs(float(times[best_i]) - t_frame),
            )
            return best_mat

    # ── 策略 2: GPS 位置匹配 ───────────────────────────────────────────────
    if t_frame is not None and capture_dir is not None:
        mat_times_gps = _load_or_build_mat_times(mmw_dir, capture_dir)
        if mat_times_gps:
            valid_pairs = [
                (mat_times_gps[m.stem], m)
                for m in mats if m.stem in mat_times_gps
            ]
            if valid_pairs:
                ts = np.array([t for t, _ in valid_pairs], dtype=np.float64)
                best_i = int(np.argmin(np.abs(ts - t_frame)))
                best_mat = valid_pairs[best_i][1]
                logger.debug(
                    "_pick_mmwave_mat [GPS]: frame t=%.3fs → %s (t=%.3fs)",
                    t_frame, best_mat.name, float(ts[best_i]),
                )
                return best_mat

    # ── 策略 3: 线性插值 ──────────────────────────────────────────────────
    t_cap: tuple[float, float] | None = None
    if capture_dir is not None:
        t_cap = _capture_time_range(capture_dir)
    if t_cap is None:
        t_cap = _seg_time_range(seg_dir)

    if t_frame is not None and t_cap is not None:
        t_start, t_end = t_cap
        span = t_end - t_start
        if span > 0.1:
            mat_center_times = np.array(
                [t_start + (i + 0.5) / n_mats * span for i in range(n_mats)],
                dtype=np.float64,
            )
            best_i = int(np.argmin(np.abs(mat_center_times - t_frame)))
            logger.debug(
                "_pick_mmwave_mat [linear]: frame t=%.3fs → mat[%d]=%s (t=%.3fs)",
                t_frame, best_i, mats[best_i].name,
                float(mat_center_times[best_i]),
            )
            return mats[best_i]

    # ── 策略 4: 旧序号比例回退 ─────────────────────────────────────────────
    cam_dir = seg_dir / "images" / _CAMERA_DIRS[_PRIMARY_CAMERA_KEY]
    if cam_dir.exists():
        frames = sorted(
            (f.stem for f in cam_dir.iterdir() if f.suffix.lower() == ".jpg"),
            key=_natural_key,
        )
        if frame_id in frames and len(frames) > 1:
            ratio = frames.index(frame_id) / max(len(frames) - 1, 1)
            mat_idx = min(int(round(ratio * (n_mats - 1))), n_mats - 1)
            return mats[mat_idx]
    return mats[0]


def _load_anchor_mat_times(capture_dir: Path) -> list[tuple[float, str]]:
    """Load MAT center times generated from the W12 packet anchor timeline."""
    capture_dir = Path(capture_dir)
    cached = _ANCHOR_MAT_TIME_CACHE.get(capture_dir)
    if cached is not None:
        return cached

    result: list[tuple[float, str]] = []
    csv_path = capture_dir / _ANCHOR_MAT_CSV_NAME
    if csv_path.exists():
        try:
            with open(csv_path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    mat_name = (
                        row.get("mat_name")
                        or row.get("mat_filename")
                        or ""
                    ).strip()
                    raw_time = (
                        row.get("camera_rel_time")
                        or row.get("mat_rel_time_sec")
                        or row.get("nav100_rel_time")
                        or ""
                    ).strip()
                    if not mat_name or not raw_time:
                        continue
                    try:
                        result.append((float(raw_time), mat_name))
                    except ValueError:
                        continue
        except Exception as exc:
            logger.warning("LH: failed to load %s: %s", csv_path, exc)

    result.sort(key=lambda item: item[0])
    _ANCHOR_MAT_TIME_CACHE[capture_dir] = result
    return result


def _build_calibration_from_profile(profile: SensorProfile) -> CalibrationBundle:
    """从 profile 静态字段构造一个最小可用的 CalibrationBundle.

    LH 当前所有 intrinsics / extrinsics 仍为占位 0.0 / 单位阵.  下游若依赖真
    实标定结果, 必须先填充 ``profiles/lh.yaml`` 与 ``lh_calib_overrides.json``.
    """
    bundle = CalibrationBundle()
    for sensor_key, entry in profile.sensors.items():
        # intrinsics
        intr_data = entry.extra.get("intrinsics") or {}
        if entry.type == "camera" and isinstance(intr_data, dict):
            dist_raw = intr_data.get("distortion") or [0.0] * 5
            dist = np.array(dist_raw, dtype=np.float64)
            if dist.size < 5:
                dist = np.pad(dist, (0, 5 - dist.size))
            bundle.intrinsics[sensor_key] = CameraIntrinsics(
                fx=float(intr_data.get("fx", 1.0) or 1.0),
                fy=float(intr_data.get("fy", 1.0) or 1.0),
                cx=float(intr_data.get("cx", 0.0) or 0.0),
                cy=float(intr_data.get("cy", 0.0) or 0.0),
                distortion=dist,
            )
        # extrinsics
        ext_data = entry.extra.get("extrinsics") or {}
        if isinstance(ext_data, dict):
            mat = ext_data.get("matrix")
            if mat is not None:
                arr = np.asarray(mat, dtype=np.float64)
                if arr.size == 16:
                    bundle.extrinsics[sensor_key] = arr.reshape(4, 4)
    return bundle


# ── 雷达目录 / 匹配 JSON ─────────────────────────────────────────────────────

def _find_radar_dir(capture_dir: Path) -> Path | None:
    """在 capture_dir 下找到 `{bin_stem}_radar` 文件夹.

    一个 capture 通常只有一个 bin, 返回第一个匹配的目录; 不存在则返回 None.
    兼容 mmwave_mat_1218style/ 命名（旧格式或本地测试布局）。
    """
    if not capture_dir.exists():
        return None
    for d in capture_dir.iterdir():
        if d.is_dir() and d.name.endswith(_RADAR_SUFFIX):
            return d
    # 兼容回退: mmwave_mat_1218style/ (旧格式/本地测试布局)
    fallback = capture_dir / "mmwave_mat_1218style"
    if fallback.exists() and any(fallback.glob("*.mat")):
        return fallback
    return None


def _load_depth_labels_from_mat(
    fd: "FrameData", mat_path: "Path", capture_dir: "Path",
    frame_id: str = "",
) -> None:
    """加载 depth_labels/{mat_stem}.json 到 fd.meta['depth_label_data'].

    depth_labels/ 位于 capture_dir 下（与 mmwave_mat_1218style/ 或 {bin_stem}_radar/ 同级）。
    文件不存在时静默跳过。
    frame_id: 当前相机帧 stem（不含扩展名），用于校验 depth JSON 中的 camera_name。
    若 camera_name 对应帧与 frame_id 不同，说明 mat 是由最近邻估算匹配到本帧的，
    其 bbox_xyxy 坐标属于另一帧的标注，不应使用，改由 GPS 回退处理。
    """
    depth_json = capture_dir / "depth_labels" / (mat_path.stem + ".json")
    if not depth_json.exists():
        return
    try:
        import json as _j
        data = _j.loads(depth_json.read_text(encoding="utf-8"))
        # 校验 camera_name 是否与当前帧一致（避免最近邻错配导致 bbox 坐标系不匹配）
        if frame_id:
            cam_name = data.get("camera_name", "")
            if cam_name:
                # Path(...).stem 去掉最后一个扩展名（.jpg）→ 与 frame_id 格式相同
                cam_stem = Path(cam_name).stem
                if cam_stem != frame_id:
                    logger.debug(
                        "LH: depth label camera mismatch, skipping: %s != %s",
                        cam_stem, frame_id,
                    )
                    return
        fd.meta["depth_label_data"] = data
        logger.debug("LH: depth label loaded for %s", mat_path.stem)
    except Exception as exc:
        logger.debug("LH: depth label load failed %s: %s", depth_json, exc)


def _load_depth_labels_from_camera(
    fd: "FrameData", frame_id: str, capture_dir: "Path"
) -> None:
    """回退：按相机帧 stem 加载 GPS 射线深度标签（assign_depth_gps.py 输出）.

    文件: depth_labels/{camera_stem}.json
    仅当 fd.meta['depth_label_data'] 为空或 boxes 为空时才加载，避免覆盖更好的数据。
    """
    existing = fd.meta.get("depth_label_data")
    if existing and existing.get("boxes"):
        return   # 已有有效深度数据，不覆盖
    depth_json = capture_dir / "depth_labels" / (frame_id + ".json")
    if not depth_json.exists():
        return
    try:
        import json as _j
        data = _j.loads(depth_json.read_text(encoding="utf-8"))
        fd.meta["depth_label_data"] = data
        logger.debug("LH: GPS depth label loaded for %s", frame_id)
    except Exception as exc:
        logger.debug("LH: GPS depth label load failed %s: %s", depth_json, exc)


def _load_seg_csv_match(seg_dir: Path) -> dict[str, str]:
    """读取 segment 目录下的 radar_camera_match_ts.csv.

    返回 ``{image_stem: mat_filename}`` 映射 (image_stem 不含扩展名).
    优先读取 segment 目录 CSV；缺失时回退到本地缓存 CSV。
    文件不存在或读取失败时返回空 dict, 结果缓存到 _CSV_MATCH_CACHE.
    """
    if seg_dir in _CSV_MATCH_CACHE:
        return _CSV_MATCH_CACHE[seg_dir]
    result: dict[str, str] = {}
    csv_path = seg_dir / _MATCH_CSV_NAME
    cache_path = _local_csv_cache_path(seg_dir)
    chosen_path = csv_path if csv_path.exists() else cache_path
    if chosen_path.exists():
        try:
            with open(chosen_path, newline="", encoding="utf-8") as fh:
                rdr = csv.DictReader(fh)
                for row in rdr:
                    cam_stem = Path(row["camera_filename"]).stem
                    result[cam_stem] = row["mat_filename"]
        except Exception as exc:
            logger.warning("LH: failed to load %s: %s", chosen_path, exc)
    _CSV_MATCH_CACHE[seg_dir] = result
    return result


def _pick_segment_csv_mat(
    mmw_dir: Path,
    seg_dir: Path,
    frame_id: str,
) -> tuple[bool, Path | None, float | None]:
    """Pick the nearest MAT only from the current segment's match CSV."""
    cached = _CSV_MATCH_ROWS_CACHE.get(seg_dir)
    if cached is None:
        csv_path = seg_dir / _MATCH_CSV_NAME
        cache_path = _local_csv_cache_path(seg_dir)
        chosen_path = csv_path if csv_path.exists() else cache_path
        exists = chosen_path.exists()
        rows: list[tuple[float, str]] = []
        if exists:
            try:
                with chosen_path.open(newline="", encoding="utf-8") as handle:
                    for row in csv.DictReader(handle):
                        mat_name = str(row.get("mat_filename", "")).strip()
                        raw_time = str(
                            row.get("camera_rel_time_sec", "")
                        ).strip()
                        if not mat_name or not raw_time:
                            continue
                        rows.append((float(raw_time), mat_name))
            except Exception as exc:
                logger.warning("LH: failed to parse %s: %s", chosen_path, exc)
        cached = (exists, rows)
        _CSV_MATCH_ROWS_CACHE[seg_dir] = cached
    exists, rows = cached
    if not exists or not rows:
        return exists, None, None
    frame_time = _parse_timestamp(frame_id)
    if frame_time is None:
        match_time, mat_name = rows[0]
    else:
        match_time, mat_name = min(
            rows, key=lambda item: abs(item[0] - frame_time)
        )
    path = mmw_dir / mat_name
    return exists, (path if path.exists() else None), float(match_time)


def _load_radar_match(capture_dir: Path) -> dict:
    """读取 capture_dir 下 radar_camera_match.json.

    返回格式:
        { seq_id: { image_stem: mat_name, ... }, ... }
    缺失时返回空 dict.
    """
    if capture_dir in _MATCH_CACHE:
        return _MATCH_CACHE[capture_dir]
    radar_dir = _find_radar_dir(capture_dir)
    result: dict = {}
    if radar_dir is not None:
        match_path = radar_dir / _MATCH_JSON_NAME
        if match_path.exists():
            try:
                import json as _json
                with open(match_path, encoding="utf-8") as fp:
                    result = _json.load(fp)
            except Exception as exc:
                logger.warning("LH: failed to load %s: %s", match_path, exc)
    _MATCH_CACHE[capture_dir] = result
    return result


# ── 标定解析 ─────────────────────────────────────────────────────────────────

def _parse_rightcam_calib(path: Path) -> dict | None:
    """解析 rightcam(1) 文本标定文件 (camera matrix / distortion / rect / proj)."""
    if path in _CALIB_CACHE:
        return _CALIB_CACHE[path]
    if not path.exists():
        return None
    section: str | None = None
    rows: dict[str, list[list[float]]] = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                low = line.lower()
                if low in ("camera matrix", "distortion", "rectification", "projection"):
                    section = low
                    rows[section] = []
                    continue
                if section is None:
                    continue
                try:
                    rows[section].append([float(x) for x in line.split()])
                except ValueError:
                    continue
    except Exception as exc:
        logger.warning("LH: failed to parse %s: %s", path, exc)
        return None

    cm = rows.get("camera matrix") or []
    if len(cm) < 3 or any(len(r) < 3 for r in cm[:3]):
        return None
    dist_rows = rows.get("distortion") or []
    dist = dist_rows[0] if dist_rows else [0.0] * 5
    while len(dist) < 5:
        dist.append(0.0)
    info = {
        "fx": cm[0][0], "fy": cm[1][1],
        "cx": cm[0][2], "cy": cm[1][2],
        "distortion": np.asarray(dist[:5], dtype=np.float64),
    }
    _CALIB_CACHE[path] = info
    return info


def _apply_rightcam_calibration(bundle: CalibrationBundle, root: Path,
                                 profile: SensorProfile | None = None) -> None:
    """套用 rightcam(1) 的实测内参 + 畸变, 并写入 mmwave→相机外参。

    内参/畸变以 ``D:/Dataset/多模态数据库/rightcam(1)`` 文件为准 (实测标定),
    body→camera 旋转假设雷达与相机同位同朝向, 仅坐标系约定不同:
        radar (body):    x=right, y=fwd,  z=up
        camera optical:  x=right, y=down, z=fwd

    架设偏移 (radar原点 → 相机光心) 从 profile.viewer.radar_to_camera_offset_m
    读取 (车体坐标下的 [dx, dy, dz], 米)。该值应从 FC100GAIZHUANG.igs
    (CATIA V5 数模) 量取。公式:  P_cam = R_b→c · (P_radar - offset_b)
    ≡ R · P_radar + (-R · offset_b)。默认 0 保持之前行为。
    """
    # 依次搜索几个候选路径
    _calib_candidates = [
        root / _RIGHTCAM_CALIB_NAME,                        # dataset root 下
        root.parent / _RIGHTCAM_CALIB_NAME,                 # dataset 上级目录
        root / ".." / _RIGHTCAM_CALIB_NAME,                 # 兼容写法
    ]
    info = None
    for _cand in _calib_candidates:
        info = _parse_rightcam_calib(_cand)
        if info is not None:
            logger.info("LH: rightcam(1) loaded from %s", _cand)
            break
    if info is None:
        # 文件均未找到 → profile YAML 中的静态内参已生效, 无需警告
        logger.debug("LH: rightcam(1) not found in any candidate path, using profile intrinsics")
        return
    bundle.intrinsics[_PRIMARY_CAMERA_KEY] = CameraIntrinsics(
        fx=float(info["fx"]), fy=float(info["fy"]),
        cx=float(info["cx"]), cy=float(info["cy"]),
        distortion=info["distortion"].copy(),
    )
    R_body_to_cam = np.array([
        [1.0,  0.0,  0.0],
        [0.0,  0.0, -1.0],
        [0.0,  1.0,  0.0],
    ], dtype=np.float64)
    # 从 YAML 读架设偏移 (radar原点 → 相机光心, 车体坐标米)
    offset_body = np.zeros(3, dtype=np.float64)
    if profile is not None:
        viewer_cfg = getattr(profile, "viewer", None) or {}
        try:
            raw = viewer_cfg.get("radar_to_camera_offset_m")
        except AttributeError:
            raw = None
        if raw is not None:
            arr = np.asarray(raw, dtype=np.float64).ravel()
            if arr.size == 3 and np.all(np.isfinite(arr)):
                offset_body = arr
    # T_body_to_cam: 先平移 (-offset) 再旋转 → t_cam = -R · offset_body
    T_body_to_cam = np.eye(4, dtype=np.float64)
    T_body_to_cam[:3, :3] = R_body_to_cam
    T_body_to_cam[:3, 3] = -R_body_to_cam @ offset_body
    bundle.extrinsics[_PRIMARY_CAMERA_KEY] = T_body_to_cam.copy()
    bundle.extrinsics["radar_mmwave"] = np.eye(4, dtype=np.float64)
    logger.info("LH: real intrinsics  fx=%.1f fy=%.1f cx=%.1f cy=%.1f  dist=%s  "
                "offset_body(radar→cam)=(%.3f,%.3f,%.3f)m  t_cam=(%.3f,%.3f,%.3f)m",
                info["fx"], info["fy"], info["cx"], info["cy"], list(info["distortion"]),
                offset_body[0], offset_body[1], offset_body[2],
                T_body_to_cam[0, 3], T_body_to_cam[1, 3], T_body_to_cam[2, 3])


# ── point cloud / mmwave loader ────────────────────────────────────────────

# OpenCV imread 在 Windows 中文路径下会打开失败。用 np.fromfile + imdecode 避开.
def _imread_unicode(path: Path) -> np.ndarray | None:
    try:
        buf = np.fromfile(str(_long_path(path)), dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def _load_pointcloud(path: Path) -> np.ndarray:
    """Load PCD/BIN/NPY -> Nx{3 or 4} float32."""
    suffix = path.suffix.lower()
    if suffix == ".npy":
        return np.load(str(path))
    if suffix == ".bin":
        pts = np.fromfile(str(path), dtype=np.float32)
        # 试探每点 4 通道; 失败回退 3 通道
        try:
            return pts.reshape(-1, 4)
        except ValueError:
            return pts.reshape(-1, 3)
    if suffix == ".pcd":
        return _read_pcd(path)
    raise ValueError(f"Unsupported point cloud format: {suffix}")


def _read_pcd(path: Path) -> np.ndarray:
    """PCD reader supporting ASCII / binary, mixed field sizes & types.

    Returns Nx4 float32: ``[x, y, z, intensity]`` (intensity = 0 when absent).
    """
    with open(path, "rb") as f:
        fields: list[str] = []
        sizes: list[int] = []
        types: list[str] = []
        counts: list[int] = []
        n_points = 0
        data_type = "ascii"
        while True:
            raw = f.readline()
            if not raw:
                break
            line = raw.decode("ascii", errors="ignore").strip()
            if line.startswith("FIELDS"):
                fields = line.split()[1:]
            elif line.startswith("SIZE"):
                sizes = [int(x) for x in line.split()[1:]]
            elif line.startswith("TYPE"):
                types = line.split()[1:]
            elif line.startswith("COUNT"):
                counts = [int(x) for x in line.split()[1:]]
            elif line.startswith("POINTS"):
                n_points = int(line.split()[-1])
            elif line.startswith("DATA"):
                data_type = line.split()[-1].lower()
                break

        if not fields:
            return np.empty((0, 4), dtype=np.float32)
        if not counts:
            counts = [1] * len(fields)

        if data_type == "ascii":
            rows: list[list[float]] = []
            for _ in range(n_points):
                row = f.readline().decode("ascii", errors="ignore").strip().split()
                if not row:
                    continue
                vals = [float(x) for x in row[: min(4, len(row))]]
                while len(vals) < 4:
                    vals.append(0.0)
                rows.append(vals)
            return (np.array(rows, dtype=np.float32) if rows
                    else np.empty((0, 4), dtype=np.float32))

        # ── binary: 用 numpy structured dtype 逐字段解析 ───────────────────
        type_map = {
            ("F", 4): "<f4", ("F", 8): "<f8",
            ("U", 1): "<u1", ("U", 2): "<u2", ("U", 4): "<u4", ("U", 8): "<u8",
            ("I", 1): "<i1", ("I", 2): "<i2", ("I", 4): "<i4", ("I", 8): "<i8",
        }
        dt_fields: list[tuple] = []
        for i, fname in enumerate(fields):
            t = (types[i] if i < len(types) else "F",
                 sizes[i] if i < len(sizes) else 4)
            np_t = type_map.get(t)
            if np_t is None:
                logger.warning("PCD %s: unknown TYPE/SIZE %s, treating as bytes",
                               path.name, t)
                np_t = f"V{t[1] * counts[i]}"
                dt_fields.append((fname, np_t))
            else:
                cnt = counts[i] if i < len(counts) else 1
                if cnt == 1:
                    dt_fields.append((fname, np_t))
                else:
                    dt_fields.append((fname, np_t, (cnt,)))
        dt = np.dtype(dt_fields)

        raw = f.read(n_points * dt.itemsize)
        if not raw:
            return np.empty((0, 4), dtype=np.float32)
        rec = np.frombuffer(raw, dtype=dt, count=n_points)

        try:
            x = rec["x"].astype(np.float32, copy=False)
            y = rec["y"].astype(np.float32, copy=False)
            z = rec["z"].astype(np.float32, copy=False)
        except ValueError:
            return np.empty((0, 4), dtype=np.float32)
        if "intensity" in rec.dtype.names:
            intensity = rec["intensity"].astype(np.float32, copy=False)
        else:
            intensity = np.zeros_like(x, dtype=np.float32)
        return np.stack([x, y, z, intensity], axis=1)


# ====================================================================
# mmwave .mat (LH 1218style)
#   - Data_Ori: shape (n_el, 1) object;  per-cell raveled = [el_deg(scalar),
#                az_arr(n_az,), ?, sd_dB(n_range, n_az), ...]
#   - BeamPose: shape (n_el, 1) object;  per-cell (n_az, 7) =
#                [az_deg, el_deg, lat, lon, alt, heading_deg, ts_sec]
# 处理与 d:\Dataset\LH_2026-04-27\process_radar_full.py 保持一致:
#   1) 每 (el-layer, az-column) 沿 range 做 1D CA-CFAR (CA-15/2, P_fa=1e-4);
#   2) 每点 R=(r+1)*6.0 m, beam frame: x_right=R·cos(el)·sin(az),
#      y_fwd=R·cos(el)·cos(az), z_up=R·sin(el);
#   3) 多束用参考束(全 mat 中 ts 最小那束) GPS+heading 统一到同一参考帧。
# ====================================================================
_RADAR_RANGE_STEP_M = 6.0          # 单 range bin 对应物理距离 (m)
_RADAR_MAX_RANGE_M = 4000.0
_RADAR_CFAR_TRAIN = 15             # 每侧训练单元
_RADAR_CFAR_GUARD = 2              # 每侧保护单元
_RADAR_CFAR_PFA = 1e-4             # 虚警概率
_RADAR_CFAR_MIN_DB = 20.0          # dB 保底
_RADAR_MAX_POINTS = 20000          # 单帧点数上限 (PyVista 渲染)
_R_EARTH_EQ = 6378137.0
_R_EARTH_POL = 6356752.0


def _cfar_alpha(n_train: int, p_fa: float) -> float:
    return n_train * (p_fa ** (-1.0 / n_train) - 1.0)


# ── 全段点云（公共接口） ──────────────────────────────────────────────────────

def load_segment_all_enu_pts(
    root: Path,
    seq_id: str,
    progress_cb=None,
) -> "tuple[np.ndarray, float, float]":
    """加载 seq_id 对应 segment 所有 mat 文件的 ENU 点云并合并返回.

    Parameters
    ----------
    root        : dataset 根目录
    seq_id      : 序列 ID（与 list_sequences 返回格式相同）
    progress_cb : 可选回调 (done: int, total: int) → None，用于进度通知

    Returns
    -------
    pts         : (N, 4) float32  [lat_deg, lon_deg, U_m, dB]，全段所有 mat 合并
    center_lat  : 全段 GPS 纬度均值
    center_lon  : 全段 GPS 经度均值

    Notes
    -----
    * 每个 mat 单独运行 CFAR + ENU 转换，与单帧加载结果完全一致。
    * 每个 mat 最多保留 _RADAR_MAX_POINTS 个最强点（避免内存爆炸）。
    * 如果 mmwave_mat 目录不存在或 CSV 无匹配则返回空数组。
    """
    seg_dir = _segment_dir(root, seq_id)
    capture_dir = _capture_dir(root, seq_id)
    mmw_dir = _find_radar_dir(capture_dir)
    if mmw_dir is None or not mmw_dir.exists():
        return np.empty((0, 4), dtype=np.float32), 0.0, 0.0

    # 枚举该 segment 对应的所有 mat 文件
    # 策略：先从 radar_camera_match_ts.csv 取（只含该 segment 时间窗口内的 mat），
    # 无 CSV 则枚举 mmw_dir 下全部 mat。
    mat_paths: list[Path] = []

    # 从 per-segment CSV 获取
    if seg_dir is not None:
        csv_match = _load_seg_csv_match(seg_dir)
        mat_names_seen: set[str] = set()
        for mat_name in csv_match.values():
            if mat_name not in mat_names_seen:
                mat_names_seen.add(mat_name)
                cand = mmw_dir / mat_name
                if cand.exists():
                    mat_paths.append(cand)

    # 回退：从 radar_camera_match.json 获取该 segment 的 mat
    if not mat_paths:
        match_json = _load_radar_match(capture_dir)
        if match_json:
            seg_match = match_json.get(seq_id, {})
            mat_names_seen2: set[str] = set()
            for mat_name in seg_match.values():
                if mat_name not in mat_names_seen2:
                    mat_names_seen2.add(mat_name)
                    cand = mmw_dir / mat_name
                    if cand.exists():
                        mat_paths.append(cand)

    # 再回退：枚举 mmw_dir 全部 mat（仅在无 CSV 且无 JSON 时）
    if not mat_paths:
        try:
            mat_paths = sorted(
                [f for f in mmw_dir.iterdir() if f.suffix.lower() == ".mat"],
                key=_natural_key,
            )
        except OSError:
            pass

    if not mat_paths:
        return np.empty((0, 4), dtype=np.float32), 0.0, 0.0

    total = len(mat_paths)
    chunks: list[np.ndarray] = []
    all_lats: list[float] = []
    all_lons: list[float] = []

    for i, mat_path in enumerate(mat_paths):
        try:
            pts, c_lat, c_lon = _load_mmwave_enu_pts(mat_path)
            if len(pts) > 0:
                chunks.append(pts)
                all_lats.append(c_lat)
                all_lons.append(c_lon)
        except Exception as exc:
            logger.debug("load_segment_all_enu_pts: skip %s: %s", mat_path.name, exc)
        if progress_cb is not None:
            try:
                progress_cb(i + 1, total)
            except Exception:
                pass

    if not chunks:
        return np.empty((0, 4), dtype=np.float32), 0.0, 0.0

    merged = np.concatenate(chunks, axis=0)
    center_lat = float(np.mean(all_lats))
    center_lon = float(np.mean(all_lons))
    return merged, center_lat, center_lon


def load_capture_depth_radar_map(
    capture_dir: Path,
    progress_cb=None,
    voxel_xy_m: float = 12.0,
    voxel_z_m: float = 6.0,
    min_mat_support: int = 2,
) -> np.ndarray:
    """Build a persistent GPS radar map from every MAT in one capture.

    Returns ``(N, 5) [lat, lon, altitude, mean_peak_db, mat_support]``.
    A MAT contributes at most once to a voxel, so support measures repeated
    observations rather than raw CFAR point density.
    """
    capture_dir = Path(capture_dir)
    cached = _CAPTURE_DEPTH_MAP_CACHE.get(capture_dir)
    if cached is not None:
        return cached

    radar_dir = _find_radar_dir(capture_dir)
    if radar_dir is None:
        return np.empty((0, 5), dtype=np.float32)
    mat_paths = sorted(radar_dir.glob("*.mat"), key=_natural_key)
    if not mat_paths:
        return np.empty((0, 5), dtype=np.float32)

    signature = "{}:{}:{}".format(
        len(mat_paths),
        max(p.stat().st_mtime_ns for p in mat_paths),
        sum(p.stat().st_size for p in mat_paths),
    )
    project_root = Path(__file__).resolve().parents[3]
    cache_dir = project_root / "temp" / "radar_depth_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    import hashlib
    path_key = hashlib.sha1(
        str(capture_dir.resolve()).encode("utf-8")
    ).hexdigest()[:12]
    cache_name = "{}_{}.npz".format(
        _safe_cache_name(capture_dir.name),
        path_key,
    )
    cache_path = cache_dir / cache_name
    if cache_path.exists():
        try:
            with np.load(cache_path, allow_pickle=False) as data:
                if str(data["signature"].item()) == signature:
                    points = data["points"].astype(np.float32, copy=False)
                    _CAPTURE_DEPTH_MAP_CACHE[capture_dir] = points
                    return points
        except Exception as exc:
            logger.debug("capture depth-map cache read failed: %s", exc)

    origin_lat = origin_lon = None
    per_mat_rows: list[np.ndarray] = []
    total = len(mat_paths)
    for mat_i, mat_path in enumerate(mat_paths):
        try:
            pts, center_lat, center_lon = _load_mmwave_enu_pts(mat_path)
            if origin_lat is None and center_lat and center_lon:
                origin_lat, origin_lon = center_lat, center_lon
            if len(pts) and origin_lat is not None:
                valid = (
                    np.isfinite(pts).all(axis=1)
                    & (pts[:, 2] >= 0.0)
                )
                pts = pts[valid]
                if len(pts):
                    cos_lat = math.cos(math.radians(origin_lat))
                    north = (
                        (pts[:, 0].astype(np.float64) - origin_lat)
                        * math.pi / 180.0 * _R_EARTH_POL
                    )
                    east = (
                        (pts[:, 1].astype(np.float64) - origin_lon)
                        * math.pi / 180.0 * _R_EARTH_EQ * cos_lat
                    )
                    q = np.column_stack([
                        np.floor(east / voxel_xy_m),
                        np.floor(north / voxel_xy_m),
                        np.floor(pts[:, 2] / voxel_z_m),
                    ]).astype(np.int64)
                    # Keep one strongest observation per MAT and voxel.
                    order = np.lexsort((-pts[:, 3], q[:, 2], q[:, 1], q[:, 0]))
                    q_sorted = q[order]
                    first = np.ones(len(order), dtype=bool)
                    first[1:] = np.any(q_sorted[1:] != q_sorted[:-1], axis=1)
                    idx = order[first]
                    per_mat_rows.append(np.column_stack([
                        q[idx],
                        pts[idx, :4],
                    ]))
        except Exception as exc:
            logger.debug("capture depth map: skip %s: %s", mat_path.name, exc)
        if progress_cb is not None:
            try:
                progress_cb(mat_i + 1, total)
            except Exception:
                pass

    if not per_mat_rows:
        return np.empty((0, 5), dtype=np.float32)

    rows = np.concatenate(per_mat_rows, axis=0)
    q = rows[:, :3].astype(np.int64)
    coords = rows[:, 3:6].astype(np.float64)
    strengths = rows[:, 6].astype(np.float64)
    unique_q, inverse = np.unique(q, axis=0, return_inverse=True)
    support = np.bincount(inverse)
    sums = np.zeros((len(unique_q), 4), dtype=np.float64)
    np.add.at(sums[:, :3], inverse, coords)
    np.add.at(sums[:, 3], inverse, strengths)
    keep = support >= max(1, min(min_mat_support, total))
    support_kept = support[keep].astype(np.float64)
    means = sums[keep] / support_kept[:, None]
    points = np.column_stack([means, support_kept]).astype(np.float32)

    try:
        np.savez_compressed(cache_path, points=points, signature=signature)
    except Exception as exc:
        logger.debug("capture depth-map cache write failed: %s", exc)
    _CAPTURE_DEPTH_MAP_CACHE[capture_dir] = points
    logger.info(
        "capture depth radar map: mats=%d persistent_voxels=%d cache=%s",
        total, len(points), cache_path,
    )
    return points


def load_capture_all_enu_pts(
    capture_dir: Path,
    progress_cb=None,
) -> np.ndarray:
    """Load every MAT point in a capture using each point's own GPS position.

    No camera-time matching, shared MAT origin, or cross-MAT persistence filter
    is applied. The returned rows are ``[lat, lon, absolute_altitude, dB]`` and
    are shared by every segment and annotated image in the capture.
    """
    capture_dir = Path(capture_dir)
    cached = _CAPTURE_ALL_POINTS_CACHE.get(capture_dir)
    if cached is not None:
        return cached

    radar_dir = _find_radar_dir(capture_dir)
    mat_paths = (
        sorted(radar_dir.glob("*.mat"), key=_natural_key)
        if radar_dir is not None else []
    )
    if not mat_paths:
        return np.empty((0, 4), dtype=np.float32)

    signature = "{}:{}:{}".format(
        len(mat_paths),
        max(path.stat().st_mtime_ns for path in mat_paths),
        sum(path.stat().st_size for path in mat_paths),
    )
    project_root = Path(__file__).resolve().parents[3]
    cache_dir = project_root / "temp" / "radar_capture_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path_key = hashlib.sha1(
        str(capture_dir.resolve()).encode("utf-8")
    ).hexdigest()[:12]
    cache_path = cache_dir / (
        f"{_safe_cache_name(capture_dir.name)}_{path_key}.npz"
    )
    if cache_path.exists():
        try:
            with np.load(cache_path, allow_pickle=False) as data:
                if str(data["signature"].item()) == signature:
                    points = data["points"].astype(np.float32, copy=False)
                    _CAPTURE_ALL_POINTS_CACHE[capture_dir] = points
                    return points
        except Exception as exc:
            logger.debug("capture point cache read failed: %s", exc)

    chunks = []
    total = len(mat_paths)
    for index, mat_path in enumerate(mat_paths):
        try:
            points, _center_lat, _center_lon = _load_mmwave_enu_pts(mat_path)
            if len(points):
                valid = np.isfinite(points).all(axis=1) & (points[:, 2] >= 0.0)
                if valid.any():
                    chunks.append(points[valid, :4].astype(np.float32, copy=False))
        except Exception as exc:
            logger.debug("capture all-points: skip %s: %s", mat_path.name, exc)
        if progress_cb is not None:
            progress_cb(index + 1, total)

    points = (
        np.concatenate(chunks, axis=0)
        if chunks else np.empty((0, 4), dtype=np.float32)
    )
    try:
        np.savez_compressed(cache_path, points=points, signature=signature)
    except Exception as exc:
        logger.debug("capture point cache write failed: %s", exc)
    _CAPTURE_ALL_POINTS_CACHE[capture_dir] = points
    logger.info(
        "capture GPS point cloud: mats=%d points=%d cache=%s",
        total, len(points), cache_path,
    )
    return points



def _ca_cfar_1d(power_lin: np.ndarray, train: int, guard: int, alpha: float) -> np.ndarray:
    """向量化 CA-CFAR: 返回布尔掩膜 (True = 过阈)."""
    n = power_lin.shape[0]
    half_win = train + guard
    cs = np.concatenate(([0.0], np.cumsum(power_lin, dtype=np.float64)))
    idx = np.arange(n)
    l0 = np.maximum(0, idx - half_win)
    l1 = np.maximum(0, idx - guard)
    r0 = np.minimum(n, idx + guard + 1)
    r1 = np.minimum(n, idx + half_win + 1)
    n_train = (l1 - l0) + (r1 - r0)
    s = (cs[l1] - cs[l0]) + (cs[r1] - cs[r0])
    safe = np.maximum(n_train, 1)
    noise = s / safe
    # n_train==0 退化: 以自身为 noise 不过阈
    noise = np.where(n_train > 0, noise, power_lin)
    return power_lin > (alpha * noise)


def _load_mmwave_mat(path: Path) -> np.ndarray:
    """返回各 el-layer 的功率 cube ``(n_el, n_range, n_az)`` (以主形状裁剪).

    为了保留原有 ``radar_tensors`` 下游调用接口, 给出一个粗略拼接。
    点云转换使用 ``_load_mmwave_pointcloud`` (独立实现).
    """
    layers = _load_mmwave_layers(path)
    if not layers:
        return np.empty((0,), dtype=np.float32)
    from collections import Counter
    shapes = Counter(L["sd"].shape for L in layers)
    target_shape, _ = shapes.most_common(1)[0]
    cube = np.stack([L["sd"] for L in layers if L["sd"].shape == target_shape], axis=0)
    return cube.astype(np.float32, copy=False)


def _load_mmwave_layers(path: Path) -> list[dict]:
    """解析 mat -> per el-layer 列表.

    支持两种 mat 格式:
      1. 标准 1218style: 含 ``BeamPose`` 字段 (n_layers, 1) → (n_az, 7)
         pose 列: [az_deg, el_deg, lat, lon, alt, heading_deg, ts_sec]
      2. batch_convert_bins 生成: 仅含 ``Data_Ori``, pose 嵌在 sub[4] (meta)
         meta 列: [0, lat, lon, heading_deg, alt, 0, el_deg_raw]
         → 自动归一化为与格式1 一致的 pose 布局

    每项 dict: ``{'el_deg': float, 'az': (n_az,), 'sd': (n_range, n_az) dB,
                  'pose': (n_az, 7)  # [az,el,lat,lon,alt,heading,ts]}``.
    """
    path = Path(path)
    cached = _MMWAVE_LAYERS_CACHE.get(path)
    if cached is not None:
        _MMWAVE_LAYERS_CACHE.move_to_end(path)
        return cached
    try:
        import scipy.io as sio
        raw = sio.loadmat(str(path))
    except Exception as exc:
        logger.debug("LH mmwave: loadmat failed for %s: %s", path, exc)
        return []

    do = raw.get("Data_Ori")
    if do is None or do.size == 0:
        return []

    pose_top = raw.get("BeamPose")
    has_beam_pose = pose_top is not None and pose_top.size > 0
    n_layers = do.shape[0]
    if has_beam_pose:
        n_layers = min(n_layers, pose_top.shape[0])

    layers: list[dict] = []
    for k in range(n_layers):
        try:
            sub = do[k, 0].ravel()
            el_deg = float(np.asarray(sub[0]).ravel()[0])
            az = np.asarray(sub[1]).ravel().astype(np.float32)
            sd = np.asarray(sub[3]).astype(np.float32)   # (n_range, n_az) in dB

            if has_beam_pose:
                # 标准 BeamPose: (n_az, 7) = [az,el,lat,lon,alt,hdg,ts]
                pose = np.asarray(pose_top[k, 0]).astype(np.float64)
            else:
                # batch_convert_bins 格式: meta 嵌在 sub[4]
                # meta 列: [0, lat, lon, hdg, alt, 0, el_deg]
                meta = np.asarray(sub[4]).astype(np.float64)  # (n_az, 7)
                n_az = min(az.shape[0], meta.shape[0])
                az = az[:n_az]
                sd = sd[:, :n_az] if sd.ndim == 2 else sd
                pose = np.zeros((n_az, 7), dtype=np.float64)
                pose[:, 0] = az.astype(np.float64)   # az_deg
                pose[:, 1] = el_deg                  # el_deg (同层固定)
                pose[:, 2] = meta[:n_az, 1]          # lat
                pose[:, 3] = meta[:n_az, 2]          # lon
                pose[:, 4] = meta[:n_az, 4]          # alt
                pose[:, 5] = meta[:n_az, 3]          # heading_deg
                pose[:, 6] = 0.0                     # ts (此格式无时间戳)

            if sd.size == 0 or az.size == 0 or pose.shape[0] == 0:
                continue
            layers.append({"el_deg": el_deg, "az": az, "sd": sd, "pose": pose})
        except Exception:
            continue
    _MMWAVE_LAYERS_CACHE[path] = layers
    _MMWAVE_LAYERS_CACHE.move_to_end(path)
    while len(_MMWAVE_LAYERS_CACHE) > 4:
        _MMWAVE_LAYERS_CACHE.popitem(last=False)
    return layers


def _load_mmwave_pointcloud(path: Path) -> tuple[np.ndarray, float]:
    """CA-CFAR + GPS 统一 生成 Nx4 点云 ``[x_right, y_fwd, z_up, power_dB]``.

    返回 ``(pts, hdg0_deg)`` 其中 ``hdg0_deg`` 是参考束的 GPS 航向角 (°, 北起顺时针),
    用于后续航向修正。
    """
    layers = _load_mmwave_layers(path)
    if not layers:
        return np.empty((0, 4), dtype=np.float32), 0.0

    # 参考束: 全 mat 中 ts 最小的那束
    all_ts = np.concatenate([L["pose"][:, 6] for L in layers])
    all_lat = np.concatenate([L["pose"][:, 2] for L in layers])
    all_lon = np.concatenate([L["pose"][:, 3] for L in layers])
    all_alt = np.concatenate([L["pose"][:, 4] for L in layers])
    all_hdg = np.concatenate([L["pose"][:, 5] for L in layers])
    ref = int(np.argmin(all_ts))
    lat0, lon0, alt0, hdg0 = (
        float(all_lat[ref]), float(all_lon[ref]),
        float(all_alt[ref]), float(all_hdg[ref]),
    )
    h0 = np.deg2rad(hdg0)
    cos_h0, sin_h0 = float(np.cos(h0)), float(np.sin(h0))
    coslat0 = float(np.cos(np.deg2rad(lat0)))

    n_train_total = _RADAR_CFAR_TRAIN * 2
    alpha = _cfar_alpha(n_train_total, _RADAR_CFAR_PFA)

    pts_chunks: list[np.ndarray] = []
    for L in layers:
        el_deg = L["el_deg"]
        az_arr = L["az"]
        sd = L["sd"]
        pose = L["pose"]
        n_range, n_az = sd.shape
        if pose.shape[0] < n_az:
            n_az = pose.shape[0]
            sd = sd[:, :n_az]
            az_arr = az_arr[:n_az]
        rng_m = (np.arange(1, n_range + 1, dtype=np.float32)) * _RADAR_RANGE_STEP_M
        in_range = rng_m < _RADAR_MAX_RANGE_M
        sd_lin = np.power(10.0, sd / 10.0).astype(np.float64)
        for j in range(n_az):
            col_lin = sd_lin[:, j]
            mask = _ca_cfar_1d(col_lin, _RADAR_CFAR_TRAIN, _RADAR_CFAR_GUARD, alpha)
            mask &= sd[:, j] > _RADAR_CFAR_MIN_DB
            mask &= in_range
            if not mask.any():
                continue
            ri = np.where(mask)[0]
            R = rng_m[ri]
            az_rad = np.deg2rad(float(az_arr[j]))
            el_rad = np.deg2rad(el_deg)
            ce, se = float(np.cos(el_rad)), float(np.sin(el_rad))
            ca, sa = float(np.cos(az_rad)), float(np.sin(az_rad))
            xb = R * ce * sa
            yb = R * ce * ca
            zb = R * se
            # 该束 GPS 位姿
            lat_b = float(pose[j, 2]); lon_b = float(pose[j, 3])
            alt_b = float(pose[j, 4]); hdg_b = float(pose[j, 5])
            dE = (lon_b - lon0) * np.deg2rad(1.0) * _R_EARTH_EQ * coslat0
            dN = (lat_b - lat0) * np.deg2rad(1.0) * _R_EARTH_POL
            dU = alt_b - alt0
            h = np.deg2rad(hdg_b)
            cos_h, sin_h = float(np.cos(h)), float(np.sin(h))
            # 束体系 -> ENU (yaw = heading from north, clockwise)
            E = dE + xb * cos_h + yb * sin_h
            N = dN - xb * sin_h + yb * cos_h
            U = dU + zb
            # ENU -> 参考束体系 (仍是 x_right, y_fwd, z_up)
            xr = E * cos_h0 - N * sin_h0
            yr = E * sin_h0 + N * cos_h0
            zr = U
            # 输出坐标系: 参考束体系 (x_right, y_fwd, z_up), 已含 GPS 位移修正
            x_out = xr.astype(np.float32)
            y_out = yr.astype(np.float32)
            z_out = zr.astype(np.float32)
            inten = sd[ri, j].astype(np.float32)
            pts_chunks.append(np.stack([x_out, y_out, z_out, inten], axis=1))

    if not pts_chunks:
        logger.warning("_load_mmwave_pointcloud: 无 CFAR 检测点 (mat=%s, layers=%d, "
                       "hdg0=%.1f°). 检查 min_db 阈值和实际信号强度.",
                       path.name, len(layers), hdg0)
        return np.empty((0, 4), dtype=np.float32), hdg0
    out = np.concatenate(pts_chunks, axis=0)
    db_min = float(out[:, 3].min()); db_max = float(out[:, 3].max())
    logger.info("_load_mmwave_pointcloud: mat=%s  layers=%d  pts=%d  "
                "hdg0=%.1f°  dB=[%.1f, %.1f]  range=[%.0f, %.0f]m",
                path.name, len(layers), len(out), hdg0, db_min, db_max,
                float(np.linalg.norm(out[:, :3], axis=1).min()),
                float(np.linalg.norm(out[:, :3], axis=1).max()))
    if out.shape[0] > _RADAR_MAX_POINTS:
        # 按 power 阈选高强度 (避免均匀采样丢远点)
        idx = np.argpartition(out[:, 3], -_RADAR_MAX_POINTS)[-_RADAR_MAX_POINTS:]
        out = out[idx]
    return out, hdg0
