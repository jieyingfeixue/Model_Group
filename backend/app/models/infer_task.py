"""InferTask ORM Model — 对应 infer_tasks 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class InferTask(Base):
    __tablename__ = "infer_tasks"

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    results: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    def create(cls, db: Session, **fields: Any) -> InferTask:
        """创建推理任务，返回新 InferTask 实例"""
        task = cls(**fields)
        task.save(db)
        return task

    @classmethod
    def get_cached_result(
        cls, db: Session, model_id: int, dataset_id: int
    ) -> InferTask | None:
        """查已有缓存结果避免重复推理（取最近一次 completed 任务）"""
        return (
            db.query(cls)
            .filter(
                cls.model_id == model_id,
                cls.dataset_id == dataset_id,
                cls.status == "completed",
            )
            .order_by(cls.finished_at.desc())
            .first()
        )

    @staticmethod
    def update_results(
        db: Session, task_id: int, results: dict[str, Any]
    ) -> InferTask | None:
        """写入推理结果（覆盖），返回更新后的 InferTask"""
        task = db.query(InferTask).filter(InferTask.task_id == task_id).first()
        if task is None:
            return None
        task.results = results
        task.save(db)
        return task
