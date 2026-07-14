"""标签体系管理 Service — 管理员角色

所有函数对应设计报告 3.3.3 节 admin_label_service。
Model 方法已在第一阶段实现，此层做参数组装 + 权限校验 + 类别 ID 生成。
"""

import json

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.label_schema import LabelSchema
from app.schemas.label_schema import LabelSchemaImport


# ──── 内部辅助 ────


def _generate_category_id(db: Session, schema_id: int) -> str:
    """生成类别 ID：cat_001, cat_002, ... 自动递增"""
    schema = (
        db.query(LabelSchema)
        .filter(LabelSchema.schema_id == schema_id)
        .first()
    )
    if schema is None:
        return "cat_001"

    categories = schema.categories or []
    max_num = 0
    for cat in categories:
        cat_id = cat.get("id", "")
        if cat_id.startswith("cat_"):
            try:
                num = int(cat_id[4:])
                max_num = max(max_num, num)
            except ValueError:
                pass
    return f"cat_{max_num + 1:03d}"


def _find_schema_or_404(db: Session, schema_id: int) -> LabelSchema:
    """查询标签体系，不存在则 404"""
    schema = (
        db.query(LabelSchema)
        .filter(LabelSchema.schema_id == schema_id)
        .first()
    )
    if schema is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"标签体系 schema_id={schema_id} 不存在",
        )
    return schema


def _find_category_or_404(schema: LabelSchema, category_id: str) -> dict:
    """在 schema.categories 中查找类别，不存在则 404"""
    categories = schema.categories or []
    for cat in categories:
        if cat.get("id") == category_id:
            return cat
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"类别 category_id={category_id} 不存在",
    )


# ──── 业务函数 ────


def create_schema(db: Session, name: str) -> LabelSchema:
    """创建标签体系。初始 categories 为空数组。

    API: POST /api/admin/schemas
    """
    schema = LabelSchema(name=name, categories=[])
    schema.save(db)
    return schema


def add_category(
    db: Session,
    schema_id: int,
    name: str,
    shortcut: str | None = None,
    depth_required: bool = False,
    occlusion_required: bool = False,
    truncation_required: bool = False,
) -> LabelSchema:
    """新增类别。自动生成 category_id，status='active'。

    API: POST /api/admin/schemas/{id}/categories
    """
    schema = _find_schema_or_404(db, schema_id)

    category_id = _generate_category_id(db, schema_id)
    category_dict = {
        "id": category_id,
        "name": name,
        "shortcut": shortcut,
        "depth_required": depth_required,
        "occlusion_required": occlusion_required,
        "truncation_required": truncation_required,
        "status": "active",
    }

    result = LabelSchema.add_category(db, schema_id, category_dict)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="新增类别失败",
        )
    return result


def update_category(
    db: Session,
    schema_id: int,
    category_id: str,
    fields: dict,
) -> LabelSchema:
    """修改类别属性。只更新传入的非 None 字段。

    API: PUT /api/admin/schemas/{id}/categories/{cat_id}
    """
    schema = _find_schema_or_404(db, schema_id)
    _find_category_or_404(schema, category_id)

    # 只保留非 None 字段
    update_fields = {k: v for k, v in fields.items() if v is not None}

    if not update_fields:
        return schema

    result = LabelSchema.update_category(db, schema_id, category_id, update_fields)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="修改类别失败",
        )
    return result


def deprecate_category(
    db: Session,
    schema_id: int,
    category_id: str,
    reason: str,
    alternative_id: str | None = None,
) -> LabelSchema:
    """废弃类别。设 status='deprecated' 并写入废弃原因和替代类别。

    API: DELETE /api/admin/schemas/{id}/categories/{cat_id}
    """
    schema = _find_schema_or_404(db, schema_id)
    cat = _find_category_or_404(schema, category_id)

    if cat.get("status") == "deprecated":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"类别 {category_id} 已被废弃，无需重复操作",
        )

    # 先调用 Model 方法设 status='deprecated'
    LabelSchema.deprecate_category(db, schema_id, category_id)

    # 再追加废弃原因和替代类别
    deprecate_fields = {
        "deprecate_reason": reason,
    }
    if alternative_id:
        deprecate_fields["alternative_id"] = alternative_id

    result = LabelSchema.update_category(
        db, schema_id, category_id, deprecate_fields
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="废弃类别失败",
        )
    return result


def export_schema(db: Session, schema_id: int) -> str:
    """导出标签体系为 JSON 字符串。

    API: GET /api/admin/schemas/{id}/export
    """
    _find_schema_or_404(db, schema_id)
    return LabelSchema.export_to_json(db, schema_id)


def import_schema(db: Session, name: str, json_str: str) -> LabelSchema:
    """从 JSON 字符串校验并导入标签体系。

    校验流程：
    1. 解析 JSON → Pydantic LabelSchemaImport 校验
    2. 写入 LabelSchema 表

    API: POST /api/admin/schemas/import
    """
    # 1. Pydantic 校验
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"JSON 格式错误: {e.msg}",
        ) from e

    try:
        LabelSchemaImport.model_validate(data)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"标签体系格式校验失败: {e}",
        ) from e

    # 2. 写入
    # 将 Pydantic 模型转为 dict 列表
    categories_raw = data.get("categories", [])
    schema = LabelSchema(name=name, categories=categories_raw)
    schema.save(db)
    return schema


def get_active_categories(db: Session, schema_id: int) -> list[dict]:
    """获取标签体系的活跃类别列表（排除已废弃的）。

    API: GET /api/schemas/{id}/categories
    """
    _find_schema_or_404(db, schema_id)
    return LabelSchema.get_active_categories(db, schema_id)
