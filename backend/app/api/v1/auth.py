"""鉴权路由 — /api/auth/* 和 /api/users/*"""

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    TokenResponse,
)
from app.schemas.user import UserResponse, UserUpdateRequest
from app.services import normal_auth_service

router = APIRouter(tags=["Auth"])
_bearer = HTTPBearer(auto_error=False)


# ──── /api/auth/* ────


@router.post("/auth/register", response_model=UserResponse, status_code=201)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """新用户注册"""
    user = normal_auth_service.register(
        db,
        username=body.username,
        password=body.password,
        email=body.email,
    )
    return UserResponse.model_validate(user)


@router.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """用户登录，返回 Access Token + Refresh Token"""
    result = normal_auth_service.login(
        db,
        username=body.username,
        password=body.password,
    )
    return TokenResponse(**result)


@router.post("/auth/refresh", response_model=TokenResponse)
def refresh(body: RefreshTokenRequest, db: Session = Depends(get_db)):
    """用 Refresh Token 换取新 Token 对"""
    result = normal_auth_service.refresh_access_token(
        db,
        refresh_token=body.refresh_token,
    )
    return TokenResponse(**result)


@router.post("/auth/logout", status_code=204)
def logout(
    refresh_token: str | None = Query(None, description="Refresh Token 一并吊销"),
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
):
    """登出。Access Token 从 Authorization Header 提取，Refresh Token 可选传参。"""
    normal_auth_service.logout(
        db,
        access_token=credentials.credentials if credentials else "",
        refresh_token=refresh_token,
    )


# ──── /api/users/* ────


@router.get("/users/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """获取当前登录用户信息"""
    user = normal_auth_service.get_current_user(db, user_id=current_user.user_id)
    return UserResponse.model_validate(user)


@router.put("/users/me", response_model=UserResponse)
def update_me(
    body: UserUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改个人信息（邮箱/密码）"""
    user = normal_auth_service.update_profile(
        db,
        user_id=current_user.user_id,
        email=body.email,
        old_password=body.old_password,
        new_password=body.new_password,
    )
    return UserResponse.model_validate(user)


@router.get("/users/me/history")
def get_my_history(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    action: str | None = Query(None, description="操作类型筛选"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看个人操作历史"""
    items, total = normal_auth_service.get_operation_history(
        db,
        user_id=current_user.user_id,
        page=page,
        size=size,
        action_filter=action,
    )
    return {"items": items, "total": total, "page": page, "size": size}
