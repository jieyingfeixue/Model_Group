"""管理端通用 Schema — 用户 / 数据源 / 配置 / 天梯权重等"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.auth import validate_password_strength


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str
    email: EmailStr
    role: str = Field(default="normal", pattern=r"^(normal|reviewer|admin)$")

    @field_validator("password")
    @classmethod
    def password_ok(cls, v: str) -> str:
        return validate_password_strength(v)


class AdminUserRoleUpdate(BaseModel):
    role: str = Field(..., pattern=r"^(normal|reviewer|admin)$")


class AdminUserStatusUpdate(BaseModel):
    is_active: bool | None = None


class DataSourceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    source_type: str = Field(..., pattern=r"^(oss_bucket|local_dir|s3)$")
    connection_info: dict[str, Any] = Field(default_factory=dict)
    modality: str = Field(default="visible")
    status: str = Field(default="inactive", pattern=r"^(active|inactive)$")


class DataSourceSensorsUpdate(BaseModel):
    sensors: dict[str, Any] = Field(default_factory=dict)


class DataSourceSyncRequest(BaseModel):
    force: bool = False
    limit: int = Field(default=100, ge=1, le=5000)


class PlatformConfigUpdate(BaseModel):
    """平台运行时配置（存 Redis，覆盖/补充环境默认值）"""

    train_max_parallel: int | None = Field(None, ge=1, le=16)
    train_timeout_sec: int | None = Field(None, ge=60, le=86400)
    infer_require_approval: bool | None = None
    eval_auto_publish: bool | None = None
    extra: dict[str, Any] | None = None


class EvalWeightsUpdate(BaseModel):
    night_map_weight: float = Field(0.3, ge=0.0, le=1.0)
    fps_weight: float = Field(0.1, ge=0.0, le=1.0)
    map50_weight: float = Field(0.4, ge=0.0, le=1.0)
    map5095_weight: float = Field(0.2, ge=0.0, le=1.0)
    categories: list[str] | None = None


class AuditLogResponse(BaseModel):
    log_id: int
    user_id: int
    action: str
    target_type: str
    target_id: int
    before_state: dict[str, Any] | None = None
    after_state: dict[str, Any] | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DataSourceResponse(BaseModel):
    source_id: int
    name: str
    source_type: str
    connection_info: dict[str, Any]
    modality: str
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}
