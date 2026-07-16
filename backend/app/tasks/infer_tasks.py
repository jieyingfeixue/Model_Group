"""推理异步任务 — Phase1 占位：写入模拟检测结果，Phase3 再接 ONNX Runtime"""

from __future__ import annotations

import time
from datetime import datetime

from app.core.database import SessionLocal
from app.models.infer_task import InferTask
from app.tasks.celery_app import celery_app


@celery_app.task(name="tasks.infer.run", bind=True)
def run_infer_task(self, infer_task_id: int) -> dict:
    """推理任务占位 Worker。

    流程：queued → running → 写入 mock results → completed
    """
    db = SessionLocal()
    try:
        task = db.query(InferTask).filter(InferTask.task_id == infer_task_id).first()
        if task is None:
            return {"ok": False, "error": "infer task not found"}

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.save(db)
        db.commit()

        time.sleep(1)

        image_id = task.image_id or 0
        mock_results = {
            "total_images": 1 if task.image_id else 0,
            "completed": 1 if task.image_id else 0,
            "avg_time": 0.12,
            "note": "phase1 placeholder — replace with ONNX Runtime in phase3",
            "detections": [
                {
                    "image_id": image_id,
                    "boxes": [
                        {
                            "x": 0.12,
                            "y": 0.18,
                            "w": 0.15,
                            "h": 0.25,
                            "category_id": 1,
                            "confidence": 0.91,
                            "depth": 12.5,
                        }
                    ],
                }
            ]
            if task.image_id
            else [],
        }

        task = db.query(InferTask).filter(InferTask.task_id == infer_task_id).first()
        if task is None:
            return {"ok": False, "error": "infer task disappeared"}

        task.results = mock_results
        task.status = "completed"
        task.finished_at = datetime.utcnow()
        task.save(db)
        db.commit()
        return {"ok": True, "status": "completed", "task_id": infer_task_id}

    except Exception as exc:
        db.rollback()
        task = db.query(InferTask).filter(InferTask.task_id == infer_task_id).first()
        if task is not None:
            task.status = "failed"
            task.results = {"error": str(exc)}
            task.finished_at = datetime.utcnow()
            task.save(db)
            db.commit()
        raise
    finally:
        db.close()
