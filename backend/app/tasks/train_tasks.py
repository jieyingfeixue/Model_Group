"""训练异步任务 — Phase1 占位：更新状态 + 模拟 progress，Phase2 再接 Docker 训练容器"""

from __future__ import annotations

import time
from datetime import datetime

from app.core.database import SessionLocal
from app.core.redis import get_redis_client
from app.models.train_task import TrainTask
from app.tasks.celery_app import celery_app


def _append_train_log(task_id: int, line: str) -> None:
    """训练日志写入 Redis List，供 GET /api/train/tasks/{id}/logs 读取。"""
    try:
        client = get_redis_client()
        key = f"train_logs:{task_id}"
        client.rpush(key, line)
        client.expire(key, 7 * 24 * 3600)
    except Exception:
        pass


@celery_app.task(name="tasks.train.run", bind=True)
def run_train_task(self, train_task_id: int) -> dict:
    """训练任务占位 Worker。

    流程：queued/approved → running → 写入模拟 progress → completed
    """
    db = SessionLocal()
    try:
        task = db.query(TrainTask).filter(TrainTask.task_id == train_task_id).first()
        if task is None:
            return {"ok": False, "error": "train task not found"}

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.save(db)
        db.commit()
        _append_train_log(train_task_id, f"[phase1] train task {train_task_id} started")

        # Phase1：用 sleep 模拟训练；Phase2 替换为 Docker 容器 + Loss 解析
        for epoch in range(1, 4):
            time.sleep(1)
            progress = {
                "epoch": epoch,
                "total_epochs": 3,
                "loss": round(1.0 / epoch, 4),
                "map50": round(0.2 * epoch, 4),
            }
            TrainTask.update_progress(db, train_task_id, progress)
            db.commit()
            _append_train_log(
                train_task_id,
                f"epoch {epoch} loss={progress['loss']} map50={progress['map50']}",
            )

        task = db.query(TrainTask).filter(TrainTask.task_id == train_task_id).first()
        if task is None:
            return {"ok": False, "error": "train task disappeared"}
        if task.status == "stopped":
            _append_train_log(train_task_id, "[phase1] train stopped by user")
            return {"ok": True, "status": "stopped"}

        task.status = "completed"
        task.finished_at = datetime.utcnow()
        task.save(db)
        db.commit()
        _append_train_log(train_task_id, "[phase1] train completed (placeholder)")
        return {"ok": True, "status": "completed", "task_id": train_task_id}

    except Exception as exc:
        db.rollback()
        task = db.query(TrainTask).filter(TrainTask.task_id == train_task_id).first()
        if task is not None:
            task.status = "failed"
            task.error_log = str(exc)
            task.finished_at = datetime.utcnow()
            task.save(db)
            db.commit()
        _append_train_log(train_task_id, f"[phase1] train failed: {exc}")
        raise
    finally:
        db.close()
