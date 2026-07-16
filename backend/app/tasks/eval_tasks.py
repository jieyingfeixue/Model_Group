"""评测异步任务 — Phase1 占位：写入模拟指标，Phase3 再接 pycocotools / MetricsEngine"""

from __future__ import annotations

import time
from datetime import datetime

from app.core.database import SessionLocal
from app.models.eval_result import EvalResult
from app.models.eval_task import EvalTask
from app.tasks.celery_app import celery_app


@celery_app.task(name="tasks.eval.run", bind=True)
def run_eval_task(self, eval_task_id: int) -> dict:
    """评测任务占位 Worker。

    流程：queued → running → 写入 mock EvalResult → completed
    """
    db = SessionLocal()
    try:
        task = db.query(EvalTask).filter(EvalTask.task_id == eval_task_id).first()
        if task is None:
            return {"ok": False, "error": "eval task not found"}

        EvalTask.update_status(db, eval_task_id, "running")
        task.started_at = datetime.utcnow()
        task.save(db)
        db.commit()

        time.sleep(1)

        overall = {
            "mAP50": 0.72,
            "mAP50_95": 0.45,
            "precision": 0.81,
            "recall": 0.68,
            "f1": 0.74,
            "fps": 42.5,
            "note": "phase1 placeholder — replace with pycocotools in phase3",
        }

        existing = EvalResult.get_by_task(db, eval_task_id)
        if existing is None:
            EvalResult.create(
                db,
                task_id=eval_task_id,
                model_id=task.model_id,
                dataset_id=task.dataset_id,
                overall_metrics=overall,
                per_class_metrics=[
                    {"category_id": 1, "name": "电线杆", "ap50": 0.80},
                    {"category_id": 2, "name": "桥梁", "ap50": 0.65},
                ],
                per_size_metrics={"small": 0.31, "medium": 0.55, "large": 0.70},
                per_scene_metrics={"daytime": 0.74, "night": 0.58},
                pr_curve_data={
                    "points": [[0.0, 1.0], [0.1, 0.95], [0.5, 0.7], [1.0, 0.0]]
                },
                confusion_matrix=[[10, 1], [2, 8]],
                error_samples={
                    "fp": [],
                    "fn": [],
                    "tp": [],
                },
                is_public=False,
            )
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
        raise
    finally:
        db.close()
