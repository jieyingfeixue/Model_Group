"""数据集审核 Service — 审核员查看/认领/审核裁决 + 15 项检查清单

设计报告 3.3.2 节 reviewer_dataset_service。
系统自动检测 7 项（A1/A5/A6/A7/A8/A9/A11），8 项（A2/A3/A4/A10/A12/A13/A14/A15）由人工判断。
"""

import re
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.data_resource import DataResource
from app.models.dataset import Dataset
from app.models.dataset_item import DatasetItem
from app.models.label_schema import LabelSchema


# ──── 内部辅助 ────


def _find_dataset_or_404(db: Session, dataset_id: int) -> Dataset:
    """查询数据集，不存在则 404"""
    ds = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if ds is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"数据集 dataset_id={dataset_id} 不存在",
        )
    return ds


# ──── 业务函数 ────


def get_pending_datasets(
    db: Session,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Dataset], int]:
    """查看待审核数据集。返回所有 review_status='submitted' 的数据集。

    API: GET /api/review/datasets
    """
    query = db.query(Dataset).filter(Dataset.review_status == "submitted")
    total = query.count()
    datasets = (
        query.order_by(Dataset.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return datasets, total


def claim_dataset_review(
    db: Session,
    dataset_id: int,
    reviewer_id: int,
) -> Dataset:
    """认领数据集审核。锁定数据集，防止重复认领。

    校验：
    - review_status 必须是 'submitted'
    - reviewer_id != owner_id（不可审核自己的数据集）

    API: POST /api/review/datasets/{id}/claim
    """
    ds = _find_dataset_or_404(db, dataset_id)

    if ds.review_status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"数据集状态为 '{ds.review_status}'，只有 'submitted' 状态的数据集可被认领",
        )

    if ds.owner_id == reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能审核自己创建的数据集",
        )

    ds.review_status = "reviewing"
    ds.reviewer_id = reviewer_id
    ds.save(db)
    return ds


def unclaim_dataset_review(
    db: Session,
    dataset_id: int,
    reviewer_id: int,
) -> Dataset:
    """放弃认领。回退为 submitted 状态，清空 reviewer_id。

    校验：当前 reviewer_id 必须是本人。

    注：超时 48h 自动释放由 Celery 定时任务实现（第三阶段）。

    API: POST /api/review/datasets/{id}/unclaim
    """
    ds = _find_dataset_or_404(db, dataset_id)

    if ds.review_status != "reviewing":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"数据集状态为 '{ds.review_status}'，只有 'reviewing' 状态可放弃认领",
        )

    if ds.reviewer_id != reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该数据集当前由其他审核员认领，无法放弃",
        )

    ds.review_status = "submitted"
    ds.reviewer_id = None
    ds.review_notes = None
    ds.save(db)
    return ds


# ═══════════════════════════════════════════════════════════════════════════════
# 15 项检查清单 — 系统自动检测 7 项
# ═══════════════════════════════════════════════════════════════════════════════

def get_review_checklist_result(
    db: Session,
    dataset_id: int,
) -> dict[str, Any]:
    """获取系统辅助检查结果。自动检测 7 项：
    A1  — 文件格式合法性
    A5  — 数据去重（路径级）
    A6  — 标签合法性
    A7  — 标注框规范性
    A8  — 深度值合理性
    A9  — 元信息完整性
    A11 — 命名规范

    返回 {check_id: {passed: bool, detail: str}} 结构。

    API: GET /api/review/datasets/{id}/checklist
    """
    ds = _find_dataset_or_404(db, dataset_id)

    # 获取数据集包含的所有数据资源
    items = db.query(DatasetItem).filter(DatasetItem.dataset_id == dataset_id).all()
    resource_ids = [item.resource_id for item in items]

    if not resource_ids:
        return {"message": "数据集为空，无法执行自动检测", "checks": {}}

    resources = (
        db.query(DataResource)
        .filter(DataResource.resource_id.in_(resource_ids))
        .all()
    )

    checks: dict[str, dict[str, Any]] = {}

    # A1: 文件格式合法性
    checks["A1"] = _check_file_format(resources)

    # A5: 数据去重（路径级）
    checks["A5"] = _check_duplication(resources)

    # A6: 标签合法性
    checks["A6"] = _check_label_validity(db, resource_ids)

    # A7: 标注框规范性
    checks["A7"] = _check_bbox_standard(db, resource_ids)

    # A8: 深度值合理性
    checks["A8"] = _check_depth_range(db, resource_ids)

    # A9: 元信息完整性
    checks["A9"] = _check_metadata_completeness(resources)

    # A11: 命名规范
    checks["A11"] = _check_naming_convention(resources)

    return {
        "dataset_id": dataset_id,
        "resource_count": len(resources),
        "checks": checks,
    }


# ──── 审核裁决 ────


def review_dataset(
    db: Session,
    dataset_id: int,
    reviewer_id: int,
    result: str,
    failed_items: list[str] | None = None,
    notes: str | None = None,
) -> Dataset:
    """审核裁决数据集。

    result: 'approved' → review_status='approved', status='published'
    result: 'rejected' → review_status='rejected'，写入 review_notes

    校验：reviewer_id != owner_id

    API: POST /api/review/datasets/{id}/verdict
    """
    ds = _find_dataset_or_404(db, dataset_id)

    if ds.review_status != "reviewing":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"数据集状态为 '{ds.review_status}'，只有 'reviewing' 状态可裁决",
        )

    if ds.reviewer_id != reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该数据集由其他审核员认领，无法裁决",
        )

    if ds.owner_id == reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能审核自己创建的数据集",
        )

    if result not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"result 必须为 'approved' 或 'rejected'，收到: {result}",
        )

    ds.review_status = "approved" if result == "approved" else "rejected"

    if result == "approved":
        ds.status = "published"
    else:
        ds.review_notes = {
            "result": "rejected",
            "failed_items": failed_items or [],
            "notes": notes or "",
        }

    ds.save(db)
    return ds


# ═══════════════════════════════════════════════════════════════════════════════
# 7 项自动检测实现
# ═══════════════════════════════════════════════════════════════════════════════

VALID_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_\-\./]+$")


def _check_file_format(resources: list[DataResource]) -> dict:
    """A1: 扫描 file_path 后缀，标记非白名单格式"""
    invalid: list[str] = []
    for r in resources:
        name_lower = (r.file_path or "").lower()
        ext = name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
        if f".{ext}" not in VALID_EXTENSIONS:
            invalid.append(r.name)

    if invalid:
        return {
            "passed": False,
            "detail": f"{len(invalid)}/{len(resources)} 个文件格式不在白名单中",
            "samples": invalid[:5],
        }
    return {"passed": True, "detail": f"全部 {len(resources)} 个文件格式合法"}


def _check_duplication(resources: list[DataResource]) -> dict:
    """A5: 按 file_path 判重"""
    seen: dict[str, list[str]] = {}
    for r in resources:
        seen.setdefault(r.file_path or "", []).append(r.name)

    duplicates = {k: v for k, v in seen.items() if len(v) > 1 and k}
    if duplicates:
        sample = list(duplicates.items())[:3]
        return {
            "passed": False,
            "detail": f"发现 {len(duplicates)} 组重复文件",
            "samples": [{"path": k, "files": v} for k, v in sample],
        }
    return {"passed": True, "detail": "未发现重复文件"}


def _check_label_validity(db: Session, resource_ids: list[int]) -> dict:
    """A6: 标注类别是否在平台标签体系内"""
    # 获取所有标注
    annotations = (
        db.query(Annotation)
        .filter(Annotation.resource_id.in_(resource_ids))
        .all()
    )

    if not annotations:
        return {"passed": True, "detail": "数据集中无标注数据，跳过标签合法性检查"}

    # 获取活跃标签体系
    label_schema = LabelSchema.get_active(db)
    if label_schema is None:
        return {"passed": True, "detail": "平台未配置标签体系，跳过检查"}

    valid_ids = {c["id"] for c in (label_schema.categories or []) if c.get("status") != "deprecated"}

    invalid_cats: set[str] = set()
    for ann in annotations:
        for bbox in (ann.bboxes or []):
            cat_id = bbox.get("category_id", "")
            if cat_id and cat_id not in valid_ids:
                invalid_cats.add(cat_id)

    if invalid_cats:
        return {
            "passed": False,
            "detail": f"发现 {len(invalid_cats)} 个类别不在标签体系中",
            "samples": list(invalid_cats),
        }
    return {"passed": True, "detail": "所有标注类别均在标签体系内"}


def _check_bbox_standard(db: Session, resource_ids: list[int]) -> dict:
    """A7: 标注框坐标越界或宽高比异常"""
    annotations = (
        db.query(Annotation)
        .filter(Annotation.resource_id.in_(resource_ids))
        .all()
    )

    if not annotations:
        return {"passed": True, "detail": "无标注数据"}

    out_of_bounds = 0
    bad_aspect = 0
    total_bboxes = 0

    for ann in annotations:
        for bbox in (ann.bboxes or []):
            total_bboxes += 1
            x, y, w, h = bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 0), bbox.get("h", 0)
            # 坐标越界
            if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
                out_of_bounds += 1
            # 宽高比异常：宽 > 高 × 5
            elif h > 0 and w / h > 5:
                bad_aspect += 1

    issues = []
    if out_of_bounds:
        issues.append(f"{out_of_bounds} 个框坐标越界")
    if bad_aspect:
        issues.append(f"{bad_aspect} 个框宽高比异常(w/h>5)")

    if issues:
        return {
            "passed": False,
            "detail": f"共 {total_bboxes} 个标注框，{'、'.join(issues)}",
        }
    return {"passed": True, "detail": f"共 {total_bboxes} 个标注框，坐标和宽高比均正常"}


def _check_depth_range(db: Session, resource_ids: list[int]) -> dict:
    """A8: 深度值 0~500m 范围检测"""
    annotations = (
        db.query(Annotation)
        .filter(Annotation.resource_id.in_(resource_ids))
        .all()
    )

    if not annotations:
        return {"passed": True, "detail": "无标注数据"}

    out_of_range = 0
    total_with_depth = 0

    for ann in annotations:
        for bbox in (ann.bboxes or []):
            depth = bbox.get("depth")
            if depth is not None:
                total_with_depth += 1
                if not (0.0 <= depth <= 500.0):
                    out_of_range += 1

    if out_of_range:
        return {
            "passed": False,
            "detail": f"{out_of_range}/{total_with_depth} 个含深度值的框超出 0~500m 范围",
        }
    if total_with_depth == 0:
        return {"passed": True, "detail": "无深度标注数据"}
    return {"passed": True, "detail": f"{total_with_depth} 个深度值均在 0~500m 范围内"}


def _check_metadata_completeness(resources: list[DataResource]) -> dict:
    """A9: meta_info 常见字段缺失检测"""
    common_fields = ["device", "scene", "weather", "time_of_day"]
    missing_stats: dict[str, int] = {}

    for r in resources:
        meta = r.meta_info or {}
        for field in common_fields:
            if field not in meta or meta[field] is None:
                missing_stats[field] = missing_stats.get(field, 0) + 1

    issues = [
        f"{field}: {count}/{len(resources)} 缺失"
        for field, count in missing_stats.items()
        if count > 0
    ]

    if issues:
        return {
            "passed": False,
            "detail": "元信息字段缺失：" + "、".join(issues),
        }
    return {"passed": True, "detail": "全部关键元信息字段完整"}


def _check_naming_convention(resources: list[DataResource]) -> dict:
    """A11: 文件名和路径是否符合命名规范"""
    invalid: list[str] = []
    for r in resources:
        path = r.file_path or r.name or ""
        if not FILENAME_PATTERN.match(path):
            invalid.append(r.name)

    if invalid:
        return {
            "passed": False,
            "detail": f"{len(invalid)}/{len(resources)} 个文件名含中文/空格/特殊字符",
            "samples": invalid[:5],
        }
    return {"passed": True, "detail": f"全部 {len(resources)} 个文件名符合规范"}
