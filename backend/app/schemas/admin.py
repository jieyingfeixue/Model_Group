"""管理员 Schema — 用户管理 / 标签管理"""

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


# ──── 用户管理 ────


class AdminUserCreateRequest(BaseModel):
    """管理员创建用户请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    email: EmailStr = Field(..., description="邮箱")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    role: str = Field(default="normal", description="角色: admin / reviewer / normal")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"admin", "reviewer", "normal"}
        if v not in allowed:
            raise ValueError(f"角色必须为以下之一: {', '.join(allowed)}")
        return v


class AdminUserResponse(BaseModel):
    """管理员视角用户信息响应"""
    user_id: int
    username: str
    email: str
    role: str
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AdminUserListResponse(BaseModel):
    """用户列表响应"""
    items: list[AdminUserResponse]
    total: int
    page: int = 1
    size: int = 20


class RoleUpdateRequest(BaseModel):
    """修改角色请求"""
    role: str = Field(..., description="admin / reviewer / normal")

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        allowed = {"admin", "reviewer", "normal"}
        if v not in allowed:
            raise ValueError(f"角色必须为以下之一: {', '.join(allowed)}")
        return v


class StatusUpdateRequest(BaseModel):
    """冻结/解冻请求"""
    is_active: bool = Field(..., description="true=激活, false=冻结")


# ──── 推理审批 ────

class InferTaskPendingItem(BaseModel):
    """推理审批待处理项"""
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    task_id: int
    model_id: int
    dataset_id: int | None = None
    image_id: int | None = None
    status: str
    created_by: int
    created_at: datetime | str | None


class InferTaskPendingListResponse(BaseModel):
    """推理审批待处理列表"""
    items: list[InferTaskPendingItem]
    total: int
    page: int = 1
    size: int = 20


# ──── 天梯治理 ────

class LeaderboardGovernanceItem(BaseModel):
    """天梯治理条目（含管理操作信息）"""
    model_config = {"from_attributes": True, "protected_namespaces": ()}

    result_id: int
    model_id: int
    model_name: str | None = None
    dataset_id: int
    mAP50: float | None = None
    mAP50_95: float | None = None
    is_public: bool = False
    is_invalidated: bool = False
    created_at: datetime | str | None = None


class LeaderboardGovernanceResponse(BaseModel):
    """天梯治理列表"""
    items: list[LeaderboardGovernanceItem]
    total: int
    page: int = 1
    size: int = 20


# ──── 作弊下架 ────

class EvalResultInvalidateRequest(BaseModel):
    """作弊下架请求"""
    reason: str = Field(..., min_length=1, description="下架原因说明")
