"""标注 Service — 创建任务 / 保存标注 / 查询 / 进度 / 历史"""

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.annotation_task import AnnotationTask
from app.models.data_resource import DataResource


def create_annotation_task(
    db: Session,
    name: str,
    data_range: dict[str, Any],
    schema_id: int,
    assignee_ids: list[int],
    created_by: int,
    reviewer_id: int | None = None,
    skip_review: bool = False,
    deadline: str | None = None,
) -> dict[str, Any]:
    """创建标注任务"""
    deadline_dt = None
    if deadline:
        try:
            deadline_dt = datetime.fromisoformat(deadline)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="deadline 格式无效，需为 ISO 8601 格式",
            )

    task = AnnotationTask.create(
        db,
        name=name,
        data_range=data_range,
        schema_id=schema_id,
        assignee_ids=assignee_ids,
        reviewer_id=reviewer_id,
        skip_review=skip_review,
        deadline=deadline_dt,
        created_by=created_by,
    )
    return {
        "task_id": task.task_id,
        "name": task.name,
        "data_range": task.data_range,
        "schema_id": task.schema_id,
        "assignee_ids": task.assignee_ids,
        "reviewer_id": task.reviewer_id,
        "skip_review": task.skip_review,
        "status": task.status,
        "deadline": task.deadline.isoformat() if task.deadline else None,
        "created_by": task.created_by,
        "created_at": task.created_at.isoformat() if task.created_at else None,
    }


def list_annotation_tasks(
    db: Session,
    user_id: int,
    role: str = "normal",
    status_filter: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询标注任务列表。

    - normal/reviewer: 只看分配给我的
    - admin: 看全部
    """
    if role == "admin":
        query = db.query(AnnotationTask)
    else:
        # 标注员：assignee_ids 包含当前用户；审核员：reviewer_id 为当前用户
        from sqlalchemy import or_

        query = db.query(AnnotationTask).filter(
            or_(
                AnnotationTask.assignee_ids.contains([user_id]),
                AnnotationTask.reviewer_id == user_id,
            )
        )

    if status_filter:
        query = query.filter(AnnotationTask.status == status_filter)

    total = query.count()
    tasks = (
        query.order_by(AnnotationTask.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for t in tasks:
        items.append({
            "task_id": t.task_id,
            "name": t.name,
            "data_range": t.data_range,
            "schema_id": t.schema_id,
            "assignee_ids": t.assignee_ids,
            "reviewer_id": t.reviewer_id,
            "skip_review": t.skip_review,
            "status": t.status,
            "deadline": t.deadline.isoformat() if t.deadline else None,
            "created_by": t.created_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return items, total


def save_annotation(
    db: Session,
    task_id: int,
    resource_id: int,
    bboxes: list[dict[str, Any]],
    user_id: int,
) -> dict[str, Any]:
    """保存标注结果（追加写，版本递增）"""
    # 校验图片在任务的 data_range 内
    task = db.query(AnnotationTask).filter(AnnotationTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标注任务不存在"
        )

    if task.status not in ("draft", "in_progress"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任务状态不允许标注",
        )

    # 若任务为 draft，自动切换到 in_progress
    if task.status == "draft":
        AnnotationTask.update_status(db, task_id, "in_progress")

    annotation = Annotation.save_new_version(
        db, task_id=task_id, resource_id=resource_id, bboxes=bboxes, user_id=user_id
    )

    return {
        "annotation_id": annotation.annotation_id,
        "task_id": annotation.task_id,
        "resource_id": annotation.resource_id,
        "version": annotation.version,
        "message": "保存成功",
    }


# ──── 任务进度 ────

def get_task_progress(db: Session, task_id: int) -> dict[str, Any]:
    """获取标注任务进度统计"""
    task = db.query(AnnotationTask).filter(AnnotationTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标注任务不存在"
        )

    # 统计任务范围内的图片总数
    data_range = task.data_range or {}
    total_images = data_range.get("sample_count", 0)

    # 统计已标注的唯一资源数
    from sqlalchemy import func as sqlfunc

    annotated_row = (
        db.query(sqlfunc.count(sqlfunc.distinct(Annotation.resource_id)))
        .filter(Annotation.task_id == task_id)
        .first()
    )
    annotated = annotated_row[0] if annotated_row else 0

    # 统计已审核数
    reviewed = (
        db.query(sqlfunc.count(sqlfunc.distinct(Annotation.resource_id)))
        .filter(
            Annotation.task_id == task_id,
            Annotation.review_status.in_(["approved", "rejected"]),
        )
        .first()
    )
    reviewed_count = reviewed[0] if reviewed else 0

    progress_pct = round(annotated / total_images * 100, 1) if total_images > 0 else 0.0

    return {
        "task_id": task_id,
        "total_images": total_images,
        "annotated": annotated,
        "reviewed": reviewed_count,
        "progress_pct": progress_pct,
    }


# ──── 下一个待标注图片 ────

def get_next_image(
    db: Session, task_id: int, user_id: int
) -> dict[str, Any] | None:
    """获取下一个待标注的图片"""
    task = db.query(AnnotationTask).filter(AnnotationTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标注任务不存在"
        )

    if task.status not in ("draft", "in_progress"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任务状态不允许标注",
        )

    data_range = task.data_range or {}
    dataset_id = data_range.get("dataset_id")
    resource_ids = data_range.get("resource_ids")

    # 获取任务中已被标注的资源 ID
    from app.models.annotation import Annotation as AnnModel

    annotated_ids = {
        row[0]
        for row in db.query(AnnModel.resource_id)
        .filter(AnnModel.task_id == task_id)
        .distinct()
        .all()
    }

    # 查找下一个未标注的资源
    query = db.query(DataResource)
    if resource_ids:
        query = query.filter(DataResource.resource_id.in_(resource_ids))
    elif dataset_id:
        from app.models.dataset_item import DatasetItem

        item_resource_ids = [
            row[0]
            for row in db.query(DatasetItem.resource_id)
            .filter(DatasetItem.dataset_id == dataset_id)
            .all()
        ]
        if item_resource_ids:
            query = query.filter(DataResource.resource_id.in_(item_resource_ids))

    next_resource = (
        query.filter(~DataResource.resource_id.in_(annotated_ids))
        .order_by(DataResource.resource_id)
        .first()
    )

    if next_resource is None:
        return None  # 全部标注完成

    # 检查是否有已有标注草稿
    existing = Annotation.get_latest(db, task_id, next_resource.resource_id)

    return {
        "resource_id": next_resource.resource_id,
        "name": next_resource.name,
        "modality": next_resource.modality,
        "file_path": next_resource.file_path,
        "has_existing_annotation": existing is not None,
        "existing_annotation_id": existing.annotation_id if existing else None,
        "existing_bboxes": existing.bboxes if existing else None,
    }


# ──── 提交标注 ────

def submit_annotation(
    db: Session, task_id: int, resource_id: int, user_id: int
) -> dict[str, Any]:
    """提交标注结果（标记完成状态）"""
    task = db.query(AnnotationTask).filter(AnnotationTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标注任务不存在"
        )

    annotation = Annotation.get_latest(db, task_id, resource_id)
    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该图片尚未标注，请先保存标注结果",
        )

    # 更新 review_status 为 submitted（如果跳过审核则直接 approved）
    new_status = "approved" if task.skip_review else "submitted"
    annotation.review_status = new_status
    annotation.save(db)

    return {
        "annotation_id": annotation.annotation_id,
        "task_id": task_id,
        "resource_id": resource_id,
        "version": annotation.version,
        "message": "提交成功",
    }


# ──── 标注历史 ────

def get_annotation_history(
    db: Session, task_id: int, resource_id: int
) -> dict[str, Any]:
    """获取某图片的标注历史（所有版本）"""
    history = Annotation.get_history(db, task_id, resource_id)

    current = Annotation.get_latest(db, task_id, resource_id)

    return {
        "resource_id": resource_id,
        "task_id": task_id,
        "history": [
            {
                "annotation_id": a.annotation_id,
                "task_id": a.task_id,
                "resource_id": a.resource_id,
                "version": a.version,
                "bboxes": a.bboxes,
                "review_status": a.review_status,
                "created_by": a.created_by,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
            for a in history
        ],
        "current_version": current.version if current else 1,
    }
