"""标注路由 — /api/annotation/*"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.annotation import (
    AnnotationSaveRequest,
    AnnotationSaveResponse,
    AnnotationSubmitRequest,
    AnnotationSubmitResponse,
    AnnotationHistoryResponse,
    AnnotationProgressResponse,
    AnnotationNextImageResponse,
    AnnotationTaskCreateRequest,
    AnnotationTaskListResponse,
    AnnotationTaskResponse,
)
from app.services import normal_annotation_service

router = APIRouter(prefix="/annotation", tags=["Annotation"])


# ──── POST /api/annotation/tasks ────

@router.post("/tasks", response_model=AnnotationTaskResponse, status_code=201)
def create_annotation_task(
    body: AnnotationTaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建标注任务"""
    result = normal_annotation_service.create_annotation_task(
        db,
        name=body.name,
        data_range=body.data_range,
        schema_id=body.schema_id,
        assignee_ids=body.assignee_ids,
        created_by=current_user.user_id,
        reviewer_id=body.reviewer_id,
        skip_review=body.skip_review,
        deadline=body.deadline,
    )
    return AnnotationTaskResponse(**result)


# ──── GET /api/annotation/tasks ────

@router.get("/tasks", response_model=AnnotationTaskListResponse)
def list_annotation_tasks(
    status: str | None = Query(None, description="按状态筛选: draft / in_progress / completed"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """标注任务列表"""
    items, total = normal_annotation_service.list_annotation_tasks(
        db,
        user_id=current_user.user_id,
        role=current_user.role,
        status_filter=status,
        page=page,
        size=size,
    )
    return AnnotationTaskListResponse(
        items=[AnnotationTaskResponse(**it) for it in items],
        total=total,
        page=page,
        size=size,
    )


# ──── PUT /api/annotation/images/{resource_id}/save ────

@router.put("/images/{resource_id}/save", response_model=AnnotationSaveResponse)
def save_annotation(
    resource_id: int,
    body: AnnotationSaveRequest,
    task_id: int = Query(..., description="标注任务 ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """保存标注结果（追加写版本）"""
    result = normal_annotation_service.save_annotation(
        db,
        task_id=task_id,
        resource_id=resource_id,
        bboxes=body.bboxes,
        user_id=current_user.user_id,
    )
    return AnnotationSaveResponse(**result)


# ──── §11 扩展：进度 / 下一张 / 提交 / 历史 ────


@router.get("/tasks/{task_id}/progress", response_model=AnnotationProgressResponse)
def get_task_progress(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取标注任务进度统计"""
    result = normal_annotation_service.get_task_progress(db, task_id)
    return AnnotationProgressResponse(**result)


@router.get("/tasks/{task_id}/next", response_model=AnnotationNextImageResponse)
def get_next_image(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取下一个待标注的图片"""
    result = normal_annotation_service.get_next_image(db, task_id, current_user.user_id)
    if result is None:
        raise HTTPException(status_code=404, detail="没有待标注的图片（可能已全部完成）")
    return AnnotationNextImageResponse(**result)


@router.post("/images/{resource_id}/submit", response_model=AnnotationSubmitResponse)
def submit_annotation(
    resource_id: int,
    body: AnnotationSubmitRequest = AnnotationSubmitRequest(),
    task_id: int = Query(..., description="标注任务 ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交标注结果（标记该图片标注完成）"""
    result = normal_annotation_service.submit_annotation(
        db, task_id=task_id, resource_id=resource_id, user_id=current_user.user_id
    )
    return AnnotationSubmitResponse(**result)


@router.get("/images/{resource_id}/history", response_model=AnnotationHistoryResponse)
def get_annotation_history(
    resource_id: int,
    task_id: int = Query(..., description="标注任务 ID"),
    db: Session = Depends(get_db),
):
    """获取某图片在指定任务中的标注历史（所有版本）"""
    result = normal_annotation_service.get_annotation_history(db, task_id, resource_id)
    return AnnotationHistoryResponse(**result)
