"""评测分析路由 — /api/eval/*"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.eval import (
    EvalCompareRequest,
    EvalMetricsResponse,
    EvalTaskCreate,
    EvalTaskResponse,
)
from app.services import normal_eval_service

router = APIRouter(tags=["Eval"])


@router.post("/eval/tasks", response_model=EvalTaskResponse, status_code=201)
def submit_eval(
    body: EvalTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发起评测任务并入队 Celery"""
    task = normal_eval_service.submit_eval_task(
        db,
        model_id=body.model_id,
        model_version_id=body.model_version_id,
        dataset_id=body.dataset_id,
        metric_config=body.metric_config,
        user_id=current_user.user_id,
    )
    return EvalTaskResponse.model_validate(task)


@router.get("/eval/tasks/{task_id}", response_model=EvalTaskResponse)
def get_eval_status(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询评测任务状态"""
    task = normal_eval_service.get_eval_task_status(db, task_id, current_user)
    return EvalTaskResponse.model_validate(task)


@router.get("/eval/tasks/{task_id}/metrics", response_model=EvalMetricsResponse)
def get_eval_metrics(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取评测核心指标"""
    result = normal_eval_service.get_eval_metrics(db, task_id, current_user)
    return EvalMetricsResponse(
        task_id=task_id,
        overall_metrics=result.overall_metrics,
        per_class_metrics=result.per_class_metrics,
        per_size_metrics=result.per_size_metrics,
        per_scene_metrics=result.per_scene_metrics,
    )


@router.get("/eval/tasks/{task_id}/pr-curve")
def get_pr_curve(
    task_id: int,
    class_id: int | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """PR 曲线数据"""
    return normal_eval_service.get_pr_curve(db, task_id, current_user, class_id)


@router.get("/eval/tasks/{task_id}/confusion")
def get_confusion(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """混淆矩阵"""
    return normal_eval_service.get_confusion_matrix(db, task_id, current_user)


@router.get("/eval/tasks/{task_id}/errors")
def get_errors(
    task_id: int,
    error_type: str | None = Query(None, description="fp | fn | tp"),
    class_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """错题本样本"""
    return normal_eval_service.get_error_samples(
        db,
        task_id=task_id,
        user=current_user,
        error_type=error_type,
        class_id=class_id,
        page=page,
        size=size,
    )


@router.post("/eval/compare")
def compare_models(
    body: EvalCompareRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """多模型对比（雷达图数据）"""
    return normal_eval_service.compare_models(db, body.model_ids, body.dataset_id)


@router.get("/eval/leaderboard")
def leaderboard(
    dataset_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """天梯榜"""
    return {"items": normal_eval_service.get_leaderboard(db, dataset_id)}


@router.get("/eval/history/{model_id}")
def history_trend(
    model_id: int,
    dataset_id: int = Query(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单模型历史趋势"""
    return {"items": normal_eval_service.get_history_trend(db, model_id, dataset_id)}
