"""训练异步任务 — Phase2：Docker/本地 demo 训练 + Loss/进度 + 新版本入库。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis import get_redis_client
from app.core.storage import download_file, upload_file
from app.models.dataset import Dataset
from app.models.model_registry import Model
from app.models.model_version import ModelVersion
from app.models.train_task import TrainTask
from app.services import train_executor
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


def _should_stop(db, task_id: int) -> bool:
    if train_executor.is_stop_requested(task_id):
        return True
    task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
    return task is not None and task.status == "stopped"


def _publish_new_version(
    db,
    task: TrainTask,
    weight_bytes: bytes,
    progress: dict[str, Any] | None,
) -> ModelVersion:
    """训练成功：权重进 MinIO，新建带血缘的 model_versions。"""
    model = db.query(Model).filter(Model.model_id == task.model_id).first()
    if model is None:
        raise RuntimeError(f"model {task.model_id} missing")

    ds_ver = None
    if task.dataset_id:
        dataset = db.query(Dataset).filter(Dataset.dataset_id == task.dataset_id).first()
        if dataset is not None:
            ds_ver = dataset.version

    object_name = (
        f"models/{model.owner_id or 0}/{model.model_id}/"
        f"train_{task.task_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.pt"
    )
    file_path = upload_file(weight_bytes, object_name, content_type="application/octet-stream")

    version = ModelVersion.create_version(
        db,
        model_id=model.model_id,
        file_path=file_path,
        note=f"train task #{task.task_id}",
        parent_version_id=task.model_version_id,
        trained_on_dataset_id=task.dataset_id,
        trained_on_dataset_version=ds_ver,
        metrics_snapshot=progress,
    )
    model.file_path = file_path
    if model.status != "deprecated":
        model.status = "available"
    model.save(db)
    return version


@celery_app.task(name="tasks.train.run", bind=True, max_retries=240)
def run_train_task(self, train_task_id: int) -> dict:
    """训练 Worker。

    流程：抢全局槽位 → 准备目录/配置 → Docker/local trainer
         → 解析 PROGRESS → 成功则上传权重并 create_version
    """
    db = SessionLocal()
    slot_held = False
    try:
        task = db.query(TrainTask).filter(TrainTask.task_id == train_task_id).first()
        if task is None:
            return {"ok": False, "error": "train task not found"}
        if task.status == "stopped":
            return {"ok": True, "status": "stopped"}
        if task.status not in {"queued", "approved"}:
            return {"ok": False, "error": f"unexpected status {task.status}"}

        if not train_executor.acquire_train_slot(train_task_id):
            _append_train_log(
                train_task_id, "[phase2] GPU/train slot busy, requeue in 15s"
            )
            raise self.retry(countdown=15)

        slot_held = True
        train_executor.clear_stop_flag(train_task_id)

        task.status = "running"
        task.started_at = datetime.utcnow()
        task.finished_at = None
        task.error_log = None
        task.progress = {"epoch": 0, "total_epochs": 0, "loss": None, "map50": None}
        task.save(db)
        db.commit()
        _append_train_log(train_task_id, f"[phase2] train task {train_task_id} started")

        jdir = train_executor.job_dir(train_task_id)
        output_name = "weights.pt"
        if (settings.TRAIN_EXECUTOR or "docker").lower() == "local":
            output_path = str((jdir / "output" / output_name).resolve())
        else:
            output_path = f"/workspace/output/{output_name}"

        base_path = None
        if task.model_version_id:
            ver = ModelVersion.get_by_id(db, task.model_version_id)
            if ver is not None:
                base_path = ver.file_path
        if base_path is None:
            model = db.query(Model).filter(Model.model_id == task.model_id).first()
            if model is not None:
                base_path = model.file_path
        if base_path:
            try:
                raw = download_file(base_path)
                (jdir / "input" / "base_weights.bin").write_bytes(raw)
                _append_train_log(train_task_id, f"[phase2] loaded base weights {base_path}")
            except Exception as exc:
                _append_train_log(
                    train_task_id, f"[phase2] skip base weights ({exc})"
                )

        cfg = dict(task.config or {})
        epochs = int(cfg.get("epochs", 5))
        sleep_sec = float(cfg.get("sleep_sec", 1.0))
        train_executor.write_train_config(
            train_task_id,
            {
                "train_task_id": train_task_id,
                "model_id": task.model_id,
                "dataset_id": task.dataset_id,
                "epochs": epochs,
                "sleep_sec": sleep_sec,
                "batch_size": cfg.get("batch_size", 16),
                "lr": cfg.get("lr", 0.001),
                "optimizer": cfg.get("optimizer", "adam"),
                "gpu_config": task.gpu_config or {},
                "output_path": output_path,
            },
        )

        last_progress: dict[str, Any] | None = None

        def on_log(line: str) -> None:
            _append_train_log(train_task_id, line)

        def on_progress(progress: dict[str, Any]) -> None:
            nonlocal last_progress
            last_progress = progress
            TrainTask.update_progress(db, train_task_id, progress)
            db.commit()

        def should_stop() -> bool:
            return _should_stop(db, train_task_id)

        result = train_executor.run_trainer(
            train_task_id,
            on_log=on_log,
            on_progress=on_progress,
            should_stop=should_stop,
        )

        task = db.query(TrainTask).filter(TrainTask.task_id == train_task_id).first()
        if task is None:
            return {"ok": False, "error": "train task disappeared"}

        if result.status == "stopped" or task.status == "stopped":
            task.status = "stopped"
            task.finished_at = datetime.utcnow()
            task.error_log = result.error or task.error_log or "stopped"
            if last_progress:
                task.progress = last_progress
            task.save(db)
            db.commit()
            _append_train_log(train_task_id, "[phase2] train stopped")
            return {"ok": True, "status": "stopped"}

        if not result.ok or result.output_weight_path is None:
            task.status = "failed"
            task.finished_at = datetime.utcnow()
            task.error_log = result.error or "train failed"
            if last_progress:
                task.progress = last_progress
            task.save(db)
            db.commit()
            _append_train_log(train_task_id, f"[phase2] train failed: {task.error_log}")
            return {"ok": False, "status": "failed", "error": task.error_log}

        weight_bytes = result.output_weight_path.read_bytes()
        # 保留训练前的基准版本作为血缘父节点
        parent_version_id = task.model_version_id
        new_version = _publish_new_version(
            db, task, weight_bytes, last_progress or result.progress
        )
        # create_version 已用 parent；这里再保证父版本正确
        if parent_version_id and new_version.parent_version_id != parent_version_id:
            new_version.parent_version_id = parent_version_id
            new_version.save(db)

        task.status = "completed"
        task.finished_at = datetime.utcnow()
        task.progress = last_progress or result.progress
        task.error_log = None
        task.model_version_id = new_version.version_id
        task.save(db)
        db.commit()
        _append_train_log(
            train_task_id,
            f"[phase2] completed → version {new_version.version_number} "
            f"(id={new_version.version_id})",
        )
        return {
            "ok": True,
            "status": "completed",
            "task_id": train_task_id,
            "version_id": new_version.version_id,
            "version_number": new_version.version_number,
        }

    except Exception as exc:
        from celery.exceptions import MaxRetriesExceededError, Retry

        if isinstance(exc, Retry):
            raise
        if isinstance(exc, MaxRetriesExceededError):
            db.rollback()
            task = db.query(TrainTask).filter(TrainTask.task_id == train_task_id).first()
            if task is not None:
                task.status = "failed"
                task.error_log = "train slot wait timeout"
                task.finished_at = datetime.utcnow()
                task.save(db)
                db.commit()
            return {"ok": False, "error": "slot wait timeout"}
        db.rollback()
        task = db.query(TrainTask).filter(TrainTask.task_id == train_task_id).first()
        if task is not None and task.status != "stopped":
            task.status = "failed"
            task.error_log = str(exc)
            task.finished_at = datetime.utcnow()
            task.save(db)
            db.commit()
        _append_train_log(train_task_id, f"[phase2] train failed: {exc}")
        raise
    finally:
        if slot_held:
            train_executor.release_train_slot(train_task_id)
        try:
            train_executor.cleanup_job_dir(train_task_id)
        except Exception:
            pass
        db.close()
