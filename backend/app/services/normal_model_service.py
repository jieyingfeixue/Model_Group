"""模型管理 Service — register / list / train / infer（对齐设计报告四行约定）"""

from __future__ import annotations

import json
import uuid
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.core.storage import upload_file
from app.models.dataset import Dataset
from app.models.infer_task import InferTask
from app.models.model_registry import Model
from app.models.model_version import ModelVersion
from app.models.train_task import TrainTask
from app.models.user import User


def register_model(
    db: Session,
    name: str,
    framework: str,
    file: UploadFile,
    metadata: dict[str, Any],
    owner_id: int,
) -> Model:
    """注册模型。上传权重到 MinIO，校验后入库，并创建初始版本。

    register_model(db, name, framework, file, metadata, owner_id): Model
    读取文件 → MinIO 存储 → Model.register → ModelVersion.create_version
    依赖 Model：Model.register(), ModelVersion.create_version()
    API: POST /api/models
    """
    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="模型文件为空")

    allowed = {"pytorch", "tensorflow", "onnx"}
    if framework not in allowed:
        raise HTTPException(status_code=400, detail=f"framework 必须为 {allowed}")

    suffix = ""
    if file.filename and "." in file.filename:
        suffix = "." + file.filename.rsplit(".", 1)[-1].lower()
    object_name = f"models/{owner_id}/{uuid.uuid4().hex}{suffix}"
    file_path = upload_file(
        file_bytes,
        object_name,
        content_type=file.content_type or "application/octet-stream",
    )

    # Phase1：暂标 available；Phase3 增加 ONNX 校验 / PyTorch→ONNX 转换后再改状态
    model = Model.register(
        db,
        name=name,
        owner_id=owner_id,
        framework=framework,
        file_path=file_path,
        meta_info=metadata or {},
        is_baseline=False,
        is_public=True,
        status="available",
    )
    ModelVersion.create_version(db, model.model_id, file_path, note="initial")
    return model


def list_my_models(
    db: Session,
    owner_id: int,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[Model], int]:
    """查看我的模型。按拥有者查询，支持按框架和状态筛选。

    list_my_models(db, owner_id, filters): (List[Model], total)
    依赖 Model：Model.get_by_owner()
    API: GET /api/models
    """
    items = Model.get_by_owner(db, owner_id, filters)
    total = len(items)
    start = (page - 1) * size
    return items[start : start + size], total


def get_model_detail(db: Session, model_id: int, user: User) -> tuple[Model, list[ModelVersion]]:
    """查看模型详情。返回模型基本信息及所有历史版本列表。

    get_model_detail(db, model_id): Model + versions
    依赖 Model：session.get / ModelVersion.list_by_model()
    API: GET /api/models/{id}
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")

    if (
        not model.is_public
        and not model.is_baseline
        and model.owner_id != user.user_id
        and user.role != "admin"
    ):
        raise HTTPException(status_code=403, detail="无权查看该模型")

    versions = ModelVersion.list_by_model(db, model_id)
    return model, versions


def upload_model_version(
    db: Session,
    model_id: int,
    file: UploadFile,
    version_note: str,
    owner_id: int,
    trained_on_dataset_id: int | None = None,
) -> ModelVersion:
    """上传新版本。权重存入 MinIO，生成语义化版本号。

    upload_model_version(db, model_id, file, version_note): ModelVersion
    依赖 Model：ModelVersion.create_version()
    API: POST /api/models/{id}/versions
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model.owner_id != owner_id:
        raise HTTPException(status_code=403, detail="仅拥有者可上传新版本")

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="模型文件为空")

    suffix = ""
    if file.filename and "." in file.filename:
        suffix = "." + file.filename.rsplit(".", 1)[-1].lower()
    object_name = f"models/{owner_id}/{model_id}/{uuid.uuid4().hex}{suffix}"
    file_path = upload_file(
        file_bytes,
        object_name,
        content_type=file.content_type or "application/octet-stream",
    )

    version = ModelVersion.create_version(db, model_id, file_path, note=version_note or "")
    if trained_on_dataset_id is not None:
        version.trained_on_dataset_id = trained_on_dataset_id
        version.save(db)
    return version


def set_model_visibility(db: Session, model_id: int, is_public: bool, owner_id: int) -> Model:
    """设置模型可见性。

    set_model_visibility(db, model_id, is_public): void
    依赖 Model：Model.set_visibility()
    API: PUT /api/models/{id}/visibility
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model.owner_id != owner_id:
        raise HTTPException(status_code=403, detail="仅拥有者可修改可见性")
    updated = Model.set_visibility(db, model_id, is_public)
    assert updated is not None
    return updated


def deprecate_model(db: Session, model_id: int, user: User) -> None:
    """废弃模型。status → deprecated。

    deprecate_model(db, model_id): void
    依赖 Model：Model.set_status()
    API: DELETE /api/models/{id}
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model.owner_id != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="仅拥有者或管理员可废弃模型")
    Model.set_status(db, model_id, "deprecated")


def list_baselines(db: Session) -> list[Model]:
    """列出基线模型。

    list_baselines(db): List[Model]
    依赖 Model：Model.list_baselines()
    API: GET /api/models/baselines
    """
    return Model.list_baselines(db)


def submit_train_task(
    db: Session,
    model_id: int,
    dataset_id: int,
    config: dict[str, Any],
    gpu_config: dict[str, Any],
    user_id: int,
) -> TrainTask:
    """提交训练任务。校验数据集冻结后创建，status=pending_approval。

    submit_train_task(db, model_id, dataset_id, config, gpu_config, user_id): TrainTask
    依赖 Model：Dataset(session.get), TrainTask.create()
    API: POST /api/train/tasks
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model.status == "deprecated":
        raise HTTPException(status_code=400, detail="已废弃模型不可训练")

    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if dataset.status != "frozen":
        raise HTTPException(
            status_code=400,
            detail="仅冻结(frozen)数据集可用于训练",
        )

    return TrainTask.create(
        db,
        model_id=model_id,
        dataset_id=dataset_id,
        config=config or {},
        gpu_config=gpu_config or {},
        status="pending_approval",
        created_by=user_id,
    )


def enqueue_train_task(db: Session, task_id: int, user: User) -> TrainTask:
    """Phase1 辅助：将训练任务入队并投递 Celery（后续由管理员审批接口替代）。

    enqueue_train_task(db, task_id): TrainTask
    TrainTask.update_status → tasks.train.run.delay
    API: POST /api/train/tasks/{id}/enqueue
    """
    from app.tasks.train_tasks import run_train_task

    task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.created_by != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权操作该训练任务")
    if task.status not in {"pending_approval", "approved", "failed", "stopped"}:
        raise HTTPException(status_code=400, detail=f"当前状态 {task.status} 不可入队")

    task.status = "queued"
    task.error_log = None
    task.save(db)
    db.commit()  # 确保 Worker 能读到已入队记录
    run_train_task.delay(task_id)
    return task


def get_train_task_detail(db: Session, task_id: int, user: User) -> TrainTask:
    """查看训练进度。

    get_train_task_detail(db, task_id): TrainTask
    依赖 Model：TrainTask(session.get)
    API: GET /api/train/tasks/{id}
    """
    task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.created_by != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权查看该训练任务")
    return task


def stop_train_task(db: Session, task_id: int, user: User) -> TrainTask:
    """终止训练。

    stop_train_task(db, task_id): void
    依赖 Model：TrainTask.update_status()
    API: POST /api/train/tasks/{id}/stop
    """
    task = get_train_task_detail(db, task_id, user)
    if task.status not in {"queued", "running", "approved", "pending_approval"}:
        raise HTTPException(status_code=400, detail=f"当前状态 {task.status} 不可终止")
    updated = TrainTask.update_status(db, task_id, "stopped")
    assert updated is not None
    return updated


def get_train_logs(task_id: int) -> list[str]:
    """从 Redis 读取训练日志流。

    get_train_logs(task_id): List[str]
    API: GET /api/train/tasks/{id}/logs
    """
    try:
        client = get_redis_client()
        return client.lrange(f"train_logs:{task_id}", 0, -1)
    except Exception:
        return []


def submit_infer(
    db: Session,
    model_id: int,
    dataset_id: int | None,
    image_id: int | None,
    user_id: int,
) -> InferTask:
    """提交推理任务。创建记录后 Celery 异步执行。

    submit_infer(db, model_id, dataset_id, image_id, user_id): InferTask
    InferTask.create → tasks.infer.run.delay
    API: POST /api/infer/tasks
    """
    from app.tasks.infer_tasks import run_infer_task

    if dataset_id is None and image_id is None:
        raise HTTPException(status_code=400, detail="dataset_id 与 image_id 需至少提供一个")

    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    if model.status != "available" and not model.is_baseline:
        raise HTTPException(status_code=400, detail="模型当前不可用于推理")

    task = InferTask.create(
        db,
        model_id=model_id,
        dataset_id=dataset_id,
        image_id=image_id,
        status="queued",
        created_by=user_id,
    )
    db.commit()  # 确保 Worker 能读到任务记录
    run_infer_task.delay(task.task_id)
    return task


def get_infer_results(
    db: Session,
    task_id: int,
    user: User,
    class_filter: int | None = None,
    min_confidence: float = 0.1,
) -> InferTask:
    """查看推理结果。按类别和置信度过滤（Phase1 仅过滤 mock boxes）。

    get_infer_results(db, task_id, class_filter, min_confidence): JSON
    依赖 Model：InferTask(session.get)
    API: GET /api/infer/tasks/{id}/results
    """
    task = db.query(InferTask).filter(InferTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="推理任务不存在")
    if task.created_by != user.user_id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权查看该推理任务")

    if not task.results:
        return task

    results = dict(task.results)
    detections = results.get("detections") or []
    filtered = []
    for det in detections:
        boxes = det.get("boxes") or []
        boxes = [
            b
            for b in boxes
            if b.get("confidence", 0) >= min_confidence
            and (class_filter is None or b.get("category_id") == class_filter)
        ]
        filtered.append({**det, "boxes": boxes})
    results["detections"] = filtered
    # 不写回 DB，仅作为返回视图
    task.results = results
    return task


def visualize_infer(db: Session, task_id: int, image_id: int, user: User) -> bytes:
    """渲染推理结果。Phase1 返回占位 JPEG；Phase3 用 Pillow 画框。

    visualize_infer(db, task_id, image_id): bytes
    API: GET /api/infer/tasks/{id}/visualize/{image_id}
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    get_infer_results(db, task_id, user)

    image = Image.new("RGB", (640, 480), (40, 40, 40))
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 60, 280, 280), outline=(0, 255, 0), width=3)
    draw.text((90, 40), f"infer#{task_id} image#{image_id} (phase1 stub)", fill=(255, 255, 255))
    buf = BytesIO()
    image.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def parse_metadata_form(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"metadata 不是合法 JSON: {exc}") from exc
