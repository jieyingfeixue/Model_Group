"""用户相关 Schema — 响应 / 更新请求"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, field_validator

from app.schemas.auth import validate_password_strength


# ──── 响应模型 ────


class UserResponse(BaseModel):
    """用户信息响应"""

    user_id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ──── 请求模型 ────


class UserUpdateRequest(BaseModel):
    """修改个人信息请求 — 所有字段可选"""

    email: EmailStr | None = None
    old_password: str | None = None
    new_password: str | None = None

    @field_validator("new_password")
    @classmethod
    def new_password_complexity(cls, v: str | None) -> str | None:
        if v is not None:
            return validate_password_strength(v)
        return v
