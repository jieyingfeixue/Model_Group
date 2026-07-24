"""标注相关 Schema — 任务创建 / 标注保存"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ──── 标注任务 ────


class AnnotationTaskCreateRequest(BaseModel):
    """创建标注任务请求"""
    name: str = Field(..., min_length=1, max_length=200, description="任务名称")
    data_range: dict[str, Any] = Field(
        ...,
        description="标注数据范围，如 {dataset_id: 1, subset: 'train', sample_count: 100}",
    )
    schema_id: int = Field(..., description="标签体系 ID")
    assignee_ids: list[int] = Field(..., min_length=1, description="标注员用户 ID 列表")
    reviewer_id: int | None = Field(default=None, description="审核员用户 ID")
    skip_review: bool = Field(default=False, description="是否跳过审核")
    deadline: str | None = Field(default=None, description="截止日期 ISO 字符串")


class AnnotationTaskResponse(BaseModel):
    """标注任务响应"""
    task_id: int
    name: str
    data_range: dict[str, Any]
    schema_id: int
    assignee_ids: list[int]
    reviewer_id: int | None = None
    skip_review: bool = False
    status: str = "draft"
    deadline: datetime | str | None = None
    created_by: int
    created_at: datetime | str | None = None

    model_config = {"from_attributes": True}


class AnnotationTaskListResponse(BaseModel):
    """标注任务列表响应"""
    items: list[AnnotationTaskResponse]
    total: int
    page: int = 1
    size: int = 20


# ──── 标注保存 ────


class AnnotationSaveRequest(BaseModel):
    """保存标注结果请求"""
    bboxes: list[dict[str, Any]] = Field(
        ...,
        description="边界框标注列表，每个标注含 class_id/x/y/w/h/confidence 等",
    )


class AnnotationSaveResponse(BaseModel):
    """标注保存响应"""
    annotation_id: int
    task_id: int
    resource_id: int
    version: int
    message: str = "保存成功"


# ──── 标注提交 ────


class AnnotationSubmitRequest(BaseModel):
    """提交标注结果请求（标记该图片标注完成）"""
    pass


class AnnotationSubmitResponse(BaseModel):
    """标注提交响应"""
    annotation_id: int
    task_id: int
    resource_id: int
    version: int
    message: str = "提交成功"


# ──── 标注历史 ────


class AnnotationHistoryItem(BaseModel):
    """标注历史条目"""
    annotation_id: int
    task_id: int
    resource_id: int
    version: int
    bboxes: list[dict[str, Any]]
    review_status: str
    created_by: int
    updated_at: datetime | str | None

    model_config = {"from_attributes": True}


class AnnotationHistoryResponse(BaseModel):
    """标注历史响应"""
    resource_id: int
    task_id: int
    history: list[AnnotationHistoryItem]
    current_version: int


# ──── 任务进度 ────


class AnnotationProgressResponse(BaseModel):
    """标注任务进度响应"""
    task_id: int
    total_images: int
    annotated: int
    reviewed: int
    progress_pct: float


# ──── 下一个待标注 ────


class AnnotationNextImageResponse(BaseModel):
    """下一个待标注图片响应"""
    resource_id: int
    name: str
    modality: str
    file_path: str
    has_existing_annotation: bool = False
    existing_annotation_id: int | None = None
    existing_bboxes: list[dict[str, Any]] | None = None
