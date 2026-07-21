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
    captured_at: float | None = Field(
        default=None,
        description="采集时间戳（Unix 秒，浮点），可来自 EXIF 自动提取或手动传入",
    )
    meta_info: dict[str, Any] = Field(
        default_factory=dict,
        description="元信息，可含 width/height/channels/file_size/device/scene/weather/time_of_day 等",
    )


class DataResourceFilter(BaseModel):
    """数据资源筛选条件"""

    modality: Modality | None = None
    annotation_status: AnnotationStatus | None = None
    status: ResourceStatus | None = None
    scene: str | None = None
    start_time: str | None = Field(None, description="起始时间 ISO 字符串")
    end_time: str | None = Field(None, description="结束时间 ISO 字符串")
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


# ──── 响应模型 ────


class DataResourceResponse(BaseModel):
    """数据资源响应 — ORM 属性与对外 JSON 字段统一为 meta_info"""

    resource_id: int
    name: str
    owner_id: int | None
    modality: str
    file_path: str
    meta_info: dict[str, Any] = Field(default_factory=dict)
    annotation_status: str
    status: str
    version: int = 1
    created_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}


# ──── 对齐请求 / 响应 ────


class AlignmentRequest(BaseModel):
    """多模态时间戳对齐请求"""

    resource_ids: list[int] = Field(..., min_length=2, description="参与对齐的数据资源 ID 列表")
    strategy: str = Field(
        ...,
        pattern=r"^(nearest_neighbor|downsample|interpolate)$",
        description="对齐策略：nearest_neighbor / downsample / interpolate",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="策略参数：time_window_ms（nearest_neighbor） / target_fps（downsample） / interpolation_strategy（interpolate）",
    )


class AlignmentResponse(BaseModel):
    """对齐结果响应"""

    group_id: int
    strategy: str
    pairs_count: int
    report: dict[str, Any]
    created_at: datetime
