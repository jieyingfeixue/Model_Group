"""数据资源 Schema — 创建 / 响应 / 筛选"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ──── 枚举 ────


class Modality(str, Enum):
    visible = "visible"
    infrared = "infrared"
    mmwave = "mmwave"
    lidar = "lidar"


class AnnotationStatus(str, Enum):
    unannotated = "unannotated"
    annotated = "annotated"


class ResourceStatus(str, Enum):
    active = "active"
    archived = "archived"


# ──── 请求模型 ────


class DataResourceCreate(BaseModel):
    """上传数据资源请求 — meta_info 字段允许前端补充场景/天气等信息"""

    name: str
    modality: Modality
    meta_info: dict[str, Any] = Field(
        default_factory=dict,
        description="元信息，可含 width/height/channels/file_size/device/scene/weather/time_of_day 等",
    )


class DataResourceFilter(BaseModel):
    """数据资源筛选条件"""

    modality: Modality | None = None
    annotation_status: AnnotationStatus | None = None
    status: ResourceStatus | None = None
    # ── 场景标签筛选（meta_info JSONB 字段） ──
    scene: str | None = None
    weather: str | None = None
    time_of_day: str | None = None
    terrain: str | None = None
    obstacle: str | None = None
    batch_id: str | None = None
    sample_group: int | None = None
    # ── 时间 / 分页 ──
    start_time: str | None = Field(None, description="起始时间 ISO 字符串")
    end_time: str | None = Field(None, description="结束时间 ISO 字符串")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=6000)


# ──── 响应模型 ────


class DataResourceResponse(BaseModel):
    """数据资源响应 — ORM 属性与对外 JSON 字段统一为 meta_info"""

    resource_id: int
    name: str
    owner_id: int | None
    modality: str
    file_path: str
    meta_info: dict[str, Any]
    annotation_status: str
    status: str
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}
