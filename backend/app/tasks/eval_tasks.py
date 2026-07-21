"""评测异步任务 — Phase3：真推理 + MetricsEngine。"""

from __future__ import annotations

from datetime import datetime

from app.core.database import SessionLocal
from app.models.eval_result import EvalResult
from app.models.eval_task import EvalTask
from app.services import eval_runtime
from app.tasks.celery_app import celery_app


@celery_app.task(name="tasks.eval.run", bind=True)
def run_eval_task(self, eval_task_id: int) -> dict:
    """评测 Worker：dataset 推理 → GT 对齐 → 写 EvalResult。"""
    db = SessionLocal()
    try:
        task = db.query(EvalTask).filter(EvalTask.task_id == eval_task_id).first()
        if task is None:
            return {"ok": False, "error": "eval task not found"}

        EvalTask.update_status(db, eval_task_id, "running")
        task.started_at = datetime.utcnow()
        task.save(db)
        db.commit()

        metrics = eval_runtime.run_eval_pipeline(
            db,
            model_id=task.model_id,
            dataset_id=task.dataset_id,
            metric_config=task.metric_config or {},
        )

        is_public = bool((task.metric_config or {}).get("is_public", False))
        existing = EvalResult.get_by_task(db, eval_task_id)
        payload = {
            "overall_metrics": metrics.get("overall_metrics") or {},
            "per_class_metrics": metrics.get("per_class_metrics"),
            "per_size_metrics": metrics.get("per_size_metrics"),
            "per_scene_metrics": metrics.get("per_scene_metrics") or {},
            "pr_curve_data": metrics.get("pr_curve_data"),
            "confusion_matrix": metrics.get("confusion_matrix"),
            "error_samples": metrics.get("error_samples"),
            "is_public": is_public,
        }
        # 把 labels 塞进 pr_curve_data 旁路字段，供 confusion API 使用
        pr = dict(payload["pr_curve_data"] or {})
        pr["confusion_labels"] = metrics.get("confusion_labels") or []
        pr["infer_summary"] = metrics.get("infer_summary") or {}
        payload["pr_curve_data"] = pr

        if existing is None:
            EvalResult.create(
                db,
                task_id=eval_task_id,
                model_id=task.model_id,
                dataset_id=task.dataset_id,
                **payload,
            )
        else:
            for k, v in payload.items():
                setattr(existing, k, v)
            existing.save(db)
        db.commit()

        task = db.query(EvalTask).filter(EvalTask.task_id == eval_task_id).first()
        if task is not None:
            task.status = "completed"
            task.finished_at = datetime.utcnow()
            task.save(db)
            db.commit()

        return {"ok": True, "status": "completed", "task_id": eval_task_id}

    except Exception as exc:
        db.rollback()
        EvalTask.update_status(db, eval_task_id, "failed")
        task = db.query(EvalTask).filter(EvalTask.task_id == eval_task_id).first()
        if task is not None:
            task.finished_at = datetime.utcnow()
            task.save(db)
            db.commit()
        return {"ok": False, "status": "failed", "error": str(exc)}
    finally:
        db.close()
