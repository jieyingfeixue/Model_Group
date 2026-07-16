"""TrainTask ORM Model — 对应 train_tasks 表

config JSONB NOT NULL DEFAULT '{}'：创建任务时允许空对象，Service 层在启动训练时校验必填字段。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class TrainTask(Base):
    __tablename__ = "train_tasks"

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    gpu_config: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending_approval",
        server_default="pending_approval",
    )
    progress: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False), nullable=True
    )
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def create(cls, db: Session, **fields: Any) -> TrainTask:
        """创建训练任务，返回新 TrainTask 实例"""
        task = cls(**fields)
        task.save(db)
        return task

    @staticmethod
    def update_status(
        db: Session, task_id: int, status: str
    ) -> TrainTask | None:
        """更新训练任务状态，返回更新后的 TrainTask"""
        task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
        if task is None:
            return None
        task.status = status
        task.save(db)
        return task

    @staticmethod
    def update_progress(
        db: Session, task_id: int, progress: dict[str, Any]
    ) -> TrainTask | None:
        """更新训练指标（epoch, loss, mAP 等），返回更新后的 TrainTask"""
        task = db.query(TrainTask).filter(TrainTask.task_id == task_id).first()
        if task is None:
            return None
        task.progress = progress
        task.save(db)
        return task

    @classmethod
    def get_by_user(cls, db: Session, user_id: int) -> list[TrainTask]:
        """按提交者查询所有训练任务，按时间倒序"""
        return (
            db.query(cls)
            .filter(cls.created_by == user_id)
            .order_by(cls.created_at.desc())
            .all()
        )

    @classmethod
    def get_pending_approval(cls, db: Session) -> list[TrainTask]:
        """查询所有待管理员审批的训练任务"""
        return (
            db.query(cls)
            .filter(cls.status == "pending_approval")
            .order_by(cls.created_at)
            .all()
        )
