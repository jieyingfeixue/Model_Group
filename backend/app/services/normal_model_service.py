"""模型管理 Service — register / list / train / infer（对齐设计报告四行约定）"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.core.storage import upload_file
from app.models.dataset import Dataset
from app.models.infer_task import InferTask
from app.models.model_registry import Model
from app.models.model_version import ModelVersion
from app.models.train_task import TrainTask
from app.models.user import User

ALLOWED_FRAMEWORKS = {"pytorch", "tensorflow", "onnx"}
FRAMEWORK_EXTENSIONS: dict[str, set[str]] = {
    "pytorch": {".pt", ".pth"},
    "tensorflow": {".pb", ".h5", ".keras"},
    "onnx": {".onnx"},
}


def _file_suffix(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _validate_weight_file(filename: str | None, framework: str) -> str:
    """校验框架与权重扩展名。返回规范化后缀。"""
    if framework not in ALLOWED_FRAMEWORKS:
        raise HTTPException(
            status_code=400, detail=f"framework 必须为 {sorted(ALLOWED_FRAMEWORKS)}"
        )
    suffix = _file_suffix(filename)
    allowed = FRAMEWORK_EXTENSIONS[framework]
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"{framework} 权重扩展名必须为 {sorted(allowed)}，收到: {suffix or '(无)'}",
        )
    return suffix


def _normalize_model_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """规范化注册元信息：保留 input_size / modalities / categories。"""
    meta = dict(metadata or {})
    modalities = meta.get("modalities")
    if modalities is None:
        meta["modalities"] = []
    elif isinstance(modalities, str):
        meta["modalities"] = [modalities]
    elif not isinstance(modalities, list):
        raise HTTPException(status_code=400, detail="meta_info.modalities 须为数组")

    categories = meta.get("categories")
    if categories is None:
        meta["categories"] = []
    elif not isinstance(categories, list):
        raise HTTPException(status_code=400, detail="meta_info.categories 须为数组")

    if "input_size" in meta and meta["input_size"] is not None:
        size = meta["input_size"]
        if not (
            isinstance(size, list)
            and len(size) == 2
            and all(isinstance(x, int) and x > 0 for x in size)
        ):
            raise HTTPException(
                status_code=400, detail="meta_info.input_size 须为 [H, W] 正整数数组"
            )
    return meta


def _assert_can_view_model(model: Model, user: User) -> None:
    if (
        not model.is_public
        and not model.is_baseline
        and model.owner_id != user.user_id
        and user.role != "admin"
    ):
        raise HTTPException(status_code=403, detail="无权查看该模型")


def _assert_owner(model: Model, owner_id: int) -> None:
    if model.owner_id != owner_id:
        raise HTTPException(status_code=403, detail="仅拥有者可操作该模型")


def _resolve_dataset_binding(
    db: Session, dataset_id: int | None
) -> tuple[int | None, str | None]:
    if dataset_id is None:
        return None, None
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(status_code=404, detail="绑定的数据集不存在")
    return dataset.dataset_id, dataset.version


def register_model(
    db: Session,
    name: str,
    framework: str,
    file: UploadFile,
    metadata: dict[str, Any],
    owner_id: int,
) -> Model:
    """注册模型。校验权重扩展名与元信息后上传 MinIO，入库并创建初始版本。

    register_model(db, name, framework, file, metadata, owner_id): Model
    校验 → 读取文件 → MinIO → Model.register(status=available) → ModelVersion.create_version
    依赖 Model：Model.register(), ModelVersion.create_version()
    API: POST /api/models
    """
    suffix = _validate_weight_file(file.filename, framework)
    meta_info = _normalize_model_metadata(metadata)

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="模型文件为空")

    object_name = f"models/{owner_id}/{uuid.uuid4().hex}{suffix}"
    file_path = upload_file(
        file_bytes,
        object_name,
        content_type=file.content_type or "application/octet-stream",
    )

    # Phase2：扩展名校验通过即 available；Phase3 再接入 ONNX 结构化校验
    model = Model.register(
        db,
        name=name.strip(),
        owner_id=owner_id,
        framework=framework,
        file_path=file_path,
        meta_info=meta_info,
        is_baseline=False,
        is_public=True,
        status="available",
    )
    ModelVersion.create_version(
        db, model.model_id, file_path, note="initial", parent_version_id=None
    )
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
    _assert_can_view_model(model, user)
    versions = ModelVersion.list_by_model(db, model_id)
    return model, versions


def get_model_version(
    db: Session, model_id: int, version_id: int, user: User
) -> ModelVersion:
    """查看单个版本详情。

    get_model_version(db, model_id, version_id): ModelVersion
    依赖 Model：ModelVersion.get_by_id()
    API: GET /api/models/{id}/versions/{version_id}
    """
    model, _ = get_model_detail(db, model_id, user)
    version = ModelVersion.get_by_id(db, version_id)
    if version is None or version.model_id != model.model_id:
        raise HTTPException(status_code=404, detail="版本不存在")
    return version


def get_model_lineage(db: Session, model_id: int, user: User) -> dict[str, Any]:
    """返回版本血缘：扁平列表 + 树形结构。

    get_model_lineage(db, model_id): {model_id, versions, tree}
    依赖 Model：ModelVersion.list_by_model()
    API: GET /api/models/{id}/lineage
    """
    model, versions = get_model_detail(db, model_id, user)
    # list_by_model 是倒序；建树用正序更稳
    ordered = sorted(versions, key=lambda v: v.version_id)

    nodes: dict[int, dict[str, Any]] = {}
    for v in ordered:
        nodes[v.version_id] = {
            "version_id": v.version_id,
            "version_number": v.version_number,
            "parent_version_id": v.parent_version_id,
            "trained_on_dataset_id": v.trained_on_dataset_id,
            "trained_on_dataset_version": v.trained_on_dataset_version,
            "change_note": v.change_note,
            "metrics_snapshot": v.metrics_snapshot,
            "created_at": v.created_at,
            "children": [],
        }

    roots: list[dict[str, Any]] = []
    for v in ordered:
        node = nodes[v.version_id]
        parent_id = v.parent_version_id
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)

    return {
        "model_id": model.model_id,
        "versions": versions,
        "tree": roots,
    }


def upload_model_version(
    db: Session,
    model_id: int,
    file: UploadFile,
    version_note: str,
    owner_id: int,
    trained_on_dataset_id: int | None = None,
    parent_version_id: int | None = None,
) -> ModelVersion:
    """上传新版本。权重存入 MinIO，生成语义化版本号并挂到父版本。

    upload_model_version(...): ModelVersion
    校验权限/扩展名 → MinIO → ModelVersion.create_version → 更新 models.file_path
    依赖 Model：ModelVersion.create_version()
    API: POST /api/models/{id}/versions
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise HTTPException(status_code=404, detail="模型不存在")
    _assert_owner(model, owner_id)
    if model.status == "deprecated":
        raise HTTPException(status_code=400, detail="已废弃模型不可上传新版本")
    if model.is_baseline:
        raise HTTPException(status_code=403, detail="基线模型只读，不可上传新版本")

    suffix = _validate_weight_file(file.filename, model.framework)
    ds_id, ds_ver = _resolve_dataset_binding(db, trained_on_dataset_id)

    if parent_version_id is not None:
        parent = ModelVersion.get_by_id(db, parent_version_id)
        if parent is None or parent.model_id != model_id:
            raise HTTPException(status_code=400, detail="parent_version_id 不属于该模型")

    file_bytes = file.file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="模型文件为空")

    object_name = f"models/{owner_id}/{model_id}/{uuid.uuid4().hex}{suffix}"
    file_path = upload_file(
        file_bytes,
        object_name,
        content_type=file.content_type or "application/octet-stream",
    )

    version = ModelVersion.create_version(
        db,
        model_id,
        file_path,
        note=version_note or "",
        parent_version_id=parent_version_id,
        trained_on_dataset_id=ds_id,
        trained_on_dataset_version=ds_ver,
    )
    model.file_path = file_path
    model.status = "available"
    model.save(db)
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
    _assert_owner(model, owner_id)
    if model.is_baseline:
        raise HTTPException(status_code=403, detail="基线模型可见性由平台管理")
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
    if model.is_baseline and user.role != "admin":
        raise HTTPException(status_code=403, detail="基线模型仅管理员可废弃")
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
    model_version_id: int | None = None,
) -> TrainTask:
    """提交训练任务。校验数据集冻结后创建，status=pending_approval。

    submit_train_task(...): TrainTask
    绑定基准版本（可指定，默认最新）→ TrainTask.create(pending_approval)
    依赖 Model：Dataset / ModelVersion / TrainTask.create()
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

    if model_version_id is not None:
        base_version = ModelVersion.get_by_id(db, model_version_id)
        if base_version is None or base_version.model_id != model_id:
            raise HTTPException(status_code=400, detail="model_version_id 不属于该模型")
    else:
        base_version = ModelVersion.get_latest(db, model_id)
        model_version_id = base_version.version_id if base_version else None

    return TrainTask.create(
        db,
        model_id=model_id,
        model_version_id=model_version_id,
        dataset_id=dataset_id,
        config=config or {},
        gpu_config=gpu_config or {},
        status="pending_approval",
        created_by=user_id,
    )


def list_pending_train_tasks(db: Session) -> list[TrainTask]:
    """管理员：列出待审批训练任务。

    list_pending_train_tasks(db): List[TrainTask]
    依赖 Model：TrainTask.get_pending_approval()
    API: GET /api/admin/train-tasks/pending
    """
    return TrainTask.get_pending_approval(db)


def approve_train_task(db: Session, task_id: int) -> TrainTask:
    """管理员审批通过：pending_approval → approved → queued，并投递 Celery。

    approve_train_task(db, task_id): TrainTask
    TrainTask 状态流转 → tasks.train.run.delay
    API: POST /api/admin/train-tasks/{id}/approve
    """
    from app.tasks.train_tasks import run_train_task

    task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.status != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail=f"仅 pending_approval 可审批，当前为 {task.status}",
        )

    task.status = "approved"
    task.error_log = None
    task.save(db)
    db.commit()

    task.status = "queued"
    task.save(db)
    db.commit()
    run_train_task.delay(task_id)
    return task


def reject_train_task(db: Session, task_id: int, reason: str) -> TrainTask:
    """管理员拒绝训练申请。

    reject_train_task(db, task_id, reason): TrainTask
    status → rejected，原因写入 error_log
    API: POST /api/admin/train-tasks/{id}/reject
    """
    task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.status != "pending_approval":
        raise HTTPException(
            status_code=400,
            detail=f"仅 pending_approval 可拒绝，当前为 {task.status}",
        )

    task.status = "rejected"
    task.error_log = reason.strip()
    task.finished_at = datetime.utcnow()
    task.save(db)
    return task


def terminate_train_task(db: Session, task_id: int) -> TrainTask:
    """管理员强制终止训练（排队中 / 运行中 / 待审均可）。

    terminate_train_task(db, task_id): TrainTask
    依赖 Model：TrainTask；并尝试杀掉训练容器
    API: POST /api/admin/train-tasks/{id}/terminate
    """
    from app.services import train_executor

    task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.status not in {
        "pending_approval",
        "approved",
        "queued",
        "running",
    }:
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {task.status} 不可强制终止",
        )

    train_executor.mark_stop_requested(task_id)
    if task.status == "running":
        train_executor.kill_train_container(task_id)

    task.status = "stopped"
    task.finished_at = datetime.utcnow()
    if not task.error_log:
        task.error_log = "terminated by admin"
    task.save(db)
    return task


def enqueue_train_task(db: Session, task_id: int, user: User) -> TrainTask:
    """管理员手动入队（重试）。Phase2 起仅 admin；待审任务请走 approve。

    enqueue_train_task(db, task_id): TrainTask
    TrainTask.update_status → tasks.train.run.delay
    API: POST /api/train/tasks/{id}/enqueue
    """
    from app.tasks.train_tasks import run_train_task

    if user.role != "admin":
        raise HTTPException(
            status_code=403,
            detail="enqueue 仅管理员可用；待审任务请走 /api/admin/train-tasks/{id}/approve",
        )

    task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="训练任务不存在")
    if task.status not in {"approved", "failed", "stopped"}:
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {task.status} 不可入队（待审请先审批）",
        )

    task.status = "queued"
    task.error_log = None
    task.finished_at = None
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
    依赖 Model：TrainTask.update_status()；并尝试杀掉训练容器
    API: POST /api/train/tasks/{id}/stop
    """
    from app.services import train_executor

    task = get_train_task_detail(db, task_id, user)
    if task.status not in {"queued", "running", "approved", "pending_approval"}:
        raise HTTPException(status_code=400, detail=f"当前状态 {task.status} 不可终止")

    train_executor.mark_stop_requested(task_id)
    if task.status == "running":
        train_executor.kill_train_container(task_id)

    task.status = "stopped"
    task.finished_at = datetime.utcnow()
    if not task.error_log:
        task.error_log = "stopped by user"
    task.save(db)
    return task


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
    coord: str = "both",
) -> InferTask:
    """查看推理结果。按类别/置信度过滤，并可投影坐标空间。

    get_infer_results(..., coord=norm|pixel|both): InferTask 视图
    依赖 Model：InferTask；坐标：eval_engine.coords.project_boxes_for_api
    API: GET /api/infer/tasks/{id}/results
    """
    from app.eval_engine.coords import project_boxes_for_api

    if coord not in {"norm", "pixel", "both"}:
        raise HTTPException(status_code=400, detail="coord 须为 norm|pixel|both")

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
        boxes = project_boxes_for_api(boxes, coord=coord)  # type: ignore[arg-type]
        filtered.append({**det, "boxes": boxes})
    results["detections"] = filtered
    results["coord_space"] = coord
    # 不写回 DB，仅作为返回视图
    task.results = results
    return task


def visualize_infer(db: Session, task_id: int, image_id: int, user: User) -> bytes:
    """渲染推理结果：尽量拉原图并用像素框绘制；失败则占位图。

    visualize_infer(db, task_id, image_id): bytes
    API: GET /api/infer/tasks/{id}/visualize/{image_id}
    """
    from io import BytesIO

    from PIL import Image, ImageDraw

    from app.core.storage import download_file
    from app.models.data_resource import DataResource

    task = get_infer_results(db, task_id, user, min_confidence=0.0, coord="both")
    results = task.results or {}
    detections = results.get("detections") or []
    target = next((d for d in detections if d.get("image_id") == image_id), None)
    boxes = (target or {}).get("boxes") or []

    image: Image.Image
    try:
        resource = (
            db.query(DataResource).filter(DataResource.resource_id == image_id).first()
        )
        if resource is None:
            raise FileNotFoundError("image missing")
        raw = download_file(resource.file_path)
        image = Image.open(BytesIO(raw)).convert("RGB")
    except Exception:
        w = int((target or {}).get("image_width") or 640)
        h = int((target or {}).get("image_height") or 480)
        image = Image.new("RGB", (w, h), (40, 40, 40))

    draw = ImageDraw.Draw(image)
    for b in boxes:
        xyxy = b.get("xyxy_pixel")
        if not xyxy or len(xyxy) != 4:
            continue
        x1, y1, x2, y2 = map(float, xyxy)
        draw.rectangle((x1, y1, x2, y2), outline=(0, 255, 0), width=3)
        label = f"c{b.get('category_id')} {float(b.get('confidence', 0)):.2f}"
        draw.text((x1 + 2, max(0, y1 - 12)), label, fill=(0, 255, 0))

    draw.text((8, 8), f"infer#{task_id} image#{image_id}", fill=(255, 255, 0))
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
