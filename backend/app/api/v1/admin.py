"""管理路由 — /api/admin/*"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.user import User
from app.schemas.admin import (
    AdminUserCreateRequest,
    AdminUserListResponse,
    AdminUserResponse,
    EvalResultInvalidateRequest,
    InferTaskPendingListResponse,
    LeaderboardGovernanceResponse,
    RoleUpdateRequest,
    StatusUpdateRequest,
)
from app.schemas.label_schema import (
    AddCategoryRequest,
    CategoryResponse,
    LabelSchemaCreateRequest,
    LabelSchemaListResponse,
    LabelSchemaResponse,
)
from app.services import admin_platform_service, admin_label_service

router = APIRouter(prefix="/admin", tags=["Admin"])

# ════════════════════════════════════════════════════════════
#  用户管理
# ════════════════════════════════════════════════════════════

# ──── GET /api/admin/users ────

@router.get("/users", response_model=AdminUserListResponse)
def list_users(
    role: str | None = Query(None, description="按角色筛选: admin / reviewer / normal"),
    is_active: bool | None = Query(None, description="按激活状态筛选"),
    keyword: str | None = Query(None, description="用户名或邮箱关键字"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员查看用户列表"""
    items, total = admin_platform_service.list_users(
        db, role=role, is_active=is_active, keyword=keyword, page=page, size=size
    )
    return AdminUserListResponse(
        items=[AdminUserResponse(**it) for it in items],
        total=total,
        page=page,
        size=size,
    )


# ──── POST /api/admin/users ────

@router.post("/users", response_model=AdminUserResponse, status_code=201)
def create_user(
    body: AdminUserCreateRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员创建新用户"""
    result = admin_platform_service.create_user(
        db,
        username=body.username,
        email=body.email,
        password=body.password,
        role=body.role,
    )
    return AdminUserResponse(**result)


# ──── PUT /api/admin/users/{user_id}/role ────

@router.put("/users/{user_id}/role")
def set_user_role(
    user_id: int,
    body: RoleUpdateRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员修改用户角色"""
    return admin_platform_service.set_user_role(db, user_id, body.role)


# ──── PUT /api/admin/users/{user_id}/status ────

@router.put("/users/{user_id}/status")
def set_user_status(
    user_id: int,
    body: StatusUpdateRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员冻结/解冻用户"""
    return admin_platform_service.set_user_status(db, user_id, body.is_active)


# ════════════════════════════════════════════════════════════
#  标签体系管理
# ════════════════════════════════════════════════════════════

# ──── GET /api/admin/labels ────

@router.get("/labels", response_model=LabelSchemaListResponse)
def list_labels(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员查看标签体系列表"""
    items, total = admin_label_service.list_label_schemas(db, page=page, size=size)
    return LabelSchemaListResponse(
        items=[LabelSchemaResponse(**it) for it in items],
        total=total,
        page=page,
        size=size,
    )


# ──── POST /api/admin/labels ────

@router.post("/labels", response_model=LabelSchemaResponse, status_code=201)
def create_label_schema(
    body: LabelSchemaCreateRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员新增标签体系"""
    categories_dicts = [cat.model_dump() for cat in body.categories]
    result = admin_label_service.create_label_schema(db, body.name, categories_dicts)
    return LabelSchemaResponse(**result)


# ──── POST /api/admin/labels/{schema_id}/categories ────

@router.post("/labels/{schema_id}/categories", response_model=CategoryResponse)
def add_label_category(
    schema_id: int,
    body: AddCategoryRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员向标签体系新增类别"""
    result = admin_label_service.add_category(db, schema_id, body.category.model_dump())
    return CategoryResponse(**result)


# ════════════════════════════════════════════════════════════
#  §11 扩展：推理审批 / 天梯治理 / 作弊下架
# ════════════════════════════════════════════════════════════

# ──── GET /api/admin/infer-tasks/pending ────

@router.get("/infer-tasks/pending", response_model=InferTaskPendingListResponse)
def list_pending_infer_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员查看待审批推理任务列表"""
    items, total = admin_platform_service.list_pending_infer_tasks(
        db, page=page, size=size
    )
    return InferTaskPendingListResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )


# ──── GET /api/admin/eval/leaderboard ────

@router.get("/eval/leaderboard", response_model=LeaderboardGovernanceResponse)
def list_eval_governance(
    dataset_id: int | None = Query(None, description="按数据集筛选"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员天梯治理：查看所有评测结果（含非公开）"""
    items, total = admin_platform_service.list_leaderboard_governance(
        db, dataset_id=dataset_id, page=page, size=size
    )
    return LeaderboardGovernanceResponse(
        items=items,
        total=total,
        page=page,
        size=size,
    )


# ──── POST /api/admin/eval-results/{result_id}/invalidate ────

@router.post("/eval-results/{result_id}/invalidate")
def invalidate_eval_result(
    result_id: int,
    body: EvalResultInvalidateRequest,
    current_user: User = Depends(require_role("admin")),
    db: Session = Depends(get_db),
):
    """管理员作弊下架：将评测结果标记无效，从排行榜移除"""
    return admin_platform_service.invalidate_eval_result(db, result_id, body.reason)
