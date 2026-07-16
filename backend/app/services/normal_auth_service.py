"""用户鉴权 Service — register / login / refresh / logout / profile / history

所有函数为纯函数形式，第一个参数 db 由 FastAPI Depends(get_db) 注入。
"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import (
    blacklist_token,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    is_token_blacklisted,
    verify_password,
)
from app.models.audit_log import AuditLog
from app.models.user import User


def register(db: Session, username: str, password: str, email: str) -> User:
    """新用户注册。用户名和邮箱唯一性校验 → bcrypt 哈希 → 写入数据库。

    Raises:
        HTTPException 409: 用户名或邮箱已存在
    """

    if User.get_by_username(db, username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已被注册",
        )
    if User.get_by_email(db, email) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邮箱已被注册",
        )

    user = User(
        username=username,
        email=email,
        password_hash=hash_password(password),
    )
    user.save(db)
    return user


def login(db: Session, username: str, password: str) -> dict[str, Any]:
    """用户登录。验证用户名和密码 → 签发 JWT 双 Token。

    Returns:
        {access_token, refresh_token, token_type, role}

    Raises:
        HTTPException 401: 用户名或密码错误
        HTTPException 403: 账号已被冻结
    """

    user = User.get_by_username(db, username)
    if user is None or not verify_password(password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被冻结，请联系管理员",
        )

    return {
        "access_token": create_access_token(user.user_id, user.role),
        "refresh_token": create_refresh_token(user.user_id),
        "token_type": "bearer",
        "role": user.role,
    }


def refresh_access_token(db: Session, refresh_token: str) -> dict[str, Any]:
    """用 Refresh Token 换取新的 Access Token。

    Returns:
        {access_token, refresh_token, token_type, role}

    Raises:
        HTTPException 401: Refresh Token 无效、过期或已被吊销
    """

    # 1. 检查黑名单
    if is_token_blacklisted(refresh_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token 已被吊销，请重新登录",
        )

    # 2. 解码
    try:
        payload = decode_token(refresh_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh Token 无效或已过期",
        )

    if payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="请使用 Refresh Token 刷新，而非 Access Token",
        )

    user_id = int(payload.get("sub", 0))
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在或已冻结",
        )

    # 3. 颁发新 Token 对
    return {
        "access_token": create_access_token(user.user_id, user.role),
        "refresh_token": create_refresh_token(user.user_id),
        "token_type": "bearer",
        "role": user.role,
    }


def logout(db: Session, access_token: str, refresh_token: str | None = None) -> None:
    """登出。将 Access Token 和 Refresh Token 加入 Redis 黑名单。

    Args:
        access_token: 当前请求的 Access Token
        refresh_token: 可选的 Refresh Token（前端传入则一并吊销）
    """

    # Access Token 有效期短，按剩余有效期计算 TTL
    try:
        payload = decode_token(access_token)
        exp = payload.get("exp", 0)
        now = __import__("time").time()
        ttl = max(int(exp - now), 1)
    except Exception:
        ttl = 86400  # 解码失败默认 24h

    blacklist_token(access_token, ttl)

    if refresh_token:
        # Refresh Token 有效期较长（7d）
        blacklist_token(refresh_token, 7 * 24 * 3600)


def get_current_user(db: Session, user_id: int) -> User:
    """获取当前登录用户信息。user_id 由 JWT 中间件注入。

    Returns:
        User 实例

    Raises:
        HTTPException 404: 用户不存在
    """

    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


def update_profile(
    db: Session,
    user_id: int,
    email: str | None = None,
    old_password: str | None = None,
    new_password: str | None = None,
) -> User:
    """修改个人信息。更新邮箱需新邮箱验证码（当前版本跳过），修改密码需验证旧密码。

    Raises:
        HTTPException 400: 旧密码错误
        HTTPException 404: 用户不存在
    """

    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")

    if email is not None:
        # 邮箱唯一性检查
        existing = User.get_by_email(db, email)
        if existing is not None and existing.user_id != user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="邮箱已被其他用户使用",
            )
        user.email = email

    if new_password is not None:
        if old_password is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="修改密码需要提供旧密码",
            )
        if not verify_password(old_password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="旧密码错误",
            )
        user.password_hash = hash_password(new_password)

    user.save(db)
    return user


def get_operation_history(
    db: Session,
    user_id: int,
    page: int = 1,
    size: int = 20,
    action_filter: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """查看个人操作历史。按时间倒序分页，支持按操作类型筛选。

    API: GET /api/users/me/history
    """

    logs, total = AuditLog.query(
        db,
        user_id=user_id,
        action=action_filter,
        page=page,
        size=size,
    )
    items = [log.to_dict() for log in logs]
    return items, total
