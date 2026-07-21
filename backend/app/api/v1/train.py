"""训练任务路由 — /api/train/tasks/*"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.model import TrainTaskCreate, TrainTaskResponse
from app.services import normal_model_service

router = APIRouter(tags=["Train"])


@router.post("/train/tasks", response_model=TrainTaskResponse, status_code=201)
def submit_train(
    body: TrainTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交训练任务（初始状态 pending_approval）"""
    task = normal_model_service.submit_train_task(
        db,
        model_id=body.model_id,
        dataset_id=body.dataset_id,
        config=body.config,
        gpu_config=body.gpu_config,
        user_id=current_user.user_id,
        model_version_id=body.model_version_id,
    )
    return TrainTaskResponse.model_validate(task)


@router.post("/train/tasks/{task_id}/enqueue", response_model=TrainTaskResponse)
def enqueue_train(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """管理员手动入队 / 重试（待审任务请走 /api/admin/train-tasks/{id}/approve）"""
    task = normal_model_service.enqueue_train_task(db, task_id, current_user)
    return TrainTaskResponse.model_validate(task)


@router.get("/train/tasks/{task_id}", response_model=TrainTaskResponse)
def get_train(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看训练进度"""
    task = normal_model_service.get_train_task_detail(db, task_id, current_user)
    return TrainTaskResponse.model_validate(task)


@router.post("/train/tasks/{task_id}/stop", response_model=TrainTaskResponse)
def stop_train(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """终止训练"""
    task = normal_model_service.stop_train_task(db, task_id, current_user)
    return TrainTaskResponse.model_validate(task)


@router.get("/train/tasks/{task_id}/logs")
def get_train_logs(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """读取训练日志（Redis）"""
    normal_model_service.get_train_task_detail(db, task_id, current_user)
    return {"lines": normal_model_service.get_train_logs(task_id)}
