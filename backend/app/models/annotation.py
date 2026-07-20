"""Annotation ORM Model — 对应 annotations 表

追加写策略：UNIQUE (task_id, resource_id, version)，每次保存 INSERT 新行保留完整历史。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class Annotation(Base):
    __tablename__ = "annotations"

    annotation_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    bboxes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        comment="审核状态：pending / submitted / approved / rejected",
    )
    reject_reasons: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def get_latest(
        cls, db: Session, task_id: int, resource_id: int
    ) -> Annotation | None:
        """获取某图片在指定任务中的最新版本标注"""
        return (
            db.query(cls)
            .filter(cls.task_id == task_id, cls.resource_id == resource_id)
            .order_by(cls.version.desc())
            .first()
        )

    @classmethod
    def get_history(
        cls, db: Session, task_id: int, resource_id: int
    ) -> list[Annotation]:
        """按版本降序返回某图片在指定任务中的所有历史版本"""
        return (
            db.query(cls)
            .filter(cls.task_id == task_id, cls.resource_id == resource_id)
            .order_by(cls.version.desc())
            .all()
        )

    @classmethod
    def save_new_version(
        cls,
        db: Session,
        task_id: int,
        resource_id: int,
        bboxes: list[dict[str, Any]],
        user_id: int,
    ) -> Annotation:
        """
        追加写：新增一行记录，version 在已有最大值基础上 +1。
        首次标注 version=1，之后每次保存 version 递增。
        返回新的 Annotation 实例。
        """
        latest = cls.get_latest(db, task_id, resource_id)
        next_version = (latest.version + 1) if latest else 1

        annotation = cls(
            task_id=task_id,
            resource_id=resource_id,
            bboxes=bboxes,
            version=next_version,
            created_by=user_id,
        )
        annotation.save(db)
        return annotation

    @classmethod
    def get_by_task(cls, db: Session, task_id: int) -> list[Annotation]:
        """按任务查询所有最新标注（每个 resource 只取最新版本）"""
        from sqlalchemy import func as sqlfunc

        subquery = (
            db.query(
                cls.resource_id,
                sqlfunc.max(cls.version).label("max_version"),
            )
            .filter(cls.task_id == task_id)
            .group_by(cls.resource_id)
            .subquery()
        )
        return (
            db.query(cls)
            .join(
                subquery,
                (cls.resource_id == subquery.c.resource_id)
                & (cls.version == subquery.c.max_version),
            )
            .filter(cls.task_id == task_id)
            .all()
        )

    @classmethod
    def get_by_review_status(
        cls, db: Session, review_status: str
    ) -> list[Annotation]:
        """按审核状态查询标注列表"""
        return (
            db.query(cls)
            .filter(cls.review_status == review_status)
            .order_by(cls.updated_at.desc())
            .all()
        )

    @staticmethod
    def set_review_result(
        db: Session,
        annotation_id: int,
        status: str,
        reject_reasons: list[dict[str, Any]] | None = None,
    ) -> Annotation | None:
        """审核通过或驳回，返回更新后的 Annotation"""
        annotation = db.query(Annotation).filter(
            Annotation.annotation_id == annotation_id
        ).first()
        if annotation is None:
            return None
        annotation.review_status = status
        annotation.reject_reasons = reject_reasons or []
        annotation.save(db)
        return annotation
