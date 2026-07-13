"""鉴权中间件 — JWT 认证 + RBAC 角色权限

以 FastAPI Depends 方式注入路由。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import decode_token, is_token_blacklisted
from app.models.user import User

# ──── Bearer Token 提取 ────
_bearer = HTTPBearer(auto_error=False)


# ──── JWT 鉴权依赖 ────


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """从 Authorization Header 提取 Bearer Token 并返回当前登录用户。

    校验链路：Token 存在 → 解码 → 检查黑名单 → 查 User → 校验 is_active。
    校验失败返回 401 Unauthorized。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 Authorization 请求头",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    # 1. 解码 JWT
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 2. 检查黑名单（登出、角色变更后吊销）
    if is_token_blacklisted(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 已被吊销，请重新登录",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id = int(payload.get("sub", 0))
    if user_id == 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token 内容无效",
        )

    # 3. 查询用户
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户不存在",
        )

    # 4. 校验账号状态
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被冻结，请联系管理员",
        )

    return user


# ──── RBAC 权限依赖 ────


def require_role(*roles: str):
    """RBAC 权限检验工厂函数。

    Usage:
        router.get("/admin/users", dependencies=[Depends(require_role("admin"))])
    """

    def role_checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"权限不足，需要以下角色之一: {', '.join(roles)}",
            )
        return current_user

    return role_checker
