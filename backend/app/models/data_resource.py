"""DataResource ORM Model — 对应 data_resources 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class DataResource(Base):
    __tablename__ = "data_resources"

    resource_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    owner_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modality: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    meta_info: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    annotation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unannotated", server_default="unannotated"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )
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
    def get_by_owner(
        cls,
        db: Session,
        owner_id: int,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[DataResource], int]:
        """按归属人组合条件分页查询，返回 (资源列表, 总数)"""
        query = db.query(cls).filter(cls.owner_id == owner_id)
        filters = filters or {}

        if modality := filters.get("modality"):
            query = query.filter(cls.modality == modality)
        if annotation_status := filters.get("annotation_status"):
            query = query.filter(cls.annotation_status == annotation_status)
        if status := filters.get("status"):
            query = query.filter(cls.status == status)
        if scene := filters.get("scene"):
            query = query.filter(cls.meta_info["scene"].astext == scene)
        if weather := filters.get("weather"):
            query = query.filter(cls.meta_info["weather"].astext == weather)
        if time_of_day := filters.get("time_of_day"):
            query = query.filter(cls.meta_info["time_of_day"].astext == time_of_day)
        if terrain := filters.get("terrain"):
            query = query.filter(cls.meta_info["terrain"].astext == terrain)
        if obstacle := filters.get("obstacle"):
            query = query.filter(cls.meta_info["obstacle"].astext == obstacle)
        if start_time := filters.get("start_time"):
            query = query.filter(cls.created_at >= start_time)
        if end_time := filters.get("end_time"):
            query = query.filter(cls.created_at <= end_time)

        total = query.count()
        resources = (
            query.order_by(cls.resource_id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return resources, total

    @classmethod
    def search(
        cls,
        db: Session,
        filters: dict[str, Any] | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[DataResource], int]:
        """多条件组合查询，返回 (资源列表, 总数)"""
        query = db.query(cls)
        filters = filters or {}

        if owner_id := filters.get("owner_id"):
            query = query.filter(cls.owner_id == owner_id)
        if modality := filters.get("modality"):
            query = query.filter(cls.modality == modality)
        if annotation_status := filters.get("annotation_status"):
            query = query.filter(cls.annotation_status == annotation_status)
        if status := filters.get("status"):
            query = query.filter(cls.status == status)
        if scene := filters.get("scene"):
            query = query.filter(cls.meta_info["scene"].astext == scene)
        if weather := filters.get("weather"):
            query = query.filter(cls.meta_info["weather"].astext == weather)
        if time_of_day := filters.get("time_of_day"):
            query = query.filter(cls.meta_info["time_of_day"].astext == time_of_day)
        if terrain := filters.get("terrain"):
            query = query.filter(cls.meta_info["terrain"].astext == terrain)
        if obstacle := filters.get("obstacle"):
            query = query.filter(cls.meta_info["obstacle"].astext == obstacle)
        if sample_group := filters.get("sample_group"):
            query = query.filter(cls.meta_info["sample_group"].astext == str(sample_group))
        if batch_id := filters.get("batch_id"):
            query = query.filter(cls.meta_info["batch_id"].astext == batch_id)

        total = query.count()
        resources = (
            query.order_by(cls.resource_id.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return resources, total

    @staticmethod
    def update_metadata(
        db: Session, resource_id: int, fields: dict[str, Any]
    ) -> DataResource | None:
        """更新元信息并触发版本号递增，返回更新后的 DataResource"""
        resource = db.query(DataResource).filter(
            DataResource.resource_id == resource_id
        ).first()
        if resource is None:
            return None
        current_meta = dict(resource.meta_info) if resource.meta_info else {}
        current_meta.update(fields)
        resource.meta_info = current_meta
        resource.version += 1
        resource.save(db)
        return resource

    @staticmethod
    def get_annotation_status_counts(
        db: Session, owner_id: int
    ) -> dict[str, int]:
        """统计各类标注状态数量，返回 {status: count}"""
        from sqlalchemy import func as sqlfunc

        rows = (
            db.query(cls.annotation_status, sqlfunc.count(cls.resource_id))
            .filter(cls.owner_id == owner_id)
            .group_by(cls.annotation_status)
            .all()
        )
        return {row[0]: row[1] for row in rows}


# 模块级别名，解决类方法内部自引用
cls = DataResource
