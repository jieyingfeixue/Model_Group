"""标注文件解析器 — COCO JSON / VOC XML / YOLO TXT

所有解析器返回统一结构：{file_name: [{x, y, w, h, category_id, ...}], ...}
坐标统一为归一化 0~1。
"""

from __future__ import annotations

import json
from typing import Any
from xml.etree import ElementTree


# ═══════════════════════════════════════════════════════════════════════════════
# COCO JSON 解析
# ═══════════════════════════════════════════════════════════════════════════════

def parse_coco(json_str: str) -> dict[str, list[dict[str, Any]]]:
    """解析 COCO JSON 格式。

    Args:
        json_str: COCO JSON 字符串。

    Returns:
        {file_name: [{x, y, w, h, category_id, ...}]}
        x, y, w, h 为归一化值（0~1）。
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"COCO JSON 格式错误: {e}") from e

    # 构建 id → 宽高 / 文件名映射
    image_map: dict[int, dict] = {}
    for img in data.get("images", []):
        image_map[img["id"]] = {
            "file_name": img["file_name"],
            "width": img.get("width", 1),
            "height": img.get("height", 1),
        }

    # 构建 category_id → category_name 映射
    category_map: dict[int, str] = {}
    for cat in data.get("categories", []):
        category_map[cat["id"]] = cat.get("name", f"class_{cat['id']}")

    # 按 file_name 聚合标注
    result: dict[str, list[dict[str, Any]]] = {}
    for ann in data.get("annotations", []):
        image_id = ann["image_id"]
        img_info = image_map.get(image_id)
        if img_info is None:
            continue

        file_name = img_info["file_name"]
        img_w = img_info["width"]
        img_h = img_info["height"]

        # COCO bbox: [x, y, w, h] — 左上角绝对坐标
        bbox = ann["bbox"]
        abs_x, abs_y, abs_w, abs_h = bbox[0], bbox[1], bbox[2], bbox[3]

        # 转归一化 center_x, center_y, w, h
        norm_cx = (abs_x + abs_w / 2) / img_w if img_w > 0 else 0.0
        norm_cy = (abs_y + abs_h / 2) / img_h if img_h > 0 else 0.0
        norm_w = abs_w / img_w if img_w > 0 else 0.0
        norm_h = abs_h / img_h if img_h > 0 else 0.0

        cat_id = category_map.get(ann.get("category_id", 0), f"class_{ann.get('category_id', 0)}")

        bbox_entry = {
            "x": round(norm_cx, 6),
            "y": round(norm_cy, 6),
            "w": round(norm_w, 6),
            "h": round(norm_h, 6),
            "category_id": cat_id,
        }

        result.setdefault(file_name, []).append(bbox_entry)

    return result


# ═══════════════════════════════════════════════════════════════════════════════
# VOC XML 解析
# ═══════════════════════════════════════════════════════════════════════════════

def parse_voc(xml_str: str, file_name: str | None = None) -> dict[str, list[dict[str, Any]]]:
    """解析 VOC XML 格式（单个文件）。

    Args:
        xml_str: VOC XML 字符串。
        file_name: 若 XML 不包含文件名，指定对应的图片文件名。

    Returns:
        {file_name: [{x, y, w, h, category_id, ...}]}
    """
    try:
        root = ElementTree.fromstring(xml_str)
    except ElementTree.ParseError as e:
        raise ValueError(f"VOC XML 格式错误: {e}") from e

    # 获取图片尺寸
    size = root.find("size")
    img_w = float(size.findtext("width", "1")) if size is not None else 1.0
    img_h = float(size.findtext("height", "1")) if size is not None else 1.0

    # 尝试从 XML 中获取文件名
    if file_name is None:
        fn_elem = root.find("filename")
        file_name = fn_elem.text if fn_elem is not None else "unknown.jpg"

    bboxes: list[dict[str, Any]] = []
    for obj in root.findall("object"):
        name = obj.findtext("name", "unknown")
        bndbox = obj.find("bndbox")
        if bndbox is None:
            continue

        xmin = float(bndbox.findtext("xmin", "0"))
        ymin = float(bndbox.findtext("ymin", "0"))
        xmax = float(bndbox.findtext("xmax", "0"))
        ymax = float(bndbox.findtext("ymax", "0"))

        # 转归一化
        norm_cx = ((xmin + xmax) / 2) / img_w if img_w > 0 else 0.0
        norm_cy = ((ymin + ymax) / 2) / img_h if img_h > 0 else 0.0
        norm_w = (xmax - xmin) / img_w if img_w > 0 else 0.0
        norm_h = (ymax - ymin) / img_h if img_h > 0 else 0.0

        bboxes.append({
            "x": round(norm_cx, 6),
            "y": round(norm_cy, 6),
            "w": round(norm_w, 6),
            "h": round(norm_h, 6),
            "category_id": name.strip(),
        })

    return {file_name: bboxes}


# ═══════════════════════════════════════════════════════════════════════════════
# YOLO TXT 解析
# ═══════════════════════════════════════════════════════════════════════════════

def parse_yolo(
    txt_str: str,
    file_name: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """解析 YOLO TXT 格式（单个文件）。

    Args:
        txt_str: YOLO 标注文件内容，每行 "class_id cx cy w h"
        file_name: 对应的图片文件名。

    Returns:
        {file_name: [{x, y, w, h, category_id: "class_N"}]}
    """
    bboxes: list[dict[str, Any]] = []
    for line in txt_str.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split()
        if len(parts) < 5:
            continue

        try:
            class_id = int(parts[0])
            cx, cy, w, h = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
        except (ValueError, IndexError):
            continue

        bboxes.append({
            "x": round(cx, 6),
            "y": round(cy, 6),
            "w": round(w, 6),
            "h": round(h, 6),
            "category_id": f"class_{class_id}",
        })

    return {file_name or "unknown.jpg": bboxes}


# ═══════════════════════════════════════════════════════════════════════════════
# 类别匹配辅助
# ═══════════════════════════════════════════════════════════════════════════════

def match_categories(
    bboxes_by_file: dict[str, list[dict[str, Any]]],
    categories: list[dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """将标注中的类别名按 label_schema 的 name 字段匹配到 cat_001 格式。

    Args:
        bboxes_by_file: parse_* 的输出。
        categories: label_schema 的 categories 列表（仅活跃类别）。

    Returns:
        (更新后的 bboxes_by_file, 匹配失败的类别名列表)
    """
    # 构建 name → id 映射（忽略大小写）
    name_to_id: dict[str, str] = {}
    for cat in categories:
        name = cat.get("name", "").lower().strip()
        cat_id = cat.get("id", "")
        if name and cat_id:
            name_to_id[name] = cat_id

    unmatched: set[str] = set()
    for file_name, bboxes in bboxes_by_file.items():
        for bbox in bboxes:
            raw_name = str(bbox.get("category_id", "")).lower().strip()
            if raw_name in name_to_id:
                bbox["category_id"] = name_to_id[raw_name]
            else:
                unmatched.add(bbox["category_id"])

    return bboxes_by_file, list(unmatched)
