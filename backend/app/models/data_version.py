"""DataVersion ORM Model — 对应 data_versions 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class DataVersion(Base):
    __tablename__ = "data_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    metadata_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def create_from_resource(
        cls, db: Session, resource_id: int
    ) -> DataVersion | None:
        """从当前资源状态生成新版本快照，返回新 DataVersion 实例"""
        from app.models.data_resource import DataResource

        resource = db.query(DataResource).filter(
            DataResource.resource_id == resource_id
        ).first()
        if resource is None:
            return None

        last_version = (
            db.query(cls)
            .filter(cls.resource_id == resource_id)
            .order_by(cls.version_number.desc())
            .first()
        )
        next_version = (last_version.version_number + 1) if last_version else 1

        snapshot = DataVersion(
            resource_id=resource_id,
            version_number=next_version,
            file_path=resource.file_path,
            metadata_snapshot=dict(resource.metadata) if resource.metadata else {},
        )
        snapshot.save(db)
        return snapshot

    @classmethod
    def list_by_resource(
        cls, db: Session, resource_id: int
    ) -> list[DataVersion]:
        """按时间倒序列出某资源的所有版本"""
        return (
            db.query(cls)
            .filter(cls.resource_id == resource_id)
            .order_by(cls.version_number.desc())
            .all()
        )

    @classmethod
    def get_diff(
        cls, db: Session, resource_id: int, v1: int, v2: int
    ) -> dict[str, Any]:
        """两版本差异对比，返回 {field: {old, new}}"""
        ver1 = (
            db.query(cls)
            .filter(cls.resource_id == resource_id, cls.version_number == v1)
            .first()
        )
        ver2 = (
            db.query(cls)
            .filter(cls.resource_id == resource_id, cls.version_number == v2)
            .first()
        )
        if ver1 is None or ver2 is None:
            return {}

        diff: dict[str, Any] = {}
        all_keys = set(ver1.metadata_snapshot.keys()) | set(ver2.metadata_snapshot.keys())
        for key in all_keys:
            old_val = ver1.metadata_snapshot.get(key)
            new_val = ver2.metadata_snapshot.get(key)
            if old_val != new_val:
                diff[key] = {"old": old_val, "new": new_val}
        return diff
