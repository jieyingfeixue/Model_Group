"""AlignmentGroup & AlignmentGroupItem ORM Model — 多模态时间戳对齐结果存储"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.models.base import Base


class AlignmentGroup(Base):
    """对齐任务组 — 一次对齐操作产出一个 group，内含多条配对明细"""

    __tablename__ = "alignment_groups"

    group_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # 关联明细
    items: Mapped[list["AlignmentGroupItem"]] = relationship(
        "AlignmentGroupItem", back_populates="group", cascade="all, delete-orphan"
    )

    # ──── 类方法 ────

    @classmethod
    def get_by_owner(
        cls,
        db: Session,
        owner_id: int,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list["AlignmentGroup"], int]:
        """按创建者分页查询对齐历史"""
        query = db.query(cls).filter(cls.created_by == owner_id)
        total = query.count()
        groups = (
            query.order_by(cls.group_id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return groups, total

    @classmethod
    def get_with_items(
        cls, db: Session, group_id: int
    ) -> "AlignmentGroup | None":
        """查询对齐组及其所有配对明细"""
        return db.query(cls).filter(cls.group_id == group_id).first()


class AlignmentGroupItem(Base):
    """对齐配对明细 — 一条记录 = 一个传感器帧在一个对齐组中的位置"""

    __tablename__ = "alignment_group_items"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("alignment_groups.group_id", ondelete="CASCADE"),
        nullable=False,
    )
    resource_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("data_resources.resource_id", ondelete="CASCADE"),
        nullable=False,
    )
    sensor_type: Mapped[str] = mapped_column(String(50), nullable=False)
    is_primary: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # 关联
    group: Mapped["AlignmentGroup"] = relationship(
        "AlignmentGroup", back_populates="items"
    )

    # ──── 类方法 ────

    @classmethod
    def get_by_group(
        cls, db: Session, group_id: int
    ) -> list["AlignmentGroupItem"]:
        """查询某个对齐组的所有配对明细"""
        return db.query(cls).filter(cls.group_id == group_id).all()

    @classmethod
    def get_by_resource(
        cls, db: Session, resource_id: int
    ) -> list["AlignmentGroupItem"]:
        """查询某数据资源参与的所有对齐组"""
        return db.query(cls).filter(cls.resource_id == resource_id).all()
