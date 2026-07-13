"""AnnotationTask ORM Model — 对应 annotation_tasks 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class AnnotationTask(Base):
    __tablename__ = "annotation_tasks"

    task_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    data_range: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    schema_id: Mapped[int] = mapped_column(Integer, nullable=False)
    assignee_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skip_review: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    deadline: Mapped[datetime | None] = mapped_column(
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
    def create(cls, db: Session, **fields: Any) -> AnnotationTask:
        """创建标注任务，返回新 AnnotationTask 实例"""
        task = cls(**fields)
        task.save(db)
        return task

    @classmethod
    def get_by_assignee(
        cls, db: Session, user_id: int
    ) -> list[AnnotationTask]:
        """按标注员查询其参与的所有任务"""
        return (
            db.query(cls)
            .filter(cls.assignee_ids.contains([user_id]))
            .order_by(cls.created_at.desc())
            .all()
        )

    @classmethod
    def get_by_status(cls, db: Session, status: str) -> list[AnnotationTask]:
        """按状态查询任务列表"""
        return (
            db.query(cls)
            .filter(cls.status == status)
            .order_by(cls.created_at.desc())
            .all()
        )

    @staticmethod
    def update_status(
        db: Session, task_id: int, new_status: str
    ) -> AnnotationTask | None:
        """更新任务状态，返回更新后的 AnnotationTask"""
        task = db.query(AnnotationTask).filter(
            AnnotationTask.task_id == task_id
        ).first()
        if task is None:
            return None
        task.status = new_status
        task.save(db)
        return task

    @classmethod
    def get_progress(cls, db: Session, task_id: int) -> dict[str, int]:
        """进度统计：{total, annotated, reviewed}"""
        from app.models.annotation import Annotation

        task = db.query(cls).filter(cls.task_id == task_id).first()
        if task is None:
            return {"total": 0, "annotated": 0, "reviewed": 0}

        total = len(task.assignee_ids) if task.assignee_ids else 0
        annotated = (
            db.query(Annotation)
            .filter(Annotation.task_id == task_id)
            .count()
        )
        reviewed = (
            db.query(Annotation)
            .filter(
                Annotation.task_id == task_id,
                Annotation.review_status.in_(["approved", "rejected"]),
            )
            .count()
        )
        return {"total": total, "annotated": annotated, "reviewed": reviewed}
