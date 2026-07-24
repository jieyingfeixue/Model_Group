"""场景标签工具 — 从合规 Excel 解析「采集会话文件夹 → 筛选标签」映射。

不修改任何磁盘目录/文件名；标签写入 data_resources.metadata (JSONB)。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# 前端 SearchFilter / 后端 Query 使用的英文枚举
WEATHER_MAP = {
    "晴天": "sunny",
    "多云": "cloudy",
    "雨天": "rainy",
    "雾天": "foggy",
}

TIME_MAP = {
    "白天": "day",
    "夜晚": "night",
}

TERRAIN_MAP = {
    "山地": "mountain",
    "山区": "mountain",
    "平原": "plain",
    "河流": "river",
    "城市": "urban",
    "高速": "highway",
    "乡村": "rural",
}

OBSTACLE_MAP = {
    "高压": "pole",
    "高压线塔": "pole",
    "电线杆": "pole",
    "建筑": "building",
    "建筑物": "building",
    "桥梁": "bridge",
    "树木": "tree",
    "路灯": "lamp",
    "风力": "wind",
    "风力发电车": "wind",
}

CAPTURE_DIR_RE = re.compile(
    # 会话根：with_cameras_capture_YYYYMMDD_HHMMSS 或 ..._1 / ...(1)
    # 不要吃掉 _part000_... 分段目录名
    r"with_cameras_capture_\d{8}_\d{6}(?:_\d+)?(?:\([^)]+\))?",
    re.IGNORECASE,
)


DEFAULT_EXCEL = (
    Path(__file__).resolve().parent.parent
    / "docs"
    / "test"
    / "compliance_paths_with_counts_new.xlsx"
)


def normalize_batch_id(raw: str) -> str:
    """从路径或目录名中提取会话文件夹名（batch_id）。"""
    text = (raw or "").strip().replace("/", "\\")
    if not text:
        return ""
    m = CAPTURE_DIR_RE.search(text)
    if m:
        return m.group(0)
    # 已是纯目录名
    name = Path(text.replace("\\", "/")).name
    return name


def canonical_batch_id(raw: str) -> str:
    """去掉增强后缀，便于 Excel「目录」与「实际统计目录」对齐。"""
    bid = normalize_batch_id(raw)
    if not bid:
        return ""
    bid = re.sub(r"_rife(_x\d+)?$", "", bid, flags=re.IGNORECASE)
    bid = re.sub(r"_converted_[a-z0-9_]+$", "", bid, flags=re.IGNORECASE)
    return bid


def resolve_tags(
    folder_tags: dict[str, dict[str, Any]], batch_id: str | None
) -> dict[str, Any] | None:
    if not batch_id:
        return None
    if batch_id in folder_tags:
        return dict(folder_tags[batch_id])
    canon = canonical_batch_id(batch_id)
    if canon and canon in folder_tags:
        tags = dict(folder_tags[canon])
        tags["batch_id"] = canon
        return tags
    return None


def infer_batch_id_from_path(path: Path | str) -> str | None:
    """从本地文件路径向上查找 with_cameras_capture_* 目录名。"""
    p = Path(path)
    for part in [p.name, *p.parts[::-1]]:
        bid = normalize_batch_id(str(part))
        if bid.startswith("with_cameras_capture_"):
            return bid
    return None


def _map_or_keep(value: Any, mapping: dict[str, str]) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in mapping:
        return mapping[text]
    # 已是英文枚举
    if text in mapping.values():
        return text
    return text


def row_to_tags(
    weather: Any,
    time_of_day: Any,
    terrain: Any,
    obstacle: Any,
    scene_desc: Any = None,
    compliance_id: Any = None,
) -> dict[str, Any]:
    tags: dict[str, Any] = {}
    w = _map_or_keep(weather, WEATHER_MAP)
    t = _map_or_keep(time_of_day, TIME_MAP)
    tr = _map_or_keep(terrain, TERRAIN_MAP)
    o = _map_or_keep(obstacle, OBSTACLE_MAP)
    if w:
        tags["weather"] = w
    if t:
        tags["time_of_day"] = t
    if tr:
        tags["terrain"] = tr
    if o:
        tags["obstacle"] = o
    if scene_desc is not None and str(scene_desc).strip():
        tags["scene"] = str(scene_desc).strip()
    elif any(k in tags for k in ("weather", "time_of_day", "terrain", "obstacle")):
        # 无整句描述时，用中文片段拼一个展示用 scene
        parts = []
        rev_w = {v: k for k, v in WEATHER_MAP.items()}
        rev_t = {v: k for k, v in TIME_MAP.items()}
        rev_tr = {v: k for k, v in TERRAIN_MAP.items()}
        rev_o = {v: k for k, v in OBSTACLE_MAP.items()}
        if w:
            parts.append(rev_w.get(w, w))
        if t:
            parts.append(rev_t.get(t, t))
        if tr:
            parts.append(rev_tr.get(tr, tr))
        if o:
            parts.append(rev_o.get(o, o))
        if parts:
            tags["scene"] = "、".join(parts)
    if compliance_id is not None and str(compliance_id).strip() != "":
        try:
            tags["compliance_id"] = int(compliance_id)
        except (TypeError, ValueError):
            tags["compliance_id"] = compliance_id
    return tags


def load_excel_folder_tags(xlsx_path: Path | str | None = None) -> dict[str, dict[str, Any]]:
    """读取合规 Excel，返回 {batch_id: tags}。

    同一会话出现在多行时：保留首次出现的标签，并把后续合规号追加到 compliance_ids。
    """
    try:
        import openpyxl
    except ImportError as e:
        raise ImportError("请先安装 openpyxl: pip install openpyxl") from e

    path = Path(xlsx_path) if xlsx_path else DEFAULT_EXCEL
    if not path.is_file():
        raise FileNotFoundError(f"找不到场景 Excel: {path}")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return {}

    # 表头：合规号, 场景(描述), 天气, 时段, 场景(地形), 障碍物, 目录, 实际统计目录, ...
    result: dict[str, dict[str, Any]] = {}
    for row in rows[1:]:
        if not row or len(row) < 7:
            continue
        compliance_id, scene_desc, weather, tod, terrain, obstacle = row[:6]
        dirs_raw = row[6] or ""
        # 优先用「目录」列；为空则退回「实际统计目录」
        if not str(dirs_raw).strip() and len(row) > 7 and row[7]:
            dirs_raw = row[7]

        tags = row_to_tags(weather, tod, terrain, obstacle, scene_desc, compliance_id)
        if not tags:
            continue

        for part in str(dirs_raw).split(";"):
            bid = normalize_batch_id(part)
            if not bid:
                continue
            if bid not in result:
                result[bid] = {**tags, "batch_id": bid, "compliance_ids": [tags.get("compliance_id")] if "compliance_id" in tags else []}
            else:
                cid = tags.get("compliance_id")
                ids = result[bid].setdefault("compliance_ids", [])
                if cid is not None and cid not in ids:
                    ids.append(cid)

    # 清理 None
    for bid, tags in result.items():
        ids = [x for x in (tags.get("compliance_ids") or []) if x is not None]
        if ids:
            tags["compliance_ids"] = ids
        elif "compliance_ids" in tags:
            del tags["compliance_ids"]

    return result


def lookup_tags_for_path(
    path: Path | str,
    folder_tags: dict[str, dict[str, Any]],
    fallback_batch_id: str | None = None,
) -> dict[str, Any]:
    """根据文件路径或 fallback batch_id 查找标签；找不到则只返回 batch_id（若有）。"""
    bid = infer_batch_id_from_path(path) or normalize_batch_id(fallback_batch_id or "")
    tags = resolve_tags(folder_tags, bid)
    if tags:
        return tags
    if bid:
        return {"batch_id": canonical_batch_id(bid) or bid}
    return {}
