"""DataResource ORM Model — 对应 data_resources 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Integer, String, Text, func
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
    captured_at: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
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
        """多条件组合查询，返回 (资源列表, 总数)。

        支持筛选维度：
        - owner_id: 数据拥有者
        - modality: 单值 str 或多值 list（IN 查询）
        - annotation_status: 标注状态
        - status: 生命周期状态
        - scene: 场景环境（meta_info JSONB）
        - batch_id: 批次号（meta_info JSONB）
        - weather: 天气（meta_info JSONB，Phase 3 新增）
        - time_of_day: 时段（meta_info JSONB，Phase 3 新增）
        - start_time / end_time: 时间范围（Phase 3 新增）
        - label_categories: 标签类别 ID 列表（JOIN annotations，Phase 3 新增）
          只看最新版本 + review_status IN ('approved', 'submitted')
        - logic_operator: AND（默认）/ OR，控制顶层条件组合方式
        """
        from datetime import datetime

        from sqlalchemy import and_, cast, func, or_
        from sqlalchemy.dialects.postgresql import JSONB

        from app.models.annotation import Annotation

        query = db.query(cls)
        filters = filters or {}

        # 收集顶层简单条件，用于 AND/OR 逻辑组合
        top_conditions: list = []

        # ── owner_id ──
        if owner_id := filters.get("owner_id"):
            top_conditions.append(cls.owner_id == owner_id)

        # ── modality（支持单值或列表） ──
        if modality := filters.get("modality"):
            if isinstance(modality, list) and len(modality) > 0:
                top_conditions.append(cls.modality.in_(modality))
            elif isinstance(modality, str):
                top_conditions.append(cls.modality == modality)

        # ── annotation_status ──
        if annotation_status := filters.get("annotation_status"):
            top_conditions.append(cls.annotation_status == annotation_status)

        # ── status ──
        if status := filters.get("status"):
            top_conditions.append(cls.status == status)

        # ── scene（JSONB） ──
        if scene := filters.get("scene"):
            top_conditions.append(cls.meta_info["scene"].astext == scene)

        # ── batch_id（JSONB） ──
        if batch_id := filters.get("batch_id"):
            top_conditions.append(cls.meta_info["batch_id"].astext == batch_id)

        # ── weather（JSONB，Phase 3 新增） ──
        if weather := filters.get("weather"):
            top_conditions.append(cls.meta_info["weather"].astext == weather)

        # ── time_of_day（JSONB，Phase 3 新增） ──
        if time_of_day := filters.get("time_of_day"):
            top_conditions.append(cls.meta_info["time_of_day"].astext == time_of_day)

        # ── 时间范围（Phase 3 新增） ──
        if start_time := filters.get("start_time"):
            try:
                top_conditions.append(
                    cls.created_at >= datetime.fromisoformat(start_time)
                )
            except (ValueError, TypeError):
                pass
        if end_time := filters.get("end_time"):
            try:
                top_conditions.append(
                    cls.created_at <= datetime.fromisoformat(end_time)
                )
            except (ValueError, TypeError):
                pass

        # ── 应用顶层条件（AND/OR） ──
        if top_conditions:
            logic_op = filters.get("logic_operator", "AND")
            if logic_op == "OR":
                query = query.filter(or_(*top_conditions))
            else:
                query = query.filter(and_(*top_conditions))

        # ── 标签类别筛选（EXISTS 子查询，Phase 3 新增） ──
        # 只看最新版本 + review_status IN ('approved', 'submitted')
        # 使用 EXISTS 而非 JOIN + DISTINCT，避免 count() 计数偏差
        if label_categories := filters.get("label_categories"):
            if not isinstance(label_categories, list) or len(label_categories) == 0:
                pass
            else:
                # 子查询：每个 resource 在每个 task 中的最新标注版本
                latest_subq = (
                    db.query(
                        Annotation.resource_id,
                        Annotation.task_id,
                        func.max(Annotation.version).label("max_version"),
                    )
                    .filter(Annotation.review_status.in_(["approved", "submitted"]))
                    .group_by(Annotation.resource_id, Annotation.task_id)
                ).subquery()

                # 对每个 category_id 构建 JSONB @> contains 条件
                label_conditions = []
                for cat_id in label_categories:
                    label_conditions.append(
                        Annotation.bboxes.op("@>")(
                            cast(f'[{{"category_id": "{cat_id}"}}]', JSONB)
                        )
                    )

                # EXISTS 子查询：是否存在满足条件的标注
                exists_check = (
                    db.query(Annotation.annotation_id)
                    .join(
                        latest_subq,
                        and_(
                            Annotation.resource_id == latest_subq.c.resource_id,
                            Annotation.task_id == latest_subq.c.task_id,
                            Annotation.version == latest_subq.c.max_version,
                        ),
                    )
                    .filter(
                        Annotation.resource_id == cls.resource_id,
                        Annotation.review_status.in_(["approved", "submitted"]),
                        or_(*label_conditions),
                    )
                    .exists()
                )

                query = query.filter(exists_check)

        # ── 分页 ──
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
