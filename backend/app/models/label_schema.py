"""LabelSchema ORM Model — 对应 label_schemas 表"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class LabelSchema(Base):
    __tablename__ = "label_schemas"

    schema_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    categories: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def get_active(cls, db: Session) -> LabelSchema | None:
        """获取当前活跃版本（最新版本号）"""
        return (
            db.query(cls)
            .order_by(cls.version.desc())
            .first()
        )

    @staticmethod
    def add_category(
        db: Session, schema_id: int, category_dict: dict[str, Any]
    ) -> LabelSchema | None:
        """新增类别，version+1，返回更新后的 LabelSchema"""
        schema = db.query(LabelSchema).filter(
            LabelSchema.schema_id == schema_id
        ).first()
        if schema is None:
            return None
        categories = list(schema.categories) if schema.categories else []
        categories.append(category_dict)
        schema.categories = categories
        schema.version += 1
        schema.save(db)
        return schema

    @staticmethod
    def update_category(
        db: Session, schema_id: int, cat_id: str, fields: dict[str, Any]
    ) -> LabelSchema | None:
        """修改类别属性，返回更新后的 LabelSchema"""
        schema = db.query(LabelSchema).filter(
            LabelSchema.schema_id == schema_id
        ).first()
        if schema is None:
            return None
        categories = list(schema.categories) if schema.categories else []
        for cat in categories:
            if cat.get("id") == cat_id:
                cat.update(fields)
                break
        schema.categories = categories
        schema.save(db)
        return schema

    @staticmethod
    def deprecate_category(
        db: Session, schema_id: int, cat_id: str
    ) -> LabelSchema | None:
        """废弃类别（设 status='deprecated'），返回更新后的 LabelSchema"""
        return LabelSchema.update_category(
            db, schema_id, cat_id, {"status": "deprecated"}
        )

    @classmethod
    def get_active_categories(
        cls, db: Session, schema_id: int
    ) -> list[dict[str, Any]]:
        """仅返回 status=active 的类别"""
        schema = db.query(cls).filter(cls.schema_id == schema_id).first()
        if schema is None or not schema.categories:
            return []
        return [c for c in schema.categories if c.get("status") != "deprecated"]

    @staticmethod
    def export_to_json(db: Session, schema_id: int) -> str:
        """导出标签体系为 JSON 字符串"""
        schema = db.query(LabelSchema).filter(
            LabelSchema.schema_id == schema_id
        ).first()
        if schema is None:
            return "{}"
        return json.dumps(
            {
                "name": schema.name,
                "version": schema.version,
                "categories": schema.categories,
            },
            ensure_ascii=False,
            indent=2,
        )

    @classmethod
    def import_from_json(
        cls, db: Session, name: str, json_str: str
    ) -> LabelSchema | None:
        """从 JSON 字符串校验并导入标签体系，返回新 LabelSchema 或 None"""
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return None

        categories = data.get("categories", [])
        if not isinstance(categories, list):
            return None

        schema = cls(name=name, categories=categories)
        schema.save(db)
        return schema
