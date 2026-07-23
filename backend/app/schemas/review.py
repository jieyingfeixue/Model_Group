"""审核相关 Schema — 数据集审核 / 标注审核"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ──── 数据集审核 ────


class DatasetReviewItem(BaseModel):
    """待审核数据集条目"""
    dataset_id: int
    name: str
    description: str | None = None
    owner_id: int | None = None
    review_status: str
    sample_count: int = 0
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None

    model_config = {"from_attributes": True}


class DatasetReviewListResponse(BaseModel):
    """待审核数据集列表响应"""
    items: list[DatasetReviewItem]
    total: int
    page: int = 1
    size: int = 20


class DatasetVerdictRequest(BaseModel):
    """数据集审核裁决请求"""
    verdict: str = Field(..., description="approved / rejected")
    notes: str | None = Field(default=None, description="审核备注")


class DatasetVerdictResponse(BaseModel):
    """数据集审核裁决响应"""
    dataset_id: int
    review_status: str
    reviewer_id: int | None = None
    review_notes: dict[str, Any] | None = None
    message: str = "审核完成"


# ──── 标注审核 ────


class AnnotationReviewItem(BaseModel):
    """待审核标注条目"""
    annotation_id: int
    task_id: int
    resource_id: int
    bboxes: list[dict[str, Any]] = []
    version: int
    review_status: str
    created_by: int
    updated_at: datetime | str | None = None

    model_config = {"from_attributes": True}


class AnnotationReviewListResponse(BaseModel):
    """标注审核列表响应"""
    items: list[AnnotationReviewItem]
    total: int
    page: int = 1
    size: int = 20


class AnnotationVerdictRequest(BaseModel):
    """标注审核裁决请求"""
    verdict: str = Field(..., description="approved / rejected")
    reject_reasons: list[dict[str, Any]] | None = Field(
        default=None,
        description="驳回原因列表，如 [{\"bbox_index\": 0, \"reason\": \"分类错误\"}]",
    )


class AnnotationVerdictResponse(BaseModel):
    """标注审核裁决响应"""
    annotation_id: int
    review_status: str
    reject_reasons: list[dict[str, Any]] | None = None
    message: str = "审核完成"


# ──── 审核统计 ────


class ReviewStatsResponse(BaseModel):
    """审核统计"""
    pending_datasets: int = 0
    pending_annotations: int = 0
    claimed_datasets: int = 0
    claimed_annotations: int = 0
