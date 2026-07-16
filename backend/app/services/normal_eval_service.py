"""评测分析 Service — 对齐设计报告 normal_eval_service"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.eval_result import EvalResult
from app.models.eval_task import EvalTask
from app.models.model_registry import Model
from app.models.user import User


def submit_eval_task(
    db: Session,
    model_id: int,
    model_version_id: int | None,
    dataset_id: int,
    metric_config: dict[str, Any],
    user_id: int,
) -> EvalTask:
    """发起评测任务。校验数据集冻结后入队 Celery。

    submit_eval_task(db, model_id, model_version_id, dataset_id, metric_config, user_id): EvalTask
    依赖 Model：Dataset(session.get), EvalTask.create()
    API: POST /api/eval/tasks
    """
    from app.tasks.eval_tasks import run_eval_task

    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.status != "frozen":
        raise HTTPException(status_code=400, detail="仅冻结(frozen)数据集可用于评测")

    task = EvalTask.create(
        db,
        model_id=model_id,
        model_version_id=model_version_id,
        dataset_id=dataset_id,
        metric_config=metric_config
        or {"iou_thresholds": [0.5, 0.75], "max_detections": 100},
        status="queued",
        created_by=user_id,
    )
    db.commit()  # 确保 Worker 能读到任务记录
    run_eval_task.delay(task.task_id)
    return task


def get_eval_task_status(db: Session, task_id: int, user: User) -> EvalTask:
    """查询评测状态。

    get_eval_task_status(db, task_id): EvalTask
    API: GET /api/eval/tasks/{id}
    """
    task = db.query(EvalTask).filter(EvalTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="评测任务不存在")
    if task.created_by != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权查看该评测任务")
    return task


def get_eval_metrics(db: Session, task_id: int, user: User) -> EvalResult:
    """获取评测指标。

    get_eval_metrics(db, task_id): EvalResult
    依赖 Model：EvalResult.get_by_task()
    API: GET /api/eval/tasks/{id}/metrics
    """
    get_eval_task_status(db, task_id, user)
    result = EvalResult.get_by_task(db, task_id)
    if result is None:
        raise HTTPException(status_code=404, detail="评测结果尚未生成")
    return result


def get_pr_curve(
    db: Session, task_id: int, user: User, class_id: int | None = None
) -> dict[str, Any]:
    """获取 PR 曲线数据。

    get_pr_curve(db, task_id, class_id): List[(float,float)]
    API: GET /api/eval/tasks/{id}/pr-curve
    """
    result = get_eval_metrics(db, task_id, user)
    data = result.pr_curve_data or {}
    # Phase1：统一返回 points；Phase3 按 class_id 分流
    points = data.get("points") or data.get(str(class_id)) or []
    return {"points": points, "class_id": class_id}


def get_confusion_matrix(db: Session, task_id: int, user: User) -> dict[str, Any]:
    """获取混淆矩阵。

    get_confusion_matrix(db, task_id): List[List[int]]
    API: GET /api/eval/tasks/{id}/confusion
    """
    result = get_eval_metrics(db, task_id, user)
    return {
        "matrix": result.confusion_matrix or [],
        "labels": ["电线杆", "桥梁"],
    }


def get_error_samples(
    db: Session,
    task_id: int,
    user: User,
    error_type: str | None = None,
    class_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> dict[str, Any]:
    """获取错误样本。

    get_error_samples(db, task_id, error_type, class_id, page, size): dict
    API: GET /api/eval/tasks/{id}/errors
    """
    result = get_eval_metrics(db, task_id, user)
    samples = result.error_samples or {}
    if error_type:
        items = samples.get(error_type) or []
    else:
        items = []
        for key in ("fp", "fn", "tp"):
            items.extend(samples.get(key) or [])

    if class_id is not None:
        items = [s for s in items if s.get("category_id") == class_id]

    total = len(items)
    start = (page - 1) * size
    return {"items": items[start : start + size], "total": total, "page": page, "size": size}


def compare_models(
    db: Session, model_ids: list[int], dataset_id: int
) -> dict[str, Any]:
    """多模型对比。最多 5 个模型，同一数据集六维雷达图数据。

    compare_models(db, model_ids, dataset_id): dict
    依赖 Model：EvalResult.get_latest_by_model_dataset()
    API: POST /api/eval/compare
    """
    axes = ["mAP50", "mAP50_95", "precision", "recall", "fps", "lightweight"]
    series = []
    for mid in model_ids[:5]:
        model = db.query(Model).filter(Model.model_id == mid).first()
        result = EvalResult.get_latest_by_model_dataset(db, mid, dataset_id)
        metrics = (result.overall_metrics if result else {}) or {}
        values = [
            float(metrics.get("mAP50", 0)),
            float(metrics.get("mAP50_95", 0)),
            float(metrics.get("precision", 0)),
            float(metrics.get("recall", 0)),
            min(float(metrics.get("fps", 0)) / 100.0, 1.0),
            float(metrics.get("lightweight", 0.5)),
        ]
        series.append(
            {
                "model_id": mid,
                "name": model.name if model else f"model-{mid}",
                "values": values,
            }
        )
    return {"axes": axes, "series": series}


def get_leaderboard(db: Session, dataset_id: int) -> list[dict[str, Any]]:
    """查看排行榜。仅公开评测结果，按 mAP 降序。

    get_leaderboard(db, dataset_id): List[dict]
    依赖 Model：EvalResult.list_public_by_dataset()
    API: GET /api/eval/leaderboard
    """
    results = EvalResult.list_public_by_dataset(db, dataset_id)
    board = []
    for r in results:
        model = db.query(Model).filter(Model.model_id == r.model_id).first()
        metrics = r.overall_metrics or {}
        board.append(
            {
                "result_id": r.result_id,
                "model_id": r.model_id,
                "model_name": model.name if model else None,
                "dataset_id": r.dataset_id,
                "mAP50": metrics.get("mAP50"),
                "mAP50_95": metrics.get("mAP50_95"),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
        )
    board.sort(key=lambda x: (x.get("mAP50") or 0), reverse=True)
    return board


def get_history_trend(
    db: Session, model_id: int, dataset_id: int
) -> list[dict[str, Any]]:
    """查看历史趋势。同模型各版本指标；mAP 倒退标记 regression。

    get_history_trend(db, model_id, dataset_id): List[dict]
    依赖 Model：EvalResult.get_trend_by_model()
    API: GET /api/eval/history/{model_id}
    """
    if hasattr(EvalResult, "get_trend_by_model"):
        rows = EvalResult.get_trend_by_model(db, model_id, dataset_id)  # type: ignore[attr-defined]
    else:
        rows = (
            db.query(EvalResult)
            .filter(EvalResult.model_id == model_id, EvalResult.dataset_id == dataset_id)
            .order_by(EvalResult.created_at.asc())
            .all()
        )

    trend: list[dict[str, Any]] = []
    prev_map: float | None = None
    for r in rows:
        metrics = r.overall_metrics or {}
        current = float(metrics.get("mAP50") or 0)
        item = {
            "result_id": r.result_id,
            "task_id": r.task_id,
            "mAP50": current,
            "mAP50_95": metrics.get("mAP50_95"),
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "regression": bool(prev_map is not None and current < prev_map),
        }
        trend.append(item)
        prev_map = current
    return trend
