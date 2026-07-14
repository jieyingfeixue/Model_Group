"""标注路由 — /api/annotation/*"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.annotation import (
    AnnotationHistoryResponse,
    AnnotationProgressResponse,
    AnnotationResponse,
    AnnotationSaveRequest,
    AnnotationTaskCreate,
    AnnotationTaskResponse,
)
from app.services import normal_annotation_service

router = APIRouter(tags=["Annotation"])


# ──── /api/annotation/tasks ────


@router.post(
    "/annotation/tasks",
    response_model=AnnotationTaskResponse,
    status_code=201,
)
def create_task(
    body: AnnotationTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建标注任务。"""
    task = normal_annotation_service.create_annotation_task(
        db,
        name=body.name,
        data_range=body.data_range,
        schema_id=body.schema_id,
        assignee_ids=body.assignee_ids,
        created_by=current_user.user_id,
        reviewer_id=body.reviewer_id,
        skip_review=body.skip_review,
        deadline=body.deadline.isoformat() if body.deadline else None,
    )
    return AnnotationTaskResponse.model_validate(task)


@router.get("/annotation/tasks")
def list_my_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询我参与的标注任务（作为标注员或创建者）。"""
    tasks = normal_annotation_service.list_my_tasks(db, user_id=current_user.user_id)
    return {
        "items": [AnnotationTaskResponse.model_validate(t) for t in tasks],
        "count": len(tasks),
    }


@router.get(
    "/annotation/tasks/{task_id}/progress",
    response_model=AnnotationProgressResponse,
)
def get_progress(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标注任务进度统计。"""
    result = normal_annotation_service.get_annotation_progress(db, task_id=task_id)
    return AnnotationProgressResponse(**result)


# ──── /api/annotation/images/{id}/* ────


@router.put(
    "/annotation/images/{resource_id}/save",
    response_model=AnnotationResponse,
)
def save_annotation(
    resource_id: int,
    body: AnnotationSaveRequest,
    task_id: int = Query(..., description="标注任务 ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存标注（追加写模式）。每 30 秒自动保存 + Ctrl+S 由前端触发。"""
    bboxes = [bbox.model_dump(exclude_none=True) for bbox in body.bboxes]
    annotation = normal_annotation_service.save_annotation(
        db,
        task_id=task_id,
        resource_id=resource_id,
        bboxes=bboxes,
        user_id=current_user.user_id,
    )
    return AnnotationResponse.model_validate(annotation)


@router.get(
    "/annotation/images/{resource_id}/history",
    response_model=AnnotationHistoryResponse,
)
def get_history(
    resource_id: int,
    task_id: int = Query(..., description="标注任务 ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标注历史版本（按版本号降序）。"""
    versions = normal_annotation_service.get_annotation_history(
        db, task_id=task_id, resource_id=resource_id
    )
    return AnnotationHistoryResponse(
        resource_id=resource_id,
        task_id=task_id,
        versions=[AnnotationResponse.model_validate(v) for v in versions],
        count=len(versions),
    )


@router.post(
    "/annotation/images/{resource_id}/submit",
    response_model=AnnotationResponse,
)
def submit_annotation(
    resource_id: int,
    task_id: int = Query(..., description="标注任务 ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交标注进入审核队列。skip_review 任务直接标记为 approved。"""
    annotation = normal_annotation_service.submit_annotation(
        db,
        task_id=task_id,
        resource_id=resource_id,
        user_id=current_user.user_id,
    )
    return AnnotationResponse.model_validate(annotation)
