"""推理异步任务 — Phase3 Step2：单图 / 整集 ONNX；支持 pt→onnx 转换。"""

from __future__ import annotations

from datetime import datetime

from app.core.database import SessionLocal
from app.models.infer_task import InferTask
from app.services import infer_runtime
from app.tasks.celery_app import celery_app


@celery_app.task(name="tasks.infer.run", bind=True)
def run_infer_task(self, infer_task_id: int) -> dict:
    """推理 Worker：image_id 单图，或 dataset_id 整集批量。"""
    db = SessionLocal()
    try:
        task = db.query(InferTask).filter(InferTask.task_id == infer_task_id).first()
        if task is None:
            return {"ok": False, "error": "infer task not found"}

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.results = {
            "total_images": 0,
            "completed": 0,
            "failed_images": 0,
            "detections": [],
            "note": "running",
        }
        task.save(db)
        db.commit()

        def on_progress(progress: dict) -> None:
            t = db.query(InferTask).filter(InferTask.task_id == infer_task_id).first()
            if t is None:
                return
            base = dict(t.results or {})
            base.update(progress)
            # 批量过程中先不带全量 detections，避免频繁写巨 JSON；结束时再写全量
            t.results = base
            t.save(db)
            db.commit()

        if task.image_id is not None:
            results = infer_runtime.run_single_image_infer(
                db,
                model_id=task.model_id,
                image_id=task.image_id,
            )
        elif task.dataset_id is not None:
            results = infer_runtime.run_dataset_infer(
                db,
                model_id=task.model_id,
                dataset_id=task.dataset_id,
                on_progress=on_progress,
            )
        else:
            raise ValueError("image_id 与 dataset_id 至少需要一个")

        task = db.query(InferTask).filter(InferTask.task_id == infer_task_id).first()
        if task is None:
            return {"ok": False, "error": "infer task disappeared"}

        task.results = results
        # 全部图片都失败才标 failed；部分失败仍 completed，由 failed_images 体现
        if results.get("total_images", 0) > 0 and results.get("failed_images") == results.get(
            "total_images"
        ):
            task.status = "failed"
        else:
            task.status = "completed"
        task.finished_at = datetime.utcnow()
        task.save(db)
        db.commit()
        return {"ok": True, "status": task.status, "task_id": infer_task_id}

    except Exception as exc:
        db.rollback()
        task = db.query(InferTask).filter(InferTask.task_id == infer_task_id).first()
        if task is not None:
            task.status = "failed"
            task.results = {"error": str(exc)}
            task.finished_at = datetime.utcnow()
            task.save(db)
            db.commit()
        return {"ok": False, "status": "failed", "error": str(exc)}
    finally:
        db.close()
