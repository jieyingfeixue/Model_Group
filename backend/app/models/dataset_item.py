"""DatasetItem ORM Model — 对应 dataset_items 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class DatasetItem(Base):
    __tablename__ = "dataset_items"

    item_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    subset: Mapped[str] = mapped_column(String(10), nullable=False)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def bulk_insert(
        cls, db: Session, dataset_id: int, items: list[dict[str, Any]]
    ) -> list[DatasetItem]:
        """批量插入条目。items 每项含 {resource_id, subset}。返回插入的条目列表。"""
        instances = [
            cls(dataset_id=dataset_id, resource_id=it["resource_id"], subset=it["subset"])
            for it in items
        ]
        db.add_all(instances)
        db.flush()
        return instances

    @classmethod
    def get_by_subset(
        cls, db: Session, dataset_id: int, subset: str
    ) -> list[DatasetItem]:
        """按子集查询所有条目"""
        return (
            db.query(cls)
            .filter(cls.dataset_id == dataset_id, cls.subset == subset)
            .all()
        )

    @classmethod
    def count_by_subset(cls, db: Session, dataset_id: int) -> dict[str, int]:
        """各子集数量统计，返回 {train: N, val: M, test: K}"""
        from sqlalchemy import func as sqlfunc

        rows = (
            db.query(cls.subset, sqlfunc.count(cls.item_id))
            .filter(cls.dataset_id == dataset_id)
            .group_by(cls.subset)
            .all()
        )
        counts: dict[str, int] = {"train": 0, "val": 0, "test": 0}
        for subset, count in rows:
            counts[subset] = count
        return counts

    @staticmethod
    def update_subset(
        db: Session, item_id: int, subset: str
    ) -> DatasetItem | None:
        """手动调整个别条目归属子集，返回更新后的 DatasetItem"""
        item = db.query(DatasetItem).filter(DatasetItem.item_id == item_id).first()
        if item is None:
            return None
        item.subset = subset
        item.save(db)
        return item

    @classmethod
    def get_diff(
        cls, db: Session, dataset_id: int, v1: str, v2: str
    ) -> dict[str, list[dict[str, Any]]]:
        """
        两版本条目差异对比。
        注：当前仅返回占位结构；完整实现需结合 data_versions 表的版本快照。
        返回 {added: [{resource_id, subset}], removed: [{resource_id, subset}]}
        """
        return {"added": [], "removed": []}
