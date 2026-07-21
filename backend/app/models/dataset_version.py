"""DatasetVersion ORM Model — 对应 dataset_versions 表

每次保存数据集版本时快照当前 filters / split_config / DatasetItem 列表。
用于版本追溯和差异对比。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class DatasetVersion(Base):
    __tablename__ = "dataset_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    version: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="语义化版本号，如 v1.0 / v1.1 / v2.0"
    )
    filters_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="该版本时的筛选条件快照"
    )
    split_config_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, comment="该版本时的子集划分配置快照"
    )
    item_ids_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="该版本时的条目快照 {resource_id: subset}",
    )
    change_log: Mapped[str] = mapped_column(
        Text, nullable=False, default="", server_default="", comment="变更日志"
    )
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def create_snapshot(
        cls,
        db: Session,
        dataset_id: int,
        version: str,
        filters_snapshot: dict[str, Any] | None,
        split_config_snapshot: dict[str, Any] | None,
        item_ids_snapshot: dict[str, Any] | None,
        change_log: str,
        created_by: int | None,
    ) -> DatasetVersion:
        """创建新版本快照，返回新实例"""
        snapshot = cls(
            dataset_id=dataset_id,
            version=version,
            filters_snapshot=filters_snapshot,
            split_config_snapshot=split_config_snapshot,
            item_ids_snapshot=item_ids_snapshot,
            change_log=change_log,
            created_by=created_by,
        )
        snapshot.save(db)
        return snapshot

    @classmethod
    def list_by_dataset(
        cls, db: Session, dataset_id: int
    ) -> list[DatasetVersion]:
        """按数据集查询所有版本，按创建时间降序"""
        return (
            db.query(cls)
            .filter(cls.dataset_id == dataset_id)
            .order_by(cls.created_at.desc())
            .all()
        )

    @classmethod
    def get_by_version(
        cls, db: Session, dataset_id: int, version: str
    ) -> DatasetVersion | None:
        """按版本号查询"""
        return (
            db.query(cls)
            .filter(cls.dataset_id == dataset_id, cls.version == version)
            .first()
        )
