"""队友外部 LabelMe 标注加载 — 仅用于可见光详情页叠加显示。

标注目录形如 label_with_cameras_capture_*，JSON 放在红外帧文件夹下，
但 imagePath / group.visible_file 指向可见光图；按可见光文件名匹配。
匹配不上则返回空列表。
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TS_RE = re.compile(r"_t(\d{6}\.\d{3})", re.IGNORECASE)
_CAM_FROM_SENSOR = {
    "DA8679037": "037",
    "DA8679038": "038",
}

# visible_file basename (normalized) -> list of json paths
_index_by_visible: dict[str, list[Path]] = {}
# "000076.100_038" -> list of json paths
_index_by_ts_cam: dict[str, list[Path]] = {}
# 有非空 shapes 的可见光名 / 时间戳相机键
_annotated_visible: set[str] = set()
_annotated_ts_cam: set[str] = set()
_index_built_at: float = 0.0
_index_roots: tuple[str, ...] = ()
_INDEX_TTL_SEC = 3600.0


def _repo_root() -> Path:
    # backend/app/utils/external_labels.py -> parents[3] = repo root（本地开发）
    # Docker 中文件在 /app/app/utils/...，parents[3] 会变成 "/"，不可用作扫描根
    return Path(__file__).resolve().parents[3]


def _is_usable_root(path: Path) -> bool:
    """拒绝文件系统根目录等过大路径，避免 Docker 下误扫整个 /。"""
    try:
        if not path.is_dir():
            return False
        resolved = path.resolve()
    except OSError:
        return False
    # Path.parent == self 表示驱动器根 / 或 C:\
    if resolved.parent == resolved:
        return False
    return True


def _label_roots() -> list[Path]:
    roots: list[Path] = []
    env = os.environ.get("EXTERNAL_LABEL_DIRS", "").strip()
    if env:
        for part in re.split(r"[;:]", env):
            part = part.strip()
            if part:
                roots.append(Path(part))
    else:
        # 未配置环境变量时：容器内 /labels + 本地仓库根
        roots.append(Path("/labels"))
        roots.append(_repo_root())

    seen: set[str] = set()
    out: list[Path] = []
    for r in roots:
        if not _is_usable_root(r):
            continue
        try:
            key = str(r.resolve())
        except OSError:
            key = str(r)
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _discover_label_dirs(roots: list[Path]) -> list[Path]:
    dirs: list[Path] = []
    for root in roots:
        if root.name.startswith("label_with_cameras_capture_"):
            dirs.append(root)
            continue
        try:
            for child in root.iterdir():
                if child.is_dir() and child.name.startswith("label_with_cameras_capture_"):
                    dirs.append(child)
        except OSError:
            continue
    return dirs


def _normalize_name(name: str) -> str:
    """统一 hikrobot 文件名中连续下划线，便于匹配。"""
    base = Path(name).name
    base = re.sub(r"_+", "_", base)
    return base.lower()


def _build_index(force: bool = False) -> None:
    global _index_by_visible, _index_by_ts_cam, _annotated_visible, _annotated_ts_cam
    global _index_built_at, _index_roots

    roots = _label_roots()
    root_key = tuple(str(r) for r in roots)
    now = time.time()
    if (
        not force
        and _index_by_visible
        and root_key == _index_roots
        and now - _index_built_at < _INDEX_TTL_SEC
    ):
        return

    index: dict[str, list[Path]] = {}
    by_ts: dict[str, list[Path]] = {}
    annotated_vis: set[str] = set()
    annotated_ts: set[str] = set()
    label_dirs = _discover_label_dirs(roots)
    count = 0
    for label_dir in label_dirs:
        for jp in label_dir.rglob("*.json"):
            try:
                with open(jp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue

            group = data.get("group") if isinstance(data.get("group"), dict) else {}
            visible = None
            v = data.get("imagePath")
            if isinstance(v, str) and v.strip():
                visible = Path(v).name
            if not visible:
                vf = group.get("visible_file")
                if isinstance(vf, str) and vf.strip():
                    visible = Path(vf).name

            has_shapes = bool(data.get("shapes"))
            stem_key = jp.stem.lower()
            by_ts.setdefault(stem_key, []).append(jp)
            cam = str(data.get("camera") or "")
            vts = str(group.get("visible_timestamp") or "")
            ts_keys = [stem_key]
            if cam and vts:
                ts_keys.append(f"{vts}_{cam}".lower())
                by_ts.setdefault(ts_keys[-1], []).append(jp)

            if visible:
                norm = _normalize_name(visible)
                index.setdefault(norm, []).append(jp)
                if has_shapes:
                    annotated_vis.add(norm)

            if has_shapes:
                for k in ts_keys:
                    annotated_ts.add(k)
            count += 1

    _index_by_visible = index
    _index_by_ts_cam = by_ts
    _annotated_visible = annotated_vis
    _annotated_ts_cam = annotated_ts
    _index_built_at = now
    _index_roots = root_key
    logger.info(
        "external labels indexed: %d json, %d annotated visible under %s",
        count,
        len(annotated_vis),
        [str(d) for d in label_dirs],
    )


def _labelme_to_bboxes(data: dict[str, Any]) -> list[dict[str, Any]]:
    iw = float(data.get("imageWidth") or 0) or 1920.0
    ih = float(data.get("imageHeight") or 0) or 1200.0
    bboxes: list[dict[str, Any]] = []
    for shape in data.get("shapes") or []:
        if not isinstance(shape, dict):
            continue
        if shape.get("shape_type") not in (None, "rectangle"):
            continue
        pts = shape.get("points") or []
        if len(pts) < 2:
            continue
        try:
            x1, y1 = float(pts[0][0]), float(pts[0][1])
            x2, y2 = float(pts[1][0]), float(pts[1][1])
        except (TypeError, ValueError, IndexError):
            continue
        left, top = min(x1, x2), min(y1, y2)
        right, bottom = max(x1, x2), max(y1, y2)
        attrs = shape.get("attributes") if isinstance(shape.get("attributes"), dict) else {}
        name = (
            attrs.get("label_zh")
            or shape.get("label")
            or attrs.get("label_id")
            or "目标"
        )
        depth = attrs.get("depth_m")
        try:
            depth_val = float(depth) if depth is not None else None
        except (TypeError, ValueError):
            depth_val = None
        bboxes.append({
            "x": left / iw,
            "y": top / ih,
            "w": (right - left) / iw,
            "h": (bottom - top) / ih,
            "category_id": name,
            "category_name": name,
            "depth": depth_val,
            "occlusion": "none",
            "truncation": "none",
        })
    return bboxes


def _camera_suffix(meta: dict[str, Any] | None, name: str) -> str | None:
    meta = meta or {}
    sensor = str(meta.get("sensor") or "")
    device = str(meta.get("device") or "")
    blob = f"{sensor} {device} {name}"
    for key, cam in _CAM_FROM_SENSOR.items():
        if key in blob:
            return cam
    return None


def _timestamp_from_name(name: str) -> str | None:
    m = _TS_RE.search(name)
    return m.group(1) if m else None


def _load_best_bboxes(paths: list[Path]) -> list[dict[str, Any]]:
    best: list[dict[str, Any]] = []
    for jp in paths:
        try:
            with open(jp, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        boxes = _labelme_to_bboxes(data)
        if boxes:
            return boxes
        if not best:
            best = boxes
    return best


def has_external_annotation(
    *,
    name: str,
    modality: str | None,
    meta_info: dict[str, Any] | None = None,
) -> bool:
    """可见光是否存在非空外部标注（不读框，仅查索引）。"""
    if (modality or "").lower() != "visible" or not name:
        return False
    _build_index()
    if _normalize_name(name) in _annotated_visible:
        return True
    cam = _camera_suffix(meta_info, name)
    ts = _timestamp_from_name(name)
    if cam and ts and f"{ts}_{cam}".lower() in _annotated_ts_cam:
        return True
    return False


def get_external_bboxes_for_resource(
    *,
    name: str,
    modality: str | None,
    meta_info: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """按可见光资源匹配外部 LabelMe JSON，返回归一化 bbox 列表。"""
    if (modality or "").lower() != "visible":
        return []
    if not name:
        return []

    _build_index()
    if not _index_by_visible and not _index_by_ts_cam:
        return []

    paths = list(_index_by_visible.get(_normalize_name(name)) or [])

    if not paths:
        cam = _camera_suffix(meta_info, name)
        ts = _timestamp_from_name(name)
        if cam and ts:
            paths = list(_index_by_ts_cam.get(f"{ts}_{cam}".lower()) or [])

    if not paths:
        return []
    return _load_best_bboxes(list(dict.fromkeys(paths)))
