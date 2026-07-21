"""管理端路由 — /api/admin/*（训练审批 + 用户/数据源/配置/天梯）"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import require_role
from app.core.database import get_db
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserRoleUpdate,
    AdminUserStatusUpdate,
    AuditLogResponse,
    DataSourceCreate,
    DataSourceResponse,
    DataSourceSensorsUpdate,
    DataSourceSyncRequest,
    EvalWeightsUpdate,
    PlatformConfigUpdate,
)
from app.schemas.model import InferTaskResponse, TrainRejectRequest, TrainTaskResponse
from app.schemas.user import UserResponse
from app.services import admin_platform_service as platform
from app.services import normal_eval_service, normal_model_service

router = APIRouter(tags=["Admin"])


# ──── 用户管理 ────


@router.get("/admin/users")
def list_users(
    role: str | None = None,
    keyword: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    items, total = platform.list_users(
        db, role=role, keyword=keyword, page=page, size=size
    )
    return {
        "items": [UserResponse.model_validate(u) for u in items],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/admin/users", response_model=UserResponse, status_code=201)
def create_user(
    body: AdminUserCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = platform.create_user(
        db,
        username=body.username,
        password=body.password,
        email=body.email,
        role=body.role,
        admin_id=current_user.user_id,
    )
    db.commit()
    return UserResponse.model_validate(user)


@router.put("/admin/users/{user_id}/role", response_model=UserResponse)
def set_user_role(
    user_id: int,
    body: AdminUserRoleUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    user = platform.set_user_role(db, user_id, body.role, current_user.user_id)
    db.commit()
    return UserResponse.model_validate(user)


@router.put("/admin/users/{user_id}/status", response_model=UserResponse)
def toggle_user_status(
    user_id: int,
    body: AdminUserStatusUpdate | None = None,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    is_active = body.is_active if body else None
    user = platform.set_user_status(db, user_id, is_active, current_user.user_id)
    db.commit()
    return UserResponse.model_validate(user)


@router.get("/admin/audit-logs")
def list_audit_logs(
    user_id: int | None = None,
    action: str | None = None,
    target_type: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    items, total = platform.list_audit_logs(
        db,
        user_id=user_id,
        action=action,
        target_type=target_type,
        page=page,
        size=size,
    )
    return {
        "items": [AuditLogResponse.model_validate(x) for x in items],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/admin/lineage")
def get_lineage(
    target_type: str = Query(...),
    target_id: int = Query(...),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return platform.get_lineage(db, target_type, target_id)


# ──── 数据源 ────


@router.get("/admin/data-sources", response_model=list[DataSourceResponse])
def list_data_sources(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return [DataSourceResponse.model_validate(x) for x in platform.list_data_sources(db)]


@router.post("/admin/data-sources", response_model=DataSourceResponse, status_code=201)
def create_data_source(
    body: DataSourceCreate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    src = platform.create_data_source(
        db,
        name=body.name,
        source_type=body.source_type,
        connection_info=body.connection_info,
        modality=body.modality,
        status=body.status,
        admin_id=current_user.user_id,
    )
    db.commit()
    return DataSourceResponse.model_validate(src)


@router.post("/admin/data-sources/{source_id}/test")
def test_data_source(
    source_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    return platform.test_data_source(db, source_id)


@router.post("/admin/data-sources/{source_id}/sync")
def sync_data_source(
    source_id: int,
    body: DataSourceSyncRequest | None = None,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    payload = body or DataSourceSyncRequest()
    result = platform.sync_data_source(
        db,
        source_id,
        force=payload.force,
        limit=payload.limit,
        admin_id=current_user.user_id,
    )
    db.commit()
    return result


@router.put("/admin/data-sources/{source_id}/sensors", response_model=DataSourceResponse)
def configure_sensors(
    source_id: int,
    body: DataSourceSensorsUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    src = platform.configure_sensors(
        db, source_id, body.sensors, current_user.user_id
    )
    db.commit()
    return DataSourceResponse.model_validate(src)


@router.post("/admin/data-sources/{source_id}/clean")
def clean_data_source(
    source_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    result = platform.clean_data_source(db, source_id, current_user.user_id)
    db.commit()
    return result


# ──── 训练审批 ────


@router.get(
    "/admin/train-tasks/pending",
    response_model=list[TrainTaskResponse],
)
def list_pending_train_tasks(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """待审批训练任务列表"""
    tasks = normal_model_service.list_pending_train_tasks(db)
    return [TrainTaskResponse.model_validate(t) for t in tasks]


@router.post(
    "/admin/train-tasks/{task_id}/approve",
    response_model=TrainTaskResponse,
)
def approve_train_task(
    task_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """审批通过并自动入队 Celery"""
    task = normal_model_service.approve_train_task(db, task_id)
    return TrainTaskResponse.model_validate(task)


@router.post(
    "/admin/train-tasks/{task_id}/reject",
    response_model=TrainTaskResponse,
)
def reject_train_task(
    task_id: int,
    body: TrainRejectRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """拒绝训练申请"""
    task = normal_model_service.reject_train_task(db, task_id, body.reason)
    return TrainTaskResponse.model_validate(task)


@router.post(
    "/admin/train-tasks/{task_id}/terminate",
    response_model=TrainTaskResponse,
)
def terminate_train_task(
    task_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员强制终止训练"""
    task = normal_model_service.terminate_train_task(db, task_id)
    return TrainTaskResponse.model_validate(task)


# ──── 推理 / GPU / 配置 ────


@router.get("/admin/infer-tasks/pending", response_model=list[InferTaskResponse])
def list_pending_infer_tasks(
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    tasks = platform.list_pending_infer_tasks(db)
    return [InferTaskResponse.model_validate(t) for t in tasks]


@router.post("/admin/infer-tasks/{task_id}/approve", response_model=InferTaskResponse)
def approve_infer_task(
    task_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    task = platform.approve_infer_task(db, task_id, current_user.user_id)
    return InferTaskResponse.model_validate(task)


@router.get("/admin/gpu/nodes")
def get_gpu_nodes(
    current_user: User = Depends(require_role("admin")),
):
    return {"items": platform.get_gpu_nodes()}


@router.get("/admin/config")
def get_config(
    current_user: User = Depends(require_role("admin")),
):
    return platform.get_platform_config()


@router.put("/admin/config")
def update_config(
    body: PlatformConfigUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    result = platform.update_platform_config(
        body.model_dump(exclude_none=True), current_user.user_id, db
    )
    db.commit()
    return result


# ──── 天梯 ────


@router.post("/admin/datasets/{dataset_id}/lock")
def lock_testset(
    dataset_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    result = platform.lock_testset(db, dataset_id, current_user.user_id)
    db.commit()
    return result


@router.post("/admin/eval-results/{result_id}/invalidate")
def invalidate_eval_result(
    result_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """天梯下架：is_public=false"""
    result = normal_eval_service.invalidate_eval_result(db, result_id)
    return {
        "result_id": result.result_id,
        "is_public": result.is_public,
        "status": "invalidated",
    }


@router.post("/admin/eval-results/{result_id}/publish")
def publish_eval_result(
    result_id: int,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """纳入天梯：is_public=true"""
    result = normal_eval_service.publish_eval_result(db, result_id)
    return {
        "result_id": result.result_id,
        "is_public": result.is_public,
        "status": "published",
    }


@router.get("/admin/eval/weights")
def get_eval_weights(
    current_user: User = Depends(require_role("admin")),
):
    return platform.get_eval_weights()


@router.put("/admin/eval/weights")
def update_eval_weights(
    body: EvalWeightsUpdate,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    result = platform.update_eval_weights(
        db, body.model_dump(exclude_none=True), current_user.user_id
    )
    db.commit()
    return result


@router.get("/admin/eval/categories")
def get_leaderboard_categories(
    current_user: User = Depends(require_role("admin")),
):
    return platform.get_leaderboard_categories()
