"""标注 Service — 创建任务 / 保存标注 / 查询"""

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.annotation_task import AnnotationTask


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
