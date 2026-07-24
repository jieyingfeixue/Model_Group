"""User ORM Model — 对应 users 表"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", server_default="normal"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
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
    def create(cls, db: Session, **fields: Any) -> User:
        """创建用户，返回新 User 实例"""
        user = cls(**fields)
        user.save(db)
        return user

    @classmethod
    def get_by_username(cls, db: Session, username: str) -> User | None:
        """按用户名查询，不存在返回 None"""
        return db.query(cls).filter(cls.username == username).first()

    @classmethod
    def get_by_email(cls, db: Session, email: str) -> User | None:
        """按邮箱查询，不存在返回 None"""
        return db.query(cls).filter(cls.email == email).first()

    @classmethod
    def list_by_role(
        cls, db: Session, role: str, page: int = 1, size: int = 20
    ) -> tuple[list[User], int]:
        """按角色分页查询，返回 (用户列表, 总数)"""
        query = db.query(cls).filter(cls.role == role)
        total = query.count()
        users = query.order_by(cls.user_id).offset((page - 1) * size).limit(size).all()
        return users, total

    @staticmethod
    def set_role(db: Session, user_id: int, new_role: str) -> User | None:
        """修改角色，返回更新后的 User"""
        user = db.query(User).filter(User.user_id == user_id).first()
        if user is None:
            return None
        user.role = new_role
        user.save(db)
        return user

    @staticmethod
    def toggle_active(db: Session, user_id: int) -> User | None:
        """冻结或解冻账号，返回更新后的 User"""
        user = db.query(User).filter(User.user_id == user_id).first()
        if user is None:
            return None
        user.is_active = not user.is_active
        user.save(db)
        return user
