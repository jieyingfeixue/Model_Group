"""DataSource ORM Model — 对应 data_sources 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class DataSource(Base):
    __tablename__ = "data_sources"

    source_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    connection_info: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    modality: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="inactive", server_default="inactive"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def get_by_name(cls, db: Session, name: str) -> DataSource | None:
        """按名称查询数据源，不存在返回 None"""
        return db.query(cls).filter(cls.name == name).first()

    @classmethod
    def list_active(cls, db: Session) -> list[DataSource]:
        """列出所有活跃数据源"""
        return db.query(cls).filter(cls.status == "active").all()
