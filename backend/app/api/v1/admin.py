"""管理端路由（Phase2 B1：训练审批相关）— /api/admin/*"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.database import get_db
from app.models.user import User
from app.schemas.model import TrainRejectRequest, TrainTaskResponse
from app.services import normal_eval_service, normal_model_service

router = APIRouter(tags=["Admin"])


@router.get(
    "/admin/train-tasks/pending",
    response_model=list[TrainTaskResponse],
)
def list_pending_train_tasks(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """待审批训练任务列表"""
    tasks = normal_model_service.list_pending_train_tasks(db)
    return [TrainTaskResponse.model_validate(t) for t in tasks]


@router.post(
    "/admin/train-tasks/{task_id}/approve",
    response_model=TrainTaskResponse,
)
def approve_train_task(
    task_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """审批通过并自动入队 Celery"""
    task = normal_model_service.approve_train_task(db, task_id)
    return TrainTaskResponse.model_validate(task)


@router.post(
    "/admin/train-tasks/{task_id}/reject",
    response_model=TrainTaskResponse,
)
def reject_train_task(
    task_id: int,
    body: TrainRejectRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """拒绝训练申请"""
    task = normal_model_service.reject_train_task(db, task_id, body.reason)
    return TrainTaskResponse.model_validate(task)


@router.post(
    "/admin/train-tasks/{task_id}/terminate",
    response_model=TrainTaskResponse,
)
def terminate_train_task(
    task_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员强制终止训练"""
    task = normal_model_service.terminate_train_task(db, task_id)
    return TrainTaskResponse.model_validate(task)


@router.post("/admin/eval-results/{result_id}/invalidate")
def invalidate_eval_result(
    result_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """天梯下架：is_public=false"""
    result = normal_eval_service.invalidate_eval_result(db, result_id)
    return {
        "result_id": result.result_id,
        "is_public": result.is_public,
        "status": "invalidated",
    }


@router.post("/admin/eval-results/{result_id}/publish")
def publish_eval_result(
    result_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """纳入天梯：is_public=true"""
    result = normal_eval_service.publish_eval_result(db, result_id)
    return {
        "result_id": result.result_id,
        "is_public": result.is_public,
        "status": "published",
    }
