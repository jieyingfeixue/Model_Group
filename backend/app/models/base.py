"""SQLAlchemy 声明性基类 — 提供 save / delete / to_dict 通用方法"""

from datetime import datetime
from typing import Any

from sqlalchemy import inspect
from sqlalchemy.orm import DeclarativeBase, Session


class Base(DeclarativeBase):
    """所有 ORM Model 的基类"""

    def save(self, db: Session) -> "Base":
        """新增或更新当前实例。新增后自动 refresh 以回填 server_default 值。"""
        pk_cols = inspect(self.__class__).primary_key
        # 主键全为 None → 新实例（需 add + refresh）；否则为已有实例（merge）
        is_new = all(getattr(self, col.name) is None for col in pk_cols)
        if is_new:
            db.add(self)
        else:
            db.merge(self)
        db.flush()
        if is_new:
            db.refresh(self)
        return self

    def delete(self, db: Session) -> None:
        """从数据库中删除当前实例"""
        db.delete(self)
        db.flush()

    def to_dict(self, exclude: set[str] | None = None) -> dict[str, Any]:
        """将 ORM 实例转换为普通字典。

        Args:
            exclude: 要排除的字段名集合（如 {'password_hash'}）

        Returns:
            字段名到值的映射字典
        """
        exclude = exclude or set()
        result: dict[str, Any] = {}
        for attr in inspect(self.__class__).columns.keys():
            if attr in exclude:
                continue
            value = getattr(self, attr)
            if isinstance(value, datetime):
                value = value.isoformat()
            result[attr] = value
        return result
