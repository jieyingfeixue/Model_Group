"""鉴权相关 Schema — Register / Login / Token"""

import re

from pydantic import BaseModel, EmailStr, field_validator


# ──── 密码强度校验常量 ────
PASSWORD_PATTERNS = {
    "lowercase": re.compile(r"[a-z]"),
    "uppercase": re.compile(r"[A-Z]"),
    "digit": re.compile(r"\d"),
    "special": re.compile(r"[!@#$%^&*()_+\-=\[\]{};':\"\\|,.<>\/?`~]"),
}


def validate_password_strength(password: str) -> str:
    """校验密码强度：8-20 位，至少包含大写/小写/数字/特殊字符中的三类"""
    if not (8 <= len(password) <= 20):
        raise ValueError("密码长度必须为 8-20 位")
    categories = sum(1 for p in PASSWORD_PATTERNS.values() if p.search(password))
    if categories < 3:
        raise ValueError("密码至少包含大写字母、小写字母、数字、特殊字符中的三类")
    return password


# ──── 请求模型 ────


class RegisterRequest(BaseModel):
    """注册请求"""

    username: str  # 3-50 字符，前端校验
    password: str
    email: EmailStr

    @field_validator("username")
    @classmethod
    def username_length(cls, v: str) -> str:
        if not (3 <= len(v) <= 50):
            raise ValueError("用户名长度必须为 3-50 位")
        return v

    @field_validator("password")
    @classmethod
    def password_complexity(cls, v: str) -> str:
        return validate_password_strength(v)


class LoginRequest(BaseModel):
    """登录请求"""

    username: str
    password: str


class RefreshTokenRequest(BaseModel):
    """刷新 Access Token 请求"""

    refresh_token: str


# ──── 响应模型 ────


class TokenResponse(BaseModel):
    """登录/刷新 Token 响应"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    role: str
