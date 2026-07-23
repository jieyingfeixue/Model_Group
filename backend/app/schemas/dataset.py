"""数据集 Schema — 创建 / 响应 / 筛选 / 切分 / 发布"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ──── 请求模型 ────

class DatasetCreateRequest(BaseModel):
    """创建数据集请求"""
    name: str = Field(..., min_length=1, max_length=200, description="数据集名称")
    description: str = Field(default="", description="数据集描述")
    resource_ids: list[int] = Field(..., min_length=1, description="数据资源 ID 列表")
    split_config: dict[str, Any] | None = Field(
        default=None,
        description="切分配置，如 {train:70, val:20, test:10, strategy:'random'}"
    )
    visibility: str = Field(default="private", description="可见性: private / public")


class DatasetSplitRequest(BaseModel):
    """切分数据集请求"""
    train: int = Field(default=70, ge=0, le=100)
    val: int = Field(default=20, ge=0, le=100)
    test: int = Field(default=10, ge=0, le=100)
    strategy: str = Field(default="random", description="random / sequential / grouped（按样本组聚合，保持多模态配对）")


class DatasetPublishRequest(BaseModel):
    """发布数据集请求"""
    version_note: str = Field(default="v1.0", description="版本说明")


# ──── 响应模型 ────

class DatasetItemResponse(BaseModel):
    """数据集条目响应"""
    item_id: int
    resource_id: int
    subset: str


class DatasetResponse(BaseModel):
    """数据集响应"""
    dataset_id: int
    name: str
    description: str | None = None
    owner_id: int | None = None
    filters: dict[str, Any] | None = None
    split_config: dict[str, Any] | None = None
    version: str = "v1.0"
    status: str = "draft"
    archive_status: str = "active"
    visibility: str = "private"
    review_status: str = "not_submitted"
    sample_count: int = 0
    subset_counts: dict[str, int] = Field(
        default_factory=lambda: {"train": 0, "val": 0, "test": 0}
    )
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None

    model_config = {"from_attributes": True}


class DatasetListResponse(BaseModel):
    """数据集列表响应"""
    items: list[DatasetResponse]
    total: int
    page: int = 1
    size: int = 20
