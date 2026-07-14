"""标签体系管理路由 — /api/admin/schemas/* 和 /api/schemas/*"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.user import User
from app.schemas.label_schema import (
    CategoryCreate,
    CategoryDeprecateRequest,
    CategoryUpdate,
    LabelSchemaCreate,
    LabelSchemaImport,
    LabelSchemaResponse,
)
from app.services import admin_label_service

router = APIRouter(tags=["Admin — Labels"])

# 管理员鉴权依赖
_admin = Depends(require_role("admin"))


# ──── /api/admin/schemas ────


@router.post(
    "/admin/schemas",
    response_model=LabelSchemaResponse,
    status_code=201,
    dependencies=[_admin],
)
def create_schema(
    body: LabelSchemaCreate,
    db: Session = Depends(get_db),
):
    """创建标签体系（管理员）。"""
    schema = admin_label_service.create_schema(db, name=body.name)
    return LabelSchemaResponse.model_validate(schema)


@router.post(
    "/admin/schemas/import",
    response_model=LabelSchemaResponse,
    status_code=201,
    dependencies=[_admin],
)
def import_schema(
    body: LabelSchemaImport,
    db: Session = Depends(get_db),
):
    """导入标签体系 JSON（管理员）。Pydantic 自动校验 JSON Schema。"""
    import json

    json_str = json.dumps(body.model_dump(), ensure_ascii=False)
    schema = admin_label_service.import_schema(
        db, name=body.name, json_str=json_str
    )
    return LabelSchemaResponse.model_validate(schema)


@router.get(
    "/admin/schemas/{schema_id}/export",
    dependencies=[_admin],
)
def export_schema(
    schema_id: int,
    db: Session = Depends(get_db),
):
    """导出标签体系为 JSON 字符串（管理员）。"""
    json_str = admin_label_service.export_schema(db, schema_id=schema_id)
    import json as _json

    return _json.loads(json_str)


# ──── /api/admin/schemas/{id}/categories ────


@router.post(
    "/admin/schemas/{schema_id}/categories",
    response_model=LabelSchemaResponse,
    status_code=201,
    dependencies=[_admin],
)
def add_category(
    schema_id: int,
    body: CategoryCreate,
    db: Session = Depends(get_db),
):
    """新增类别（管理员）。自动生成 category_id（cat_001...）。"""
    schema = admin_label_service.add_category(
        db,
        schema_id=schema_id,
        name=body.name,
        shortcut=body.shortcut,
        depth_required=body.depth_required,
        occlusion_required=body.occlusion_required,
        truncation_required=body.truncation_required,
    )
    return LabelSchemaResponse.model_validate(schema)


@router.put(
    "/admin/schemas/{schema_id}/categories/{category_id}",
    response_model=LabelSchemaResponse,
    dependencies=[_admin],
)
def update_category(
    schema_id: int,
    category_id: str,
    body: CategoryUpdate,
    db: Session = Depends(get_db),
):
    """修改类别属性（管理员）。只更新传入的非空字段。"""
    schema = admin_label_service.update_category(
        db,
        schema_id=schema_id,
        category_id=category_id,
        fields=body.model_dump(exclude_none=True),
    )
    return LabelSchemaResponse.model_validate(schema)


@router.delete(
    "/admin/schemas/{schema_id}/categories/{category_id}",
    response_model=LabelSchemaResponse,
    dependencies=[_admin],
)
def deprecate_category(
    schema_id: int,
    category_id: str,
    body: CategoryDeprecateRequest,
    db: Session = Depends(get_db),
):
    """废弃类别（管理员）。设 status='deprecated'，记录原因和替代类别。"""
    schema = admin_label_service.deprecate_category(
        db,
        schema_id=schema_id,
        category_id=category_id,
        reason=body.reason,
        alternative_id=body.alternative_id,
    )
    return LabelSchemaResponse.model_validate(schema)


# ──── /api/schemas/{id}/categories（普通用户可用） ────


@router.get(
    "/schemas/{schema_id}/categories",
    dependencies=[Depends(get_current_user)],
)
def get_active_categories(
    schema_id: int,
    db: Session = Depends(get_db),
):
    """获取标签体系活跃类别列表（任意登录用户）。排除 status='deprecated' 的类别。"""
    categories = admin_label_service.get_active_categories(db, schema_id=schema_id)
    return {"schema_id": schema_id, "categories": categories, "count": len(categories)}
