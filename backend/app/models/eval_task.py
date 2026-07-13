"""EvalTask ORM Model — 对应 eval_tasks 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class EvalTask(Base):
    __tablename__ = "eval_tasks"

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    metric_config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def create(cls, db: Session, **fields: Any) -> EvalTask:
        """创建评测任务，返回新 EvalTask 实例"""
        task = cls(**fields)
        task.save(db)
        return task

    @staticmethod
    def update_status(
        db: Session, task_id: int, status: str
    ) -> EvalTask | None:
        """更新评测任务状态，返回更新后的 EvalTask"""
        task = db.query(EvalTask).filter(EvalTask.task_id == task_id).first()
        if task is None:
            return None
        task.status = status
        task.save(db)
        return task

    @classmethod
    def get_by_model_and_dataset(
        cls, db: Session, model_id: int, dataset_id: int
    ) -> list[EvalTask]:
        """按模型+数据集查询评测任务"""
        return (
            db.query(cls)
            .filter(cls.model_id == model_id, cls.dataset_id == dataset_id)
            .order_by(cls.created_at.desc())
            .all()
        )
