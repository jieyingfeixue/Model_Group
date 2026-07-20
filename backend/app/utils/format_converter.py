"""格式转换器 — COCO JSON / VOC XML / YOLO TXT 导出

从数据库指针和标注 JSON 组装为标准格式，不复制物理图片。
被 normal_dataset_service 调用。
"""

from __future__ import annotations

import json
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.data_resource import DataResource
from app.models.dataset_item import DatasetItem
from app.models.label_schema import LabelSchema


class FormatConverter:
    """格式转换器。"""

    # ── COCO JSON ────────────────────────────────────────────────────────

    @staticmethod
    def to_coco(
        db: Session,
        dataset_id: int,
        subset: str | None = None,
    ) -> dict[str, Any]:
        """转换为 COCO JSON 格式。

        输出结构：
        {
            "info": {...},
            "licenses": [...],
            "images": [{id, file_name, width, height}],
            "annotations": [{id, image_id, category_id, bbox: [x,y,w,h], area, iscrowd}],
            "categories": [{id, name, supercategory}]
        }

        坐标转换：内部归一化(cx,cy,w,h) → COCO 绝对坐标(x,y,w,h)左上角原点
        """
        items = _get_items(db, dataset_id, subset)
        if not items:
            return _empty_coco()

        resource_ids = [it.resource_id for it in items]
        resources = _get_resources_map(db, resource_ids)
        annotations_map = _get_latest_annotations_map(db, resource_ids)
        categories = _get_categories(db)

        images = []
        coco_annotations = []
        ann_id = 1

        for item in items:
            rid = item.resource_id
            res = resources.get(rid)
            if res is None:
                continue

            img_w = (res.meta_info or {}).get("width", 0)
            img_h = (res.meta_info or {}).get("height", 0)

            images.append({
                "id": rid,
                "file_name": res.name,
                "width": img_w,
                "height": img_h,
            })

            bboxes = annotations_map.get(rid, [])
            for bbox in bboxes:
                # 归一化(cx,cy,w,h) → 绝对(x,y,w,h)
                cx, cy, w, h = bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 0), bbox.get("h", 0)
                abs_x = (cx - w / 2) * img_w
                abs_y = (cy - h / 2) * img_h
                abs_w = w * img_w
                abs_h = h * img_h

                coco_annotations.append({
                    "id": ann_id,
                    "image_id": rid,
                    "category_id": bbox.get("category_id", "unknown"),
                    "bbox": [round(abs_x, 2), round(abs_y, 2), round(abs_w, 2), round(abs_h, 2)],
                    "area": round(abs_w * abs_h, 2),
                    "iscrowd": 0,
                })
                ann_id += 1

        return {
            "info": {
                "description": f"Dataset {dataset_id} export",
                "version": "1.0",
                "year": 2026,
            },
            "licenses": [],
            "images": images,
            "annotations": coco_annotations,
            "categories": categories,
        }

    # ── VOC XML ───────────────────────────────────────────────────────────

    @staticmethod
    def to_voc(
        db: Session,
        dataset_id: int,
        subset: str | None = None,
    ) -> list[tuple[str, str]]:
        """转换为 VOC XML 格式。每张图片一个 XML 文件。

        返回 [(file_name_without_ext, xml_string), ...]

        坐标转换：内部归一化(cx,cy,w,h) → VOC 绝对(xmin,ymin,xmax,ymax)
        """
        items = _get_items(db, dataset_id, subset)
        if not items:
            return []

        resource_ids = [it.resource_id for it in items]
        resources = _get_resources_map(db, resource_ids)
        annotations_map = _get_latest_annotations_map(db, resource_ids)
        categories = _get_categories(db)

        # 构建 category_id → name 映射（VOC 标准要求使用类别名称而非 ID）
        cat_name_map: dict[str, str] = {c["id"]: c["name"] for c in categories}

        results: list[tuple[str, str]] = []

        for item in items:
            rid = item.resource_id
            res = resources.get(rid)
            if res is None:
                continue

            img_w = (res.meta_info or {}).get("width", 0)
            img_h = (res.meta_info or {}).get("height", 0)
            base_name = res.name.rsplit(".", 1)[0] if "." in res.name else res.name

            annotation_el = Element("annotation")

            folder_el = SubElement(annotation_el, "folder")
            folder_el.text = f"dataset_{dataset_id}"

            filename_el = SubElement(annotation_el, "filename")
            filename_el.text = res.name

            size_el = SubElement(annotation_el, "size")
            SubElement(size_el, "width").text = str(img_w)
            SubElement(size_el, "height").text = str(img_h)
            SubElement(size_el, "depth").text = str(
                (res.meta_info or {}).get("channels", 3)
            )

            bboxes = annotations_map.get(rid, [])
            for bbox in bboxes:
                cx, cy, w, h = bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 0), bbox.get("h", 0)
                xmin = round((cx - w / 2) * img_w, 2)
                ymin = round((cy - h / 2) * img_h, 2)
                xmax = round((cx + w / 2) * img_w, 2)
                ymax = round((cy + h / 2) * img_h, 2)

                cat_id = bbox.get("category_id", "unknown")
                cat_name = cat_name_map.get(cat_id, cat_id)

                obj_el = SubElement(annotation_el, "object")
                SubElement(obj_el, "name").text = cat_name
                SubElement(obj_el, "difficult").text = "0"

                bndbox_el = SubElement(obj_el, "bndbox")
                SubElement(bndbox_el, "xmin").text = str(xmin)
                SubElement(bndbox_el, "ymin").text = str(ymin)
                SubElement(bndbox_el, "xmax").text = str(xmax)
                SubElement(bndbox_el, "ymax").text = str(ymax)

            xml_str = tostring(annotation_el, encoding="unicode")
            results.append((base_name, xml_str))

        return results

    # ── YOLO TXT ──────────────────────────────────────────────────────────

    @staticmethod
    def to_yolo(
        db: Session,
        dataset_id: int,
        subset: str | None = None,
    ) -> tuple[list[tuple[str, str]], str]:
        """转换为 YOLO 格式。

        每张图片一个 .txt 文件：class_id center_x center_y width height（归一化 0~1）
        同时生成 data.yaml。

        返回 ([(file_name_without_ext, txt_content), ...], yaml_content)

        注：YOLO 的 class_id 是整数索引，与 categories 在 data.yaml 中的顺序对应。
        """
        items = _get_items(db, dataset_id, subset)
        if not items:
            return [], ""

        resource_ids = [it.resource_id for it in items]
        resources = _get_resources_map(db, resource_ids)
        annotations_map = _get_latest_annotations_map(db, resource_ids)
        categories = _get_categories(db)

        # 构建 category_id → class_index 映射
        cat_to_idx: dict[str, int] = {}
        for idx, cat in enumerate(categories):
            cat_to_idx[cat["id"]] = idx

        txt_files: list[tuple[str, str]] = []

        for item in items:
            rid = item.resource_id
            res = resources.get(rid)
            if res is None:
                continue

            base_name = res.name.rsplit(".", 1)[0] if "." in res.name else res.name
            lines: list[str] = []

            bboxes = annotations_map.get(rid, [])
            for bbox in bboxes:
                cat_id = bbox.get("category_id", "unknown")
                class_idx = cat_to_idx.get(cat_id, 0)
                cx = bbox.get("x", 0)
                cy = bbox.get("y", 0)
                w = bbox.get("w", 0)
                h = bbox.get("h", 0)
                lines.append(f"{class_idx} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")

            txt_files.append((base_name, "\n".join(lines) + "\n" if lines else ""))

        # 生成 data.yaml
        names = {idx: cat["name"] for idx, cat in enumerate(categories)}
        dataset_name = f"dataset_{dataset_id}"
        if subset:
            dataset_name += f"_{subset}"

        yaml_content = f"# YOLO export — {dataset_name}\n"
        yaml_content += f"nc: {len(categories)}\n"
        yaml_content += f"names:\n"
        for idx, name in names.items():
            yaml_content += f"  {idx}: {name}\n"

        return txt_files, yaml_content

    # ── 校验 ──────────────────────────────────────────────────────────────

    @staticmethod
    def validate_output(format_str: str, output: Any) -> bool:
        """校验输出格式必填字段完整性和坐标合法性。

        format_str: 'coco' / 'voc' / 'yolo'
        """
        if format_str == "coco":
            if not isinstance(output, dict):
                return False
            if "images" not in output or "annotations" not in output:
                return False
            for ann in output.get("annotations", []):
                bbox = ann.get("bbox", [])
                if len(bbox) != 4:
                    return False
                if any(v < 0 for v in bbox):
                    return False
            return True

        if format_str == "voc":
            if not isinstance(output, list):
                return False
            return True

        if format_str == "yolo":
            if not isinstance(output, tuple) or len(output) != 2:
                return False
            return True

        return False


# ═══════════════════════════════════════════════════════════════════════════════
# 内部辅助函数
# ═══════════════════════════════════════════════════════════════════════════════


def _get_items(
    db: Session, dataset_id: int, subset: str | None
) -> list[DatasetItem]:
    """获取 dataset_items，可按 subset 过滤"""
    query = db.query(DatasetItem).filter(DatasetItem.dataset_id == dataset_id)
    if subset:
        query = query.filter(DatasetItem.subset == subset)
    return query.all()


def _get_resources_map(
    db: Session, resource_ids: list[int]
) -> dict[int, DataResource]:
    """批量获取 DataResource，返回 {resource_id: DataResource}"""
    resources = (
        db.query(DataResource)
        .filter(DataResource.resource_id.in_(resource_ids))
        .all()
    )
    return {r.resource_id: r for r in resources}


def _get_latest_annotations_map(
    db: Session, resource_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """获取每个 resource 的最新 approved/submitted 标注 bboxes。

    返回 {resource_id: [bbox, ...]}
    """
    if not resource_ids:
        return {}

    # 子查询：最新版本
    subq = (
        db.query(
            Annotation.resource_id,
            Annotation.task_id,
            func.max(Annotation.version).label("max_version"),
        )
        .filter(
            Annotation.resource_id.in_(resource_ids),
            Annotation.review_status.in_(["approved", "submitted"]),
        )
        .group_by(Annotation.resource_id, Annotation.task_id)
    ).subquery()

    annotations = (
        db.query(Annotation.resource_id, Annotation.bboxes)
        .join(
            subq,
            (Annotation.resource_id == subq.c.resource_id)
            & (Annotation.task_id == subq.c.task_id)
            & (Annotation.version == subq.c.max_version),
        )
        .all()
    )

    result: dict[int, list[dict[str, Any]]] = {rid: [] for rid in resource_ids}
    for rid, bboxes in annotations:
        result[rid] = bboxes or []
    return result


def _get_categories(db: Session) -> list[dict[str, Any]]:
    """获取活跃标签体系的类别列表（COCO 格式）"""
    schema = LabelSchema.get_active(db)
    if schema is None:
        return []
    active = LabelSchema.get_active_categories(db, schema.schema_id)
    return [
        {
            "id": cat["id"],
            "name": cat.get("name", cat["id"]),
            "supercategory": "obstacle",
        }
        for cat in active
    ]


def _empty_coco() -> dict[str, Any]:
    return {
        "info": {"description": "", "version": "1.0", "year": 2026},
        "licenses": [],
        "images": [],
        "annotations": [],
        "categories": [],
    }
