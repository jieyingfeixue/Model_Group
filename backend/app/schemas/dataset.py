"""数据集 Schema — 创建 / 筛选 / 预览 / 响应"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ──── 枚举 ────


class DatasetStatus(str, Enum):
    draft = "draft"
    frozen = "frozen"
    published = "published"


class ArchiveStatus(str, Enum):
    active = "active"
    archived = "archived"


class Visibility(str, Enum):
    private = "private"
    public = "public"


class ReviewStatus(str, Enum):
    not_submitted = "not_submitted"
    submitted = "submitted"
    approved = "approved"
    rejected = "rejected"


class LogicOperator(str, Enum):
    AND = "AND"
    OR = "OR"


# ──── 请求模型 ────


class TimeRange(BaseModel):
    """时间范围筛选"""
    start: str | None = Field(None, description="起始时间 ISO 字符串")
    end: str | None = Field(None, description="结束时间 ISO 字符串")


class DatasetFilter(BaseModel):
    """数据集多条件筛选 — 同维度内 OR，跨维度间 AND"""

    modality: list[str] | None = Field(
        None, description="模态类型（多选：visible/infrared/mmwave/lidar）"
    )
    scene: str | None = Field(None, description="场景环境：urban/rural/highway/...")
    weather: str | None = Field(None, description="天气：clear/rainy/foggy/...")
    time_of_day: str | None = Field(None, description="时段：day/night/dawn/dusk")
    annotation_status: str | None = Field(
        None, description="标注状态：unannotated/annotated"
    )
    label_categories: list[str] | None = Field(
        None, description="标签类别 ID 列表（如 cat_001），圈定包含特定类别标注的样本"
    )
    time_range: TimeRange | None = Field(None, description="时间范围")
    logic_operator: LogicOperator = Field(
        LogicOperator.AND, description="逻辑操作符：AND/OR"
    )


class DatasetCreateRequest(BaseModel):
    """创建数据集请求"""

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=2000)
    filters: dict[str, Any] = Field(
        default_factory=dict,
        description="筛选条件 JSON，圈定样本范围",
    )
    owner_id: int | None = Field(None, description="拥有者 ID，默认当前用户")


class DatasetPreviewRequest(BaseModel):
    """数据集预览请求"""

    filters: DatasetFilter = Field(..., description="筛选条件")
    owner_id: int = Field(..., description="数据拥有者 ID")


class DatasetSplitRequest(BaseModel):
    """数据集划分请求"""

    ratios: dict[str, int] = Field(
        ...,
        description="划分比例，如 {train: 70, val: 20, test: 10}，三者之和严格等于 100",
        json_schema_extra={"example": {"train": 70, "val": 20, "test": 10}},
    )
    strategy: str = Field(
        "random",
        pattern=r"^(random|stratified)$",
        description="划分策略：random / stratified",
    )
    stratify_by: str = Field(
        "scene",
        pattern=r"^(scene|modality)$",
        description="分层依据（stratified 时生效）：scene / modality",
    )


class DatasetSplitResponse(BaseModel):
    """数据集划分响应 — 分布统计数据"""

    total: int = Field(..., description="总样本数")
    train: dict[str, Any] = Field(..., description="训练集分布 {count, categories: {...}}")
    val: dict[str, Any] = Field(..., description="验证集分布")
    test: dict[str, Any] = Field(..., description="测试集分布")


# ──── 响应模型 ────


class DatasetPreviewResponse(BaseModel):
    """数据集预览响应"""

    total_count: int = Field(..., description="命中样本总数")
    sample_thumbnails: list[str] = Field(
        default_factory=list,
        description="随机抽样缩略图 URL（最多 10 张）",
    )


class DatasetResponse(BaseModel):
    """数据集完整响应"""

    dataset_id: int
    name: str
    description: str | None = None
    owner_id: int | None = None
    filters: dict[str, Any] | None = None
    split_config: dict[str, Any] | None = None
    version: str
    status: str
    archive_status: str
    visibility: str
    review_status: str
    reviewer_id: int | None = None
    review_notes: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ──── 版本管理 ────


class VersionSaveRequest(BaseModel):
    """保存新版本请求"""

    change_log: str = Field(..., min_length=1, max_length=2000, description="变更日志（必填）")
    bump_type: str = Field(
        "minor",
        pattern=r"^(minor|major)$",
        description="版本号递增方式：minor（v1.0→v1.1）/ major（v1.0→v2.0）",
    )


class VersionItem(BaseModel):
    """版本历史条目"""

    version_id: int
    version: str
    change_log: str
    sample_count: int
    created_by: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VersionDiffResponse(BaseModel):
    """版本差异对比响应"""

    v1: str
    v2: str
    added: list[dict[str, Any]] = Field(
        default_factory=list, description="新增样本 [{resource_id, subset}]"
    )
    removed: list[dict[str, Any]] = Field(
        default_factory=list, description="删除样本 [{resource_id, subset}]"
    )
    subset_changes: list[dict[str, Any]] = Field(
        default_factory=list, description="子集变更 [{resource_id, from, to}]"
    )
    filter_changes: dict[str, Any] = Field(
        default_factory=dict, description="筛选条件变更"
    )
    summary: str = Field("", description="变更摘要")
