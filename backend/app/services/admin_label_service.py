"""标签体系管理 Service — 管理员 CRUD 标签体系"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.label_schema import LabelSchema


def list_label_schemas(
    db: Session,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询所有标签体系"""
    query = db.query(LabelSchema)
    total = query.count()
    schemas = (
        query.order_by(LabelSchema.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for s in schemas:
        items.append({
            "schema_id": s.schema_id,
            "name": s.name,
            "categories": s.categories,
            "version": s.version,
            "created_at": s.created_at,
            "updated_at": s.updated_at,
        })

    return items, total


def create_label_schema(
    db: Session,
    name: str,
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    """创建新标签体系"""
    schema = LabelSchema(name=name, categories=categories)
    schema.save(db)
    return {
        "schema_id": schema.schema_id,
        "name": schema.name,
        "categories": schema.categories,
        "version": schema.version,
        "created_at": schema.created_at,
        "updated_at": schema.updated_at,
    }


def add_category(
    db: Session,
    schema_id: int,
    category: dict[str, Any],
) -> dict[str, Any]:
    """向标签体系新增类别"""
    schema = LabelSchema.add_category(db, schema_id, category)
    if schema is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标签体系不存在"
        )
    return {
        "schema_id": schema.schema_id,
        "message": f"类别 '{category.get('name', category.get('id', ''))}' 已添加",
    }
