"""
assign_depth_from_db.py  —  Step 3：基于 GPS 目标数据库全量赋值深度

原理
----
  利用 target_depth_db.json 中存储的目标 GPS 坐标，对任意帧做纯几何深度计算：
      depth_m = haversine(vehicle_GPS, target_GPS)
  不依赖雷达、不依赖相机内外参，仅需 GPS。

  匹配策略（无可靠 FOV 时）：
  1. 对同标签的所有数据库目标，计算从当前车辆位置看去的期望方位角
         expected_az = bearing(vehicle, target) - vehicle_heading  （相机坐标系，右为正）
  2. 对图像中每个标注框，估算粗略方位角
         az_box ≈ (u_center / img_w - 0.5) × FOV_APPROX  （±FOV/2 映射到 ±img_w/2）
  3. 角度差 |expected_az - az_box| < AZ_MATCH_DEG 时视为候选
  4. 同一帧内同标签多目标 → 按水平位置顺序（左→右）一对一匹配

输入
----
  {capture_dir}/target_depth_db.json
  nav100__fix.csv / nav100__heading.csv
  annot_root/*.json   —— LabelMe 标注文件（人工 or autofill）

输出
----
  {capture_dir}/depth_labels/{mat_stem}.json
  与 assign_depth_azimuth.py 格式完全一致，method 字段为 "gps_db"

用法
----
  # 单个 capture（LH 数据集）
  python tools/assign_depth_from_db.py \\
      --capture-dir "L:/LH_data_all_sensor/4_29/with_cameras_capture_20260429_164703" \\
      --annot-root  "L:/LH_data_all_sensor_annotations"

  # 全量
  python tools/assign_depth_from_db.py --all \\
      --annot-root "L:/LH_data_all_sensor_annotations"

  # 也处理自动标注
  python tools/assign_depth_from_db.py --all \\
      --annot-root "L:/LH_data_all_sensor_annotations_autofill"
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

# ── 常量 ─────────────────────────────────────────────────────────────────────

FOV_APPROX_DEG  = 8.8    # 精确相机水平 FOV（°），fx=12503.99, w=1920 计算结果
AZ_MATCH_DEG    = 12.0   # 方位角匹配阈值（°）：±5° 振动 + ±7° FOV误差
MIN_DEPTH_M     = 50.0
MAX_DEPTH_M     = 5000.0
DB_FILENAME     = "target_depth_db.json"
MARKER_NAME     = ".db_applied"        # 标记文件，表示已执行本脚本
ALGORITHM_VERSION = 2
CAM_SUBDIR      = "hikrobot_camera__DA8679037__image_raw"
YAW_SEARCH_DEG  = 5.0    # 搜索窗半宽（°），外参已知 camera_z=body_y，只吸收安装公差
YAW_STEP_DEG    = 0.5
CAMERA_YAW_OFFSET_INIT_DEG = 0.0  # 外参标定:camera_z=body_z, 偏航≈0°
CAMERA_YAW_SEARCH_FIRST_FRAME_DEG = 30.0  # 首帧或重定位搜索范围，一般不会超过±30°
TEMPORAL_MAX_DX = 0.22

_RE_CAM_T = re.compile(r'_t([\d.]+)\.jpg$')
_RE_FZ    = re.compile(r'_FZ(\d+)-(\d+)\.mat$', re.IGNORECASE)


# ── GPS 几何（与 build_target_db 一致）──────────────────────────────────────

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(max(0.0, min(1.0, a))))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lr1 = math.radians(lat1)
    lr2 = math.radians(lat2)
    dl  = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(lr2)
    x = math.cos(lr1) * math.sin(lr2) - math.sin(lr1) * math.cos(lr2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _az_diff(a: float, b: float) -> float:
    """规范化方位角差到 (-180, 180]。"""
    d = (a - b + 180.0) % 360.0 - 180.0
    return d


def _canonical_label(label: str) -> str:
    """Collapse annotation aliases so manual map targets match LabelMe labels."""
    text = re.sub(r"[\s_\-]+", " ", str(label).strip().lower())
    if any(k in text for k in ("building", "建筑", "楼", "房屋")):
        return "building"
    if any(k in text for k in ("tower", "铁塔", "电塔", "杆塔", "signal")):
        return "tower"
    return text


def _box_center_x(box: dict) -> float:
    x0, _y0, x1, _y1 = box["bbox_xyxy"]
    return (float(x0) + float(x1)) * 0.5 / max(float(box.get("img_w", 1)), 1.0)


@dataclass
class TemporalMatchState:
    """Small per-sequence state; target GPS remains the source of depth truth."""

    yaw_offset_deg: float = 0.0
    previous: list[dict] = field(default_factory=list)
    frame_time: float | None = None


def _temporal_target_hint(
    box: dict,
    state: TemporalMatchState | None,
    target_rows: list[dict] | None = None,
    fov_deg: float = FOV_APPROX_DEG,
) -> str | None:
    if state is None or not state.previous:
        return None
    label = _canonical_label(box["label"])
    cx = _box_center_x(box)
    row_by_id = {
        row["target"]["id"]: row for row in (target_rows or [])
    }
    candidates = []
    for previous in state.previous:
        if previous["label"] != label:
            continue
        predicted_cx = previous["cx"]
        row = row_by_id.get(previous["target_id"])
        previous_az = previous.get("target_az_deg")
        if row is not None and isinstance(previous_az, (int, float)):
            predicted_cx += _az_diff(
                row["az_deg"], float(previous_az)
            ) / max(float(fov_deg), 1e-6)
        error = abs(predicted_cx - cx)
        if error <= TEMPORAL_MAX_DX:
            candidates.append((error, previous))
    if not candidates:
        return None
    return min(candidates, key=lambda item: item[0])[1]["target_id"]


def _estimate_yaw_offset(
    boxes: list[dict],
    target_rows: list[dict],
    state: TemporalMatchState | None,
    fov_deg: float,
    az_thresh: float,
) -> float:
    """Estimate frame-wide camera yaw without using camera extrinsics.

    Each physical map target may explain at most one box in a frame. Temporal
    target hints break ties when several map targets have similar bearings.
    """
    if not boxes or not target_rows:
        return state.yaw_offset_deg if state else 0.0

    center = state.yaw_offset_deg if state else 0.0
    tower_box_count = sum(
        _canonical_label(box["label"]) == "tower" for box in boxes
    )
    tower_target_count = sum(
        row["canonical_label"] == "tower" for row in target_rows
    )
    independent_tower_relocalization = (
        tower_box_count >= 2 and tower_target_count >= 2
    )
    if state is None or not state.previous or independent_tower_relocalization:
        # Extrinsics: body→camera R = [[1,0,0],[0,0,-1],[0,1,0]]
        #   camera_z = body_y (forward), so camera yaw ≈ body heading.
        # A ±30° search absorbs mounting tolerances + GPS heading drift.
        offsets = np.arange(
            -CAMERA_YAW_SEARCH_FIRST_FRAME_DEG,
            CAMERA_YAW_SEARCH_FIRST_FRAME_DEG + YAW_STEP_DEG,
            YAW_STEP_DEG,
        )
    else:
        offsets = np.arange(
            center - YAW_SEARCH_DEG,
            center + YAW_SEARCH_DEG + YAW_STEP_DEG,
            YAW_STEP_DEG,
        )
    best_offset = center
    best_score = -float("inf")
    relative_rank: dict[int, float] = {}
    target_rank: dict[int, float] = {}
    for label in {_canonical_label(box["label"]) for box in boxes}:
        box_ids = [
            i for i, box in enumerate(boxes)
            if _canonical_label(box["label"]) == label
            and isinstance(box.get("relative_depth_score"), (int, float))
        ]
        row_ids = [
            i for i, row in enumerate(target_rows)
            if row["canonical_label"] == label
        ]
        if len(box_ids) >= 2 and len(row_ids) >= 2:
            for rank, box_i in enumerate(sorted(
                box_ids,
                key=lambda i: float(boxes[i]["relative_depth_score"]),
                reverse=True,
            )):
                relative_rank[box_i] = rank / max(len(box_ids) - 1, 1)
            for rank, row_i in enumerate(sorted(
                row_ids, key=lambda i: target_rows[i]["distance_m"]
            )):
                target_rank[row_i] = rank / max(len(row_ids) - 1, 1)

    for offset in offsets:
        score = -0.01 * abs(offset - center)
        pair_scores = []
        for box_i, box in enumerate(boxes):
            label = _canonical_label(box["label"])
            az_box = (_box_center_x(box) - 0.5) * fov_deg + offset
            hint = (
                None
                if label == "tower" and tower_box_count >= 2
                else _temporal_target_hint(
                    box, state, target_rows=target_rows, fov_deg=fov_deg
                )
            )
            for row_i, row in enumerate(target_rows):
                if row["canonical_label"] != label:
                    continue
                diff = abs(_az_diff(row["az_deg"], az_box))
                s = math.exp(-0.5 * (diff / max(az_thresh, 1.0)) ** 2)
                if hint and hint == row["target"]["id"]:
                    # Once two towers have established their identities, a
                    # single remaining tower must not jump to the other map
                    # target just because unstable camera yaw fits it better.
                    s += 2.0 if tower_box_count == 1 else 0.8
                if box_i in relative_rank and row_i in target_rank:
                    s -= 0.6 * abs(
                        relative_rank[box_i] - target_rank[row_i]
                    )
                pair_scores.append((s, box_i, row_i))
        used_boxes, used_rows = set(), set()
        for pair_score, box_i, row_i in sorted(pair_scores, reverse=True):
            if box_i in used_boxes or row_i in used_rows:
                continue
            used_boxes.add(box_i)
            used_rows.add(row_i)
            score += pair_score
        if score > best_score:
            best_score = score
            best_offset = float(offset)

    if state is None or not state.previous or independent_tower_relocalization:
        return best_offset
    return 0.65 * state.yaw_offset_deg + 0.35 * best_offset


# ── nav100 加载（与 build_target_db 一致）────────────────────────────────────

def load_capture_nav(cap_dir: Path):
    ts_all, lat_all, lon_all = [], [], []
    ts_h_all, hdg_all = [], []
    for part_dir in sorted(cap_dir.iterdir()):
        if not part_dir.is_dir() or '_part' not in part_dir.name:
            continue
        for seg_dir in sorted(part_dir.iterdir()):
            if not seg_dir.is_dir() or not seg_dir.name.startswith('segment_'):
                continue
            gps_csv = seg_dir / 'gps'     / 'nav100__fix'     / 'nav100__fix.csv'
            hdg_csv = seg_dir / 'heading' / 'nav100__heading' / 'nav100__heading.csv'
            if gps_csv.exists():
                try:
                    with open(gps_csv, newline='', encoding='utf-8') as fh:
                        for row in csv.DictReader(fh):
                            ts_all.append(float(row['relative_time_sec']))
                            lat_all.append(float(row['latitude']))
                            lon_all.append(float(row['longitude']))
                except Exception:
                    pass
            if hdg_csv.exists():
                try:
                    with open(hdg_csv, newline='', encoding='utf-8') as fh:
                        for row in csv.DictReader(fh):
                            ts_h_all.append(float(row['relative_time_sec']))
                            hdg_all.append(float(row['value']))
                except Exception:
                    pass

    ts  = np.asarray(ts_all,  dtype=np.float64)
    lat = np.asarray(lat_all, dtype=np.float64)
    lon = np.asarray(lon_all, dtype=np.float64)
    ts_h = np.asarray(ts_h_all, dtype=np.float64)
    hdg  = np.asarray(hdg_all,  dtype=np.float64)
    if len(ts) > 0:
        o = np.argsort(ts);  ts, lat, lon = ts[o], lat[o], lon[o]
    if len(ts_h) > 0:
        o = np.argsort(ts_h);  ts_h, hdg = ts_h[o], hdg[o]
    return ts, lat, lon, ts_h, hdg


# ── LabelMe 标注加载 ──────────────────────────────────────────────────────────

def find_annot_json(camera_name: str, annot_root: Path) -> Path | None:
    """在 annot_root 下搜索与 camera_name 对应的 LabelMe JSON。"""
    stem = Path(camera_name).stem
    candidates = [
        annot_root / f"{stem}.json",
        annot_root / CAM_SUBDIR / f"{stem}.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def load_labelme_boxes(json_path: Path) -> tuple[list[dict], int, int]:
    """解析 LabelMe JSON，返回 (boxes, img_w, img_h)。"""
    with open(json_path, encoding='utf-8') as f:
        data = json.load(f)
    img_w = data.get("imageWidth", 1920)
    img_h = data.get("imageHeight", 1200)
    boxes = []
    for shape in data.get("shapes", []):
        pts   = shape.get("points", [])
        stype = shape.get("shape_type", "rectangle")
        if stype not in ("rectangle", "polygon") or len(pts) < 2:
            continue
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        boxes.append({
            "label":     shape.get("label", ""),
            "bbox_xyxy": [min(xs), min(ys), max(xs), max(ys)],
            "img_w":     img_w,
            "img_h":     img_h,
        })
    return boxes, img_w, img_h


# ── 核心匹配 ──────────────────────────────────────────────────────────────────

def _match_boxes_to_targets(
    boxes:    list[dict],
    targets:  list[dict],
    v_lat:    float,
    v_lon:    float,
    v_hdg:    float,
    fov_deg:  float = FOV_APPROX_DEG,
    az_thresh: float = AZ_MATCH_DEG,
    state: TemporalMatchState | None = None,
    frame_time: float | None = None,
) -> list[dict]:
    """
    将标注框列表与数据库目标列表进行匹配，返回带 depth_m 的框列表。

    匹配策略（无可靠 FOV 时的宽容方案）：
      • 对每个 (box_label, target_label) 相同的组合，计算目标期望方位角
      • 利用框的水平位置（u_center）与期望方位角的相对顺序进行一对一匹配
      • 方位角阈值 az_thresh 宽松（±12°），容许无人机振动误差
    """
    active_state = state
    if (
        state is not None
        and frame_time is not None
        and state.frame_time is not None
        and (frame_time <= state.frame_time or frame_time - state.frame_time > 3.0)
    ):
        active_state = TemporalMatchState(yaw_offset_deg=state.yaw_offset_deg)

    target_rows = []
    for target in targets:
        dist = haversine(v_lat, v_lon, target["lat"], target["lon"])
        if not (MIN_DEPTH_M <= dist <= MAX_DEPTH_M):
            continue
        target_rows.append({
            "target": target,
            "canonical_label": _canonical_label(target.get("label", "")),
            "az_deg": _az_diff(
                bearing(v_lat, v_lon, target["lat"], target["lon"]), v_hdg
            ),
            "distance_m": dist + float(target.get("depth_offset_m", 0.0)),
            "map_distance_m": dist,
        })

    yaw_offset = _estimate_yaw_offset(
        boxes, target_rows, active_state, fov_deg=fov_deg, az_thresh=az_thresh
    )
    tower_box_count = sum(
        _canonical_label(box["label"]) == "tower" for box in boxes
    )
    relative_rank: dict[int, float] = {}
    target_rank: dict[int, float] = {}
    for label in {_canonical_label(box["label"]) for box in boxes}:
        box_ids = [
            i for i, box in enumerate(boxes)
            if _canonical_label(box["label"]) == label
            and isinstance(box.get("relative_depth_score"), (int, float))
        ]
        row_ids = [
            i for i, row in enumerate(target_rows)
            if row["canonical_label"] == label
        ]
        if len(box_ids) >= 2 and len(row_ids) >= 2:
            for rank, box_i in enumerate(sorted(
                box_ids,
                key=lambda i: float(boxes[i]["relative_depth_score"]),
                reverse=True,
            )):
                relative_rank[box_i] = rank / max(len(box_ids) - 1, 1)
            for rank, row_i in enumerate(sorted(
                row_ids, key=lambda i: target_rows[i]["distance_m"]
            )):
                target_rank[row_i] = rank / max(len(row_ids) - 1, 1)
    result = [None] * len(boxes)
    next_previous = []

    pair_costs = []
    for box_i, box in enumerate(boxes):
        label = _canonical_label(box["label"])
        az_box = (_box_center_x(box) - 0.5) * fov_deg + yaw_offset
        hint = (
            None
            if label == "tower" and tower_box_count >= 2
            else _temporal_target_hint(
                box, active_state, target_rows=target_rows, fov_deg=fov_deg
            )
        )
        for row_i, row in enumerate(target_rows):
            if row["canonical_label"] != label:
                continue
            diff = abs(_az_diff(row["az_deg"], az_box))
            cost = diff
            if hint and hint == row["target"]["id"]:
                temporal_weight = 1.5 if tower_box_count == 1 else 0.75
                cost -= min(az_thresh * temporal_weight, 8.0)
            if box_i in relative_rank and row_i in target_rank:
                cost += az_thresh * abs(
                    relative_rank[box_i] - target_rank[row_i]
                )
            pair_costs.append((cost, diff, box_i, row_i, az_box, hint))

    used_boxes, used_rows = set(), set()
    for _cost, raw_diff, box_i, row_i, az_box, hint in sorted(pair_costs):
        if box_i in used_boxes or row_i in used_rows:
            continue
        if raw_diff > az_thresh * 2.0:
            continue
        used_boxes.add(box_i)
        used_rows.add(row_i)
        box = boxes[box_i]
        best = target_rows[row_i]
        raw_diff = abs(_az_diff(best["az_deg"], az_box))
        target = best["target"]
        angular_conf = math.exp(-0.5 * (raw_diff / max(az_thresh, 1.0)) ** 2)
        temporal_bonus = 0.1 if hint == target["id"] else 0.0
        confidence = min(
            1.0,
            0.65 * float(target.get("confidence", 0.5))
            + 0.35 * angular_conf
            + temporal_bonus,
        )
        result[box_i] = {
            **box,
            "depth_m": round(best["distance_m"], 1),
            "az_box_deg": round(az_box, 2),
            "camera_yaw_offset_deg": round(yaw_offset, 2),
            "method": "gps_db_temporal",
            "target_id": target["id"],
            "az_diff_deg": round(raw_diff, 1),
            "confidence": round(confidence, 3),
            "map_distance_m": round(best["map_distance_m"], 1),
            "depth_offset_m": round(float(target.get("depth_offset_m", 0.0)), 1),
        }
        next_previous.append({
            "label": _canonical_label(box["label"]),
            "cx": _box_center_x(box),
            "target_id": target["id"],
            "target_az_deg": best["az_deg"],
        })

    for box_i, box in enumerate(boxes):
        if result[box_i] is not None:
            continue
        label = _canonical_label(box["label"])
        label_rows = [
            row for row in target_rows if row["canonical_label"] == label
        ]
        # Several building boxes may describe parts of one physical complex.
        # Point-like tower targets remain strictly one-to-one.
        if label != "tower" and label_rows:
            az_box = (_box_center_x(box) - 0.5) * fov_deg + yaw_offset
            hint = _temporal_target_hint(
                box, active_state, target_rows=target_rows, fov_deg=fov_deg
            )
            best = min(
                label_rows,
                key=lambda row: (
                    abs(_az_diff(row["az_deg"], az_box))
                    - (min(az_thresh * 0.75, 6.0)
                       if hint == row["target"]["id"] else 0.0)
                ),
            )
            raw_diff = abs(_az_diff(best["az_deg"], az_box))
            if raw_diff <= az_thresh * 2.0:
                target = best["target"]
                angular_conf = math.exp(
                    -0.5 * (raw_diff / max(az_thresh, 1.0)) ** 2
                )
                result[box_i] = {
                    **box,
                    "depth_m": round(best["distance_m"], 1),
                    "az_box_deg": round(az_box, 2),
                    "camera_yaw_offset_deg": round(yaw_offset, 2),
                    "method": "gps_db_temporal",
                    "target_id": target["id"],
                    "az_diff_deg": round(raw_diff, 1),
                    "confidence": round(min(
                        1.0,
                        0.65 * float(target.get("confidence", 0.5))
                        + 0.35 * angular_conf
                        + (0.1 if hint == target["id"] else 0.0),
                    ), 3),
                    "map_distance_m": round(best["map_distance_m"], 1),
                    "depth_offset_m": round(
                        float(target.get("depth_offset_m", 0.0)), 1
                    ),
                }
                next_previous.append({
                    "label": label,
                    "cx": _box_center_x(box),
                    "target_id": target["id"],
                    "target_az_deg": best["az_deg"],
                })
                continue
        result[box_i] = {
            **box,
            "depth_m": None,
            "method": "unmatched_map_target" if label_rows else "no_db_target",
        }

    if state is not None:
        state.yaw_offset_deg = yaw_offset
        state.previous = next_previous
        state.frame_time = frame_time
    return result


# ── 处理单帧 ─────────────────────────────────────────────────────────────────

def process_one_frame(
    camera_name: str,
    mat_stem:    str | None,
    annot_root:  Path,
    targets:     list[dict],
    out_dir:     Path,
    ts_gps:      np.ndarray,
    lat_arr:     np.ndarray,
    lon_arr:     np.ndarray,
    ts_hdg:      np.ndarray,
    hdg_arr:     np.ndarray,
    overwrite:   bool = False,
    state:       TemporalMatchState | None = None,
    annot_path:  Path | None = None,
) -> bool:
    """处理单个相机帧，赋值深度并写出 JSON。返回 True 表示成功写出。"""
    # 输出文件名（与 assign_depth_azimuth 保持一致，用 mat_stem）
    out_stem = mat_stem if mat_stem else Path(camera_name).stem
    out_path = out_dir / f"{out_stem}.json"

    if out_path.exists() and not overwrite:
        # Only skip results produced by this algorithm version or newer.
        try:
            with open(out_path, encoding='utf-8') as f:
                existing = json.load(f)
            if int(existing.get("depth_assignment_version", 0)) >= ALGORITHM_VERSION:
                return False
        except Exception:
            pass

    # 找标注 JSON
    annot_path = annot_path or find_annot_json(camera_name, annot_root)
    if annot_path is None:
        return False

    boxes, img_w, img_h = load_labelme_boxes(annot_path)
    if not boxes:
        return False

    # 解析相机帧时间
    m = _RE_CAM_T.search(camera_name)
    t_ref = float(m.group(1)) if m else float(ts_gps[0])

    v_lat = float(np.interp(t_ref, ts_gps, lat_arr))
    v_lon = float(np.interp(t_ref, ts_gps, lon_arr))
    if len(ts_hdg) > 0:
        unwrapped_hdg = np.unwrap(np.deg2rad(hdg_arr))
        v_hdg = float(np.rad2deg(np.interp(t_ref, ts_hdg, unwrapped_hdg)) % 360.0)
    else:
        v_hdg = 0.0

    matched_boxes = _match_boxes_to_targets(
        boxes, targets, v_lat, v_lon, v_hdg, state=state,
        frame_time=t_ref,
    )

    # 统计
    n_depth = sum(1 for b in matched_boxes if b.get("depth_m") is not None)
    if n_depth == 0:
        return False

    # 读取已有 JSON（若存在），合并：gps_db 赋值覆盖旧的 None；不覆盖雷达结果
    if out_path.exists():
        try:
            with open(out_path, encoding='utf-8') as f:
                existing_data = json.load(f)
        except Exception:
            existing_data = {}
    else:
        existing_data = {}

    # 构建输出 boxes（保留雷达结果，补充 GPS 结果）
    out_boxes = []
    for b in matched_boxes:
        dm = b.get("depth_m")
        out_boxes.append({
            "label":      b["label"],
            "bbox_xyxy":  b["bbox_xyxy"],
            "az_box_deg": b.get("az_box_deg", 0.0),
            "depth_m":    dm,
            "confidence": b.get("confidence", 0.0),
            "method":     b.get("method", "gps_db"),
            "target_id":  b.get("target_id", ""),
            "az_diff_deg": b.get("az_diff_deg"),
            "camera_yaw_offset_deg": b.get("camera_yaw_offset_deg"),
        })

    out_data = {
        **existing_data,
        "camera_name": camera_name,
        "mat_name":    (mat_stem + ".mat") if mat_stem else "",
        "boxes":       out_boxes,
        "fov_deg":     FOV_APPROX_DEG,
        "_db_applied": True,
        "depth_assignment_version": ALGORITHM_VERSION,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out_data, f, ensure_ascii=False, indent=2)
    return True


# ── 处理单个 capture ─────────────────────────────────────────────────────────

def process_capture(
    cap_dir:    Path,
    annot_root: Path,
    overwrite:  bool = False,
    verbose:    bool = True,
) -> int:
    """
    对一个 capture 目录全量赋值深度。

    参数
    ----
    cap_dir:    capture 根目录（含 target_depth_db.json 和 depth_labels/）
    annot_root: LabelMe 标注根目录（人工或 autofill，同一次只传一个）
    overwrite:  True = 强制覆盖已有深度结果
    verbose:    是否打印进度

    返回成功写出的 JSON 数量。
    """
    db_path = cap_dir / DB_FILENAME
    if not db_path.exists():
        if verbose:
            print(f"  ⚠ 缺少 {DB_FILENAME}，跳过: {cap_dir.name}")
        return 0

    with open(db_path, encoding='utf-8') as f:
        db = json.load(f)
    targets = db.get("targets", [])
    if not targets:
        if verbose:
            print(f"  ⚠ {DB_FILENAME} 无目标，跳过: {cap_dir.name}")
        return 0

    # A manually confirmed map target is stronger evidence than automatically
    # clustered radar seeds. For each semantic class, use manual targets alone
    # when at least one exists; otherwise retain the automatic fallback.
    manual_labels = {
        _canonical_label(t.get("label", ""))
        for t in targets
        if t.get("manual")
    }
    if manual_labels:
        targets = [
            t for t in targets
            if _canonical_label(t.get("label", "")) not in manual_labels
            or t.get("manual")
        ]

    # 加载 nav100
    ts_gps, lat_arr, lon_arr, ts_hdg, hdg_arr = load_capture_nav(cap_dir)
    if len(ts_gps) == 0:
        if verbose:
            print(f"  ⚠ 无 nav100 GPS，跳过: {cap_dir.name}")
        return 0

    # 加载 mat → camera 映射（用于确定 out_stem）
    mat_csv = cap_dir / "match_mat_camera.csv"
    cam_to_mat: dict[str, str] = {}   # camera_name → mat_stem
    if mat_csv.exists():
        try:
            with open(mat_csv, newline='', encoding='utf-8') as fh:
                for row in csv.DictReader(fh):
                    cam = row.get("camera_name", "").strip()
                    mat = Path(row.get("mat_name", "")).stem
                    if cam and mat:
                        cam_to_mat[cam] = mat
        except Exception:
            pass

    out_dir = cap_dir / "depth_labels"
    n_written = 0

    # 遍历 annot_root 中所有 LabelMe JSON
    # 支持两种结构：
    #   annot_root/{camera_stem}.json
    #   annot_root/hikrobot_camera__DA8679037__image_raw/{camera_stem}.json
    capture_annot_root = annot_root / cap_dir.parent.name / cap_dir.name
    search_root = capture_annot_root if capture_annot_root.exists() else annot_root
    annot_jsons = list(search_root.rglob(f"{CAM_SUBDIR}/*.json"))
    if not annot_jsons:
        annot_jsons = list(search_root.glob("*.json"))

    # 只处理属于本 capture 的标注（通过 cam_to_mat 过滤，或直接检查相机子目录）
    # 简单策略：camera_name → 尝试在 cap_dir 里找对应文件验证归属
    cam_names_in_cap: set[str] = set(cam_to_mat.keys())
    if not cam_names_in_cap:
        # 回退：扫描 capture 下所有相机文件
        for img in cap_dir.rglob(f"{CAM_SUBDIR}/*.jpg"):
            cam_names_in_cap.add(img.name)

    def _annot_time(path: Path) -> float:
        match = re.search(r"_t([\d.]+)$", path.stem)
        return float(match.group(1)) if match else float("inf")

    temporal_states: dict[str, TemporalMatchState] = {}
    for ajson in sorted(annot_jsons, key=lambda p: (str(p.parent), _annot_time(p))):
        cam_name = ajson.stem + ".jpg"
        if cam_names_in_cap and cam_name not in cam_names_in_cap:
            continue
        mat_stem = cam_to_mat.get(cam_name)
        sequence_key = str(ajson.parents[2]) if len(ajson.parents) > 2 else str(ajson.parent)
        state = temporal_states.setdefault(sequence_key, TemporalMatchState())
        ok = process_one_frame(
            camera_name=cam_name,
            mat_stem=mat_stem,
            annot_root=annot_root,
            targets=targets,
            out_dir=out_dir,
            ts_gps=ts_gps, lat_arr=lat_arr, lon_arr=lon_arr,
            ts_hdg=ts_hdg, hdg_arr=hdg_arr,
            overwrite=overwrite,
            state=state,
            annot_path=ajson,
        )
        if ok:
            n_written += 1

    # 写标记文件（供 startup_check 检查）
    if n_written > 0:
        marker = out_dir / MARKER_NAME
        marker.write_text(str(ALGORITHM_VERSION), encoding="ascii")

    if verbose:
        print(f"  annot_root={annot_root.name}  "
              f"新写 {n_written} 个 depth JSON")
    return n_written


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="GPS 目标数据库全量深度赋值")
    ap.add_argument("--capture-dir", type=Path,
                    help="单个 capture 目录")
    ap.add_argument("--all", action="store_true",
                    help="遍历 L:/LH_data_all_sensor 所有 capture")
    ap.add_argument("--root", type=Path, default=Path("L:/LH_data_all_sensor"))
    ap.add_argument("--annot-root", type=Path, required=True,
                    help="LabelMe 标注根目录（人工或 autofill）")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true", default=True)
    args = ap.parse_args()

    if args.capture_dir:
        caps = [args.capture_dir]
    elif args.all:
        bins = sorted(args.root.rglob("*_mmwave_udp.bin"))
        caps = list(dict.fromkeys(b.parent for b in bins))
    else:
        ap.print_help();  sys.exit(1)

    print(f"共 {len(caps)} 个 capture，annot_root={args.annot_root}\n")
    total = 0
    for cap in caps:
        print(f"[{cap.parent.name}/{cap.name}]")
        try:
            n = process_capture(cap, args.annot_root,
                                overwrite=args.overwrite,
                                verbose=args.verbose)
            total += n
        except Exception as exc:
            print(f"  [错误] {exc}")
        print()
    print(f"完成，共写出 {total} 个 depth JSON。")


if __name__ == "__main__":
    main()
