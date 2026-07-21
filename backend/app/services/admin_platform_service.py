"""管理端平台服务 — 用户 / 审计 / 血缘 / 数据源 / GPU / 配置 / 天梯"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.redis import get_redis_client
from app.core.security import hash_password
from app.models.audit_log import AuditLog
from app.models.data_resource import DataResource
from app.models.data_source import DataSource
from app.models.dataset import Dataset
from app.models.dataset_item import DatasetItem
from app.models.infer_task import InferTask
from app.models.model_registry import Model
from app.models.model_version import ModelVersion
from app.models.user import User

CONFIG_KEY = "admin:platform_config"
WEIGHTS_KEY = "admin:eval_weights"
LOCKED_KEY = "admin:locked_testsets"
GPU_KEY = "admin:gpu_nodes"


def write_audit(
    db: Session,
    *,
    user_id: int,
    action: str,
    target_type: str,
    target_id: int,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> None:
    log = AuditLog(
        user_id=user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        before_state=before,
        after_state=after,
    )
    log.save(db)


# ──── 用户管理 ────


def list_users(
    db: Session,
    *,
    role: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[User], int]:
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter((User.username.ilike(like)) | (User.email.ilike(like)))
    total = q.count()
    rows = (
        q.order_by(User.user_id.asc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return rows, total


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    email: str,
    role: str,
    admin_id: int,
) -> User:
    if User.get_by_username(db, username):
        raise HTTPException(status_code=409, detail="用户名已存在")
    if User.get_by_email(db, email):
        raise HTTPException(status_code=409, detail="邮箱已存在")
    user = User(
        username=username,
        password_hash=hash_password(password),
        email=email,
        role=role,
        is_active=True,
    )
    user.save(db)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.create_user",
        target_type="user",
        target_id=user.user_id,
        after={"username": username, "role": role, "email": email},
    )
    return user


def set_user_role(db: Session, user_id: int, role: str, admin_id: int) -> User:
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    before = {"role": user.role}
    user.role = role
    user.save(db)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.set_role",
        target_type="user",
        target_id=user_id,
        before=before,
        after={"role": role},
    )
    return user


def set_user_status(
    db: Session, user_id: int, is_active: bool | None, admin_id: int
) -> User:
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user_id == admin_id and is_active is False:
        raise HTTPException(status_code=400, detail="不能停用当前登录管理员账号")
    before = {"is_active": user.is_active}
    if is_active is None:
        user.is_active = not user.is_active
    else:
        user.is_active = is_active
    user.save(db)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.toggle_status",
        target_type="user",
        target_id=user_id,
        before=before,
        after={"is_active": user.is_active},
    )
    return user


def list_audit_logs(
    db: Session,
    *,
    user_id: int | None = None,
    action: str | None = None,
    target_type: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[AuditLog], int]:
    return AuditLog.query(
        db,
        user_id=user_id,
        action=action,
        target_type=target_type,
        page=page,
        size=size,
    )


# ──── 血缘 ────


def get_lineage(db: Session, target_type: str, target_id: int) -> dict[str, Any]:
    t = (target_type or "").lower().strip()
    if t in {"model", "models"}:
        model = db.query(Model).filter(Model.model_id == target_id).first()
        if model is None:
            raise HTTPException(status_code=404, detail="模型不存在")
        versions = (
            db.query(ModelVersion)
            .filter(ModelVersion.model_id == target_id)
            .order_by(ModelVersion.created_at.asc())
            .all()
        )
        return {
            "target_type": "model",
            "target_id": target_id,
            "name": model.name,
            "nodes": [
                {
                    "version_id": v.version_id,
                    "version_number": v.version_number,
                    "parent_version_id": v.parent_version_id,
                    "trained_on_dataset_id": v.trained_on_dataset_id,
                    "change_note": v.change_note,
                    "created_at": v.created_at,
                }
                for v in versions
            ],
        }
    if t in {"dataset", "datasets"}:
        ds = db.query(Dataset).filter(Dataset.dataset_id == target_id).first()
        if ds is None:
            raise HTTPException(status_code=404, detail="数据集不存在")
        counts = DatasetItem.count_by_subset(db, target_id)
        return {
            "target_type": "dataset",
            "target_id": target_id,
            "name": ds.name,
            "version": ds.version,
            "status": ds.status,
            "subset_counts": counts,
            "filters": ds.filters,
        }
    if t in {"data", "resource", "data_resource"}:
        res = db.query(DataResource).filter(DataResource.resource_id == target_id).first()
        if res is None:
            raise HTTPException(status_code=404, detail="数据资源不存在")
        return {
            "target_type": "data_resource",
            "target_id": target_id,
            "name": res.name,
            "owner_id": res.owner_id,
            "modality": res.modality,
            "version": res.version,
            "meta_info": res.meta_info,
        }
    # 回退：审计轨迹
    logs, _ = AuditLog.query(db, target_type=t, page=1, size=50)
    filtered = [x for x in logs if x.target_id == target_id]
    return {
        "target_type": t,
        "target_id": target_id,
        "audit_trail": [
            {
                "log_id": x.log_id,
                "action": x.action,
                "user_id": x.user_id,
                "before_state": x.before_state,
                "after_state": x.after_state,
                "created_at": x.created_at,
            }
            for x in filtered
        ],
    }


# ──── 数据源 ────


def list_data_sources(db: Session) -> list[DataSource]:
    return db.query(DataSource).order_by(DataSource.source_id.desc()).all()


def create_data_source(
    db: Session,
    *,
    name: str,
    source_type: str,
    connection_info: dict[str, Any],
    modality: str,
    status: str,
    admin_id: int,
) -> DataSource:
    if DataSource.get_by_name(db, name):
        raise HTTPException(status_code=409, detail="数据源名称已存在")
    src = DataSource(
        name=name,
        source_type=source_type,
        connection_info=connection_info or {},
        modality=modality,
        status=status,
    )
    src.save(db)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.create_data_source",
        target_type="data_source",
        target_id=src.source_id,
        after={"name": name, "source_type": source_type},
    )
    return src


def _get_source(db: Session, source_id: int) -> DataSource:
    src = db.query(DataSource).filter(DataSource.source_id == source_id).first()
    if src is None:
        raise HTTPException(status_code=404, detail="数据源不存在")
    return src


def test_data_source(db: Session, source_id: int) -> dict[str, Any]:
    src = _get_source(db, source_id)
    info = src.connection_info or {}
    ok = False
    detail = ""
    if src.source_type == "local_dir":
        path = Path(str(info.get("path") or info.get("dir") or ""))
        ok = path.exists() and path.is_dir()
        detail = f"path exists={ok}: {path}"
    elif src.source_type in {"oss_bucket", "s3"}:
        endpoint = info.get("endpoint") or settings.MINIO_ENDPOINT
        bucket = info.get("bucket") or settings.MINIO_BUCKET
        try:
            from minio import Minio

            client = Minio(
                endpoint=str(endpoint).replace("http://", "").replace("https://", ""),
                access_key=info.get("access_key") or settings.MINIO_ACCESS_KEY,
                secret_key=info.get("secret_key") or settings.MINIO_SECRET_KEY,
                secure=bool(info.get("secure", settings.MINIO_SECURE)),
            )
            ok = client.bucket_exists(bucket)
            detail = f"bucket={bucket} exists={ok}"
        except Exception as exc:  # noqa: BLE001
            ok = False
            detail = str(exc)
    else:
        detail = f"未知 source_type={src.source_type}"
    return {
        "source_id": source_id,
        "ok": ok,
        "detail": detail,
        "status": "ok" if ok else "failed",
    }


def sync_data_source(
    db: Session, source_id: int, *, force: bool = False, limit: int = 100, admin_id: int
) -> dict[str, Any]:
    src = _get_source(db, source_id)
    info = src.connection_info or {}
    scanned = 0
    imported = 0
    warnings: list[str] = []

    if src.source_type == "local_dir":
        path = Path(str(info.get("path") or info.get("dir") or ""))
        if not path.exists():
            raise HTTPException(status_code=400, detail=f"本地目录不存在: {path}")
        patterns = ("*.jpg", "*.jpeg", "*.png", "*.bmp", "*.webp")
        files: list[Path] = []
        for pat in patterns:
            files.extend(path.glob(pat))
        files = sorted(files)[:limit]
        scanned = len(files)
        # 仅登记元信息到 connection_info.last_sync，真正入库走 /data/upload
        warnings.append("local_dir 同步仅扫描文件列表，上传请走 /api/data/upload")
        info["last_sync"] = {
            "at": datetime.utcnow().isoformat(),
            "scanned": scanned,
            "sample_files": [f.name for f in files[:10]],
            "force": force,
        }
        src.connection_info = info
        src.status = "active"
        src.save(db)
        imported = 0
    else:
        # 对象存储：探测对象数量（最多 list limit）
        try:
            from minio import Minio

            endpoint = info.get("endpoint") or settings.MINIO_ENDPOINT
            bucket = info.get("bucket") or settings.MINIO_BUCKET
            prefix = info.get("prefix") or ""
            client = Minio(
                endpoint=str(endpoint).replace("http://", "").replace("https://", ""),
                access_key=info.get("access_key") or settings.MINIO_ACCESS_KEY,
                secret_key=info.get("secret_key") or settings.MINIO_SECRET_KEY,
                secure=bool(info.get("secure", settings.MINIO_SECURE)),
            )
            objs = client.list_objects(bucket, prefix=prefix, recursive=True)
            names = []
            for obj in objs:
                scanned += 1
                names.append(obj.object_name)
                if scanned >= limit:
                    break
            info["last_sync"] = {
                "at": datetime.utcnow().isoformat(),
                "scanned": scanned,
                "sample_objects": names[:10],
                "force": force,
            }
            src.connection_info = info
            src.status = "active"
            src.save(db)
            warnings.append("对象存储同步仅完成枚举，导入资源请走上传/批处理任务")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"同步失败: {exc}") from exc

    write_audit(
        db,
        user_id=admin_id,
        action="admin.sync_data_source",
        target_type="data_source",
        target_id=source_id,
        after={"scanned": scanned, "imported": imported},
    )
    return {
        "source_id": source_id,
        "scanned": scanned,
        "imported": imported,
        "warnings": warnings,
    }


def configure_sensors(
    db: Session, source_id: int, sensors: dict[str, Any], admin_id: int
) -> DataSource:
    src = _get_source(db, source_id)
    info = dict(src.connection_info or {})
    info["sensors"] = sensors
    src.connection_info = info
    src.save(db)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.configure_sensors",
        target_type="data_source",
        target_id=source_id,
        after={"sensors": sensors},
    )
    return src


def clean_data_source(db: Session, source_id: int, admin_id: int) -> dict[str, Any]:
    src = _get_source(db, source_id)
    info = dict(src.connection_info or {})
    info.pop("last_sync", None)
    info["cleaned_at"] = datetime.utcnow().isoformat()
    src.connection_info = info
    src.status = "inactive"
    src.save(db)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.clean_data_source",
        target_type="data_source",
        target_id=source_id,
    )
    return {"source_id": source_id, "status": src.status, "message": "已清理同步缓存并停用"}


# ──── 推理审批 / GPU / 配置 ────


def list_pending_infer_tasks(db: Session) -> list[InferTask]:
    return (
        db.query(InferTask)
        .filter(InferTask.status.in_(["pending_approval", "queued", "failed"]))
        .order_by(InferTask.created_at.desc())
        .limit(100)
        .all()
    )


def approve_infer_task(db: Session, task_id: int, admin_id: int) -> InferTask:
    from app.tasks.infer_tasks import run_infer_task

    task = db.query(InferTask).filter(InferTask.task_id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="推理任务不存在")
    if task.status not in {"pending_approval", "failed", "queued"}:
        raise HTTPException(
            status_code=400,
            detail=f"当前状态 {task.status} 不可审批/重试",
        )
    task.status = "queued"
    task.save(db)
    db.commit()
    run_infer_task.delay(task.task_id)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.approve_infer",
        target_type="infer_task",
        target_id=task_id,
    )
    return task


def get_gpu_nodes() -> list[dict[str, Any]]:
    client = get_redis_client()
    raw = client.get(GPU_KEY)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    # 默认节点：反映训练槽位
    slot = client.get(settings.TRAIN_SLOT_KEY)
    return [
        {
            "node_id": "local-demo",
            "name": "本地 Demo 节点",
            "type": "cpu",
            "status": "busy" if slot else "idle",
            "slot": slot,
            "max_parallel": settings.TRAIN_MAX_PARALLEL,
            "train_image": settings.TRAIN_IMAGE,
            "executor": settings.TRAIN_EXECUTOR,
        }
    ]


def get_platform_config() -> dict[str, Any]:
    client = get_redis_client()
    raw = client.get(CONFIG_KEY)
    stored: dict[str, Any] = {}
    if raw:
        try:
            stored = json.loads(raw)
        except json.JSONDecodeError:
            stored = {}
    return {
        "train_max_parallel": stored.get(
            "train_max_parallel", settings.TRAIN_MAX_PARALLEL
        ),
        "train_timeout_sec": stored.get("train_timeout_sec", settings.TRAIN_TIMEOUT_SEC),
        "infer_require_approval": stored.get("infer_require_approval", False),
        "eval_auto_publish": stored.get("eval_auto_publish", False),
        "extra": stored.get("extra") or {},
        "defaults": {
            "TRAIN_EXECUTOR": settings.TRAIN_EXECUTOR,
            "TRAIN_IMAGE": settings.TRAIN_IMAGE,
        },
    }


def update_platform_config(payload: dict[str, Any], admin_id: int, db: Session) -> dict[str, Any]:
    client = get_redis_client()
    current = get_platform_config()
    for key in (
        "train_max_parallel",
        "train_timeout_sec",
        "infer_require_approval",
        "eval_auto_publish",
        "extra",
    ):
        if key in payload and payload[key] is not None:
            current[key] = payload[key]
    # 去掉 defaults 再存
    to_store = {k: v for k, v in current.items() if k != "defaults"}
    client.set(CONFIG_KEY, json.dumps(to_store, ensure_ascii=False))
    write_audit(
        db,
        user_id=admin_id,
        action="admin.update_config",
        target_type="platform",
        target_id=0,
        after=to_store,
    )
    return get_platform_config()


# ──── 天梯 / 试卷锁定 ────


def lock_testset(db: Session, dataset_id: int, admin_id: int) -> dict[str, Any]:
    ds = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if ds is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    if ds.status == "draft":
        ds.status = "frozen"
        ds.save(db)
    client = get_redis_client()
    locked = set()
    raw = client.get(LOCKED_KEY)
    if raw:
        try:
            locked = set(json.loads(raw))
        except json.JSONDecodeError:
            locked = set()
    locked.add(dataset_id)
    client.set(LOCKED_KEY, json.dumps(sorted(locked)))
    notes = dict(ds.review_notes or {})
    notes["testset_locked"] = True
    notes["locked_at"] = datetime.utcnow().isoformat()
    ds.review_notes = notes
    ds.save(db)
    write_audit(
        db,
        user_id=admin_id,
        action="admin.lock_testset",
        target_type="dataset",
        target_id=dataset_id,
    )
    return {
        "dataset_id": dataset_id,
        "status": ds.status,
        "locked": True,
        "message": "试卷已锁定（GT 对普通用户隐藏由评测侧读取 locked 标记）",
    }


def get_eval_weights() -> dict[str, Any]:
    client = get_redis_client()
    raw = client.get(WEIGHTS_KEY)
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    return {
        "night_map_weight": 0.3,
        "fps_weight": 0.1,
        "map50_weight": 0.4,
        "map5095_weight": 0.2,
        "categories": ["pole", "bridge", "building", "tree", "lamp"],
    }


def update_eval_weights(
    db: Session, payload: dict[str, Any], admin_id: int
) -> dict[str, Any]:
    current = get_eval_weights()
    current.update({k: v for k, v in payload.items() if v is not None})
    client = get_redis_client()
    client.set(WEIGHTS_KEY, json.dumps(current, ensure_ascii=False))
    write_audit(
        db,
        user_id=admin_id,
        action="admin.update_eval_weights",
        target_type="eval",
        target_id=0,
        after=current,
    )
    return current


def get_leaderboard_categories() -> dict[str, Any]:
    weights = get_eval_weights()
    return {
        "categories": weights.get("categories")
        or ["pole", "bridge", "building", "tree", "lamp"],
        "weights": {
            "night_map_weight": weights.get("night_map_weight", 0.3),
            "fps_weight": weights.get("fps_weight", 0.1),
            "map50_weight": weights.get("map50_weight", 0.4),
            "map5095_weight": weights.get("map5095_weight", 0.2),
        },
    }
