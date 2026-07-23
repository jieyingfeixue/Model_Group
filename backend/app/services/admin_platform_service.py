"""平台管理 Service — 用户管理 / 统计"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.core.security import hash_password


def list_users(
    db: Session,
    role: str | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """管理员查询用户列表（支持筛选）"""
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if keyword:
        query = query.filter(
            User.username.ilike(f"%{keyword}%") | User.email.ilike(f"%{keyword}%")
        )

    total = query.count()
    users = (
        query.order_by(User.user_id)
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for u in users:
        items.append({
            "user_id": u.user_id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
            "updated_at": u.updated_at,
        })

    return items, total


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    role: str = "normal",
) -> dict[str, Any]:
    """管理员创建新用户"""
    # 检查用户名重复
    if User.get_by_username(db, username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    # 检查邮箱重复
    if User.get_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邮箱已被注册",
        )

    user = User.create(
        db,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def set_user_role(
    db: Session, user_id: int, new_role: str
) -> dict[str, Any]:
    """管理员修改用户角色"""
    if new_role not in ("admin", "reviewer", "normal"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色必须为 admin / reviewer / normal",
        )

    user = User.set_role(db, user_id, new_role)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在"
        )

    return {
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role,
        "message": f"角色已更新为 {new_role}",
    }


def set_user_status(
    db: Session, user_id: int, is_active: bool
) -> dict[str, Any]:
    """管理员冻结/解冻用户"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在"
        )

    user.is_active = is_active
    user.save(db)

    status_text = "激活" if is_active else "冻结"
    return {
        "user_id": user.user_id,
        "username": user.username,
        "is_active": user.is_active,
        "message": f"用户已{status_text}",
    }
