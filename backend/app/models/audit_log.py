"""AuditLog ORM Model — 对应 audit_logs 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def query(
        cls,
        db: Session,
        user_id: int | None = None,
        action: str | None = None,
        target_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[AuditLog], int]:
        """多条件检索审计日志，返回 (日志列表, 总数)"""
        query = db.query(cls)

        if user_id is not None:
            query = query.filter(cls.user_id == user_id)
        if action is not None:
            query = query.filter(cls.action == action)
        if target_type is not None:
            query = query.filter(cls.target_type == target_type)
        if start_time is not None:
            query = query.filter(cls.created_at >= start_time)
        if end_time is not None:
            query = query.filter(cls.created_at <= end_time)

        total = query.count()
        logs = (
            query.order_by(cls.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return logs, total
