"""Model ORM Model — 对应 models 表（模型注册表）"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class Model(Base):
    __tablename__ = "models"

    model_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    framework: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    meta_info: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False)
    is_baseline: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
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
    def register(cls, db: Session, **fields: Any) -> Model:
        """注册新模型，返回新 Model 实例"""
        model = cls(**fields)
        model.save(db)
        return model

    @classmethod
    def get_by_owner(
        cls, db: Session, owner_id: int, filters: dict[str, Any] | None = None
    ) -> list[Model]:
        """按拥有者加条件查询"""
        query = db.query(cls).filter(cls.owner_id == owner_id)
        filters = filters or {}

        if framework := filters.get("framework"):
            query = query.filter(cls.framework == framework)
        if status := filters.get("status"):
            query = query.filter(cls.status == status)

        return query.order_by(cls.model_id.desc()).all()

    @classmethod
    def list_baselines(cls, db: Session) -> list[Model]:
        """列出所有平台预置基线模型"""
        return (
            db.query(cls)
            .filter(cls.is_baseline == True)
            .order_by(cls.model_id)
            .all()
        )

    @staticmethod
    def set_status(db: Session, model_id: int, status: str) -> Model | None:
        """更新模型状态，返回更新后的 Model"""
        model = db.query(Model).filter(Model.model_id == model_id).first()
        if model is None:
            return None
        model.status = status
        model.save(db)
        return model

    @staticmethod
    def set_visibility(
        db: Session, model_id: int, is_public: bool
    ) -> Model | None:
        """设置是否允许他人用于推理或对比，返回更新后的 Model"""
        model = db.query(Model).filter(Model.model_id == model_id).first()
        if model is None:
            return None
        model.is_public = is_public
        model.save(db)
        return model
