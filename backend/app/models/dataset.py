"""Dataset ORM Model — 对应 datasets 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class Dataset(Base):
    __tablename__ = "datasets"

    dataset_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filters: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    split_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="v1.0", server_default="v1.0"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft"
    )
    archive_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="private", server_default="private"
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="not_submitted",
        server_default="not_submitted",
    )
    reviewer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_notes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
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
    def create(cls, db: Session, **fields: Any) -> Dataset:
        """创建数据集，返回新 Dataset 实例"""
        dataset = cls(**fields)
        dataset.save(db)
        return dataset

    @classmethod
    def get_by_owner(cls, db: Session, owner_id: int) -> list[Dataset]:
        """按拥有者查询所有数据集"""
        return (
            db.query(cls)
            .filter(cls.owner_id == owner_id)
            .order_by(cls.dataset_id.desc())
            .all()
        )

    @classmethod
    def list_public(
        cls,
        db: Session,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        size: int = 50,
    ) -> tuple[list[Dataset], int]:
        """查询公开数据集，支持多条件筛选和分页（Phase 3 增强）。

        筛选维度：
        - modality: 单值或多值列表（filters JSONB 中 modality 字段）
        - scene / weather / time_of_day: filters JSONB 中的场景信息
        - keyword: 数据集名称 + 描述模糊搜索
        - sort_by: updated_at（默认）/ created_at
        """
        query = db.query(cls).filter(
            cls.visibility == "public", cls.status == "published"
        )
        filters = filters or {}

        if modality := filters.get("modality"):
            if isinstance(modality, list):
                # 多值 IN 查询（filters JSONB 中匹配）
                from sqlalchemy import or_
                conditions = [
                    cls.filters["modality"].astext == m for m in modality
                ]
                query = query.filter(or_(*conditions))
            else:
                query = query.filter(cls.filters["modality"].astext == modality)
        if scene := filters.get("scene"):
            query = query.filter(cls.filters["scene"].astext == scene)
        if weather := filters.get("weather"):
            query = query.filter(cls.filters["weather"].astext == weather)
        if time_of_day := filters.get("time_of_day"):
            query = query.filter(cls.filters["time_of_day"].astext == time_of_day)
        if label_categories := filters.get("label_categories"):
            # 匹配数据集创建时筛选条件中的 label_categories
            # 支持单值或多值列表
            from sqlalchemy import or_
            if isinstance(label_categories, list):
                conditions = [
                    cls.filters["label_categories"].astext.contains(cat_id)
                    for cat_id in label_categories
                ]
                query = query.filter(or_(*conditions))
            else:
                query = query.filter(
                    cls.filters["label_categories"].astext.contains(label_categories)
                )
        if keyword := filters.get("keyword"):
            query = query.filter(
                (cls.name.ilike(f"%{keyword}%"))
                | (cls.description.ilike(f"%{keyword}%"))
            )

        sort_by = filters.get("sort_by", "updated_at")
        order_col = cls.updated_at if sort_by != "created_at" else cls.created_at

        total = query.count()
        datasets = (
            query.order_by(order_col.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return datasets, total

    @staticmethod
    def update_status(db: Session, dataset_id: int, status: str) -> Dataset | None:
        """更新数据集状态（draft → frozen → published），返回更新后的 Dataset"""
        dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
        if dataset is None:
            return None
        dataset.status = status
        dataset.save(db)
        return dataset

    @staticmethod
    def set_visibility(
        db: Session, dataset_id: int, visibility: str
    ) -> Dataset | None:
        """设置可见范围（private / public），返回更新后的 Dataset"""
        dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
        if dataset is None:
            return None
        dataset.visibility = visibility
        dataset.save(db)
        return dataset

    @staticmethod
    def set_archive_status(
        db: Session, dataset_id: int, archive_status: str
    ) -> Dataset | None:
        """归档或恢复数据集，返回更新后的 Dataset"""
        dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
        if dataset is None:
            return None
        dataset.archive_status = archive_status
        dataset.save(db)
        return dataset

    @classmethod
    def get_versions(cls, db: Session, dataset_id: int) -> list[dict[str, Any]]:
        """返回数据集所有语义化版本列表（从 dataset_items 变更历史推算）"""
        # 当前版本从自身字段读取；历史版本需结合 data_versions 表
        dataset = db.query(cls).filter(cls.dataset_id == dataset_id).first()
        if dataset is None:
            return []
        return [{"version": dataset.version, "updated_at": dataset.updated_at.isoformat()}]
