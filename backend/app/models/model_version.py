"""ModelVersion ORM Model — 对应 model_versions 表"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class ModelVersion(Base):
    __tablename__ = "model_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_id: Mapped[int] = mapped_column(Integer, nullable=False)
    version_number: Mapped[str] = mapped_column(String(20), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    trained_on_dataset_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    trained_on_dataset_version: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    metrics_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=func.now(),
        server_default=func.now(),
    )

    # ──── 类方法 ────

    @classmethod
    def create_version(
        cls, db: Session, model_id: int, file_path: str, note: str = ""
    ) -> ModelVersion:
        """新增版本记录。版本号自动递增（从已有最大版本推算）。返回新 ModelVersion。"""
        latest = (
            db.query(cls)
            .filter(cls.model_id == model_id)
            .order_by(cls.version_id.desc())
            .first()
        )
        if latest and latest.version_number:
            parts = latest.version_number.lstrip("v").split(".")
            major = int(parts[0]) if parts else 0
            minor = int(parts[1]) if len(parts) > 1 else 0
            patch = int(parts[2]) if len(parts) > 2 else 0
            patch += 1
            next_version = f"v{major}.{minor}.{patch}"
        else:
            next_version = "v1.0.0"

        version = cls(
            model_id=model_id,
            version_number=next_version,
            file_path=file_path,
            change_note=note,
        )
        version.save(db)
        return version

    @classmethod
    def list_by_model(cls, db: Session, model_id: int) -> list[ModelVersion]:
        """按模型查询所有版本，按时间倒序"""
        return (
            db.query(cls)
            .filter(cls.model_id == model_id)
            .order_by(cls.version_id.desc())
            .all()
        )

    @classmethod
    def get_latest(cls, db: Session, model_id: int) -> ModelVersion | None:
        """获取某模型的最新版本"""
        return (
            db.query(cls)
            .filter(cls.model_id == model_id)
            .order_by(cls.version_id.desc())
            .first()
        )
