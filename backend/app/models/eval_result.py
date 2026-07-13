"""EvalResult ORM Model — 对应 eval_results 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class EvalResult(Base):
    __tablename__ = "eval_results"

    result_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(Integer, nullable=False)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    overall_metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    per_class_metrics: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    per_size_metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    per_scene_metrics: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    pr_curve_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    confusion_matrix: Mapped[list[list[float]] | None] = mapped_column(
        JSONB, nullable=True
    )
    error_samples: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    is_public: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def create(cls, db: Session, **fields: Any) -> EvalResult:
        """写入评测结果，返回新 EvalResult 实例"""
        result = cls(**fields)
        result.save(db)
        return result

    @classmethod
    def get_by_task(cls, db: Session, task_id: int) -> EvalResult | None:
        """按评测任务查询结果（一对一）"""
        return db.query(cls).filter(cls.task_id == task_id).first()

    @classmethod
    def get_latest_by_model_dataset(
        cls, db: Session, model_id: int, dataset_id: int
    ) -> EvalResult | None:
        """获取某模型在某数据集上的最新评测结果"""
        return (
            db.query(cls)
            .filter(cls.model_id == model_id, cls.dataset_id == dataset_id)
            .order_by(cls.created_at.desc())
            .first()
        )

    @classmethod
    def list_public_by_dataset(
        cls, db: Session, dataset_id: int
    ) -> list[EvalResult]:
        """天梯榜查询：某数据集上所有公开评测结果，按 mAP 降序"""
        return (
            db.query(cls)
            .filter(cls.dataset_id == dataset_id, cls.is_public == True)
            .order_by(cls.overall_metrics["mAP50"].desc())
            .all()
        )

    @classmethod
    def get_trend_by_model(
        cls, db: Session, model_id: int, dataset_id: int
    ) -> list[EvalResult]:
        """历史趋势：某模型在某数据集上的所有评测结果，按时间排序"""
        return (
            db.query(cls)
            .filter(cls.model_id == model_id, cls.dataset_id == dataset_id)
            .order_by(cls.created_at)
            .all()
        )

    @staticmethod
    def set_public(
        db: Session, result_id: int, is_public: bool
    ) -> EvalResult | None:
        """设置是否纳入天梯榜排名，返回更新后的 EvalResult"""
        result = db.query(EvalResult).filter(
            EvalResult.result_id == result_id
        ).first()
        if result is None:
            return None
        result.is_public = is_public
        result.save(db)
        return result
