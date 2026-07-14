"""标注相关 Schema — 任务创建 / 保存 / 响应 / BBox"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ──── BBox 结构 ────


class BBoxItem(BaseModel):
    """单个标注框 — 归一化坐标（0~1），depth 单位米"""

    x: float = Field(..., ge=0.0, le=1.0, description="中心点 x 坐标（归一化）")
    y: float = Field(..., ge=0.0, le=1.0, description="中心点 y 坐标（归一化）")
    w: float = Field(..., ge=0.0, le=1.0, description="框宽度（归一化）")
    h: float = Field(..., ge=0.0, le=1.0, description="框高度（归一化）")
    category_id: str = Field(..., description="类别 ID，对应标签体系中 cat_xxx")
    depth: float | None = Field(None, ge=0.0, le=500.0, description="深度（米）")
    occlusion: int = Field(0, ge=0, le=3, description="遮挡程度：0=无, 1=轻微, 2=中等, 3=严重")
    truncation: int = Field(0, ge=0, le=3, description="截断程度：0=无, 1=轻微, 2=中等, 3=严重")


# ──── 请求模型 ────


class AnnotationTaskCreate(BaseModel):
    """创建标注任务"""

    name: str = Field(..., min_length=1, max_length=200)
    data_range: dict[str, Any] = Field(
        ..., description="待标注数据的筛选条件 JSON，如 {modality: 'visible', scene: 'urban'}"
    )
    schema_id: int = Field(..., gt=0, description="关联的标签体系 ID")
    assignee_ids: list[int] = Field(..., min_length=1, description="标注员用户 ID 列表")
    reviewer_id: int | None = Field(None, description="审核员 ID（可选）")
    skip_review: bool = Field(False, description="是否跳过审核")
    deadline: datetime | None = Field(None, description="截止时间（可选）")


class AnnotationSaveRequest(BaseModel):
    """保存标注"""

    bboxes: list[BBoxItem] = Field(..., description="标注框列表")


class AnnotationSubmitRequest(BaseModel):
    """提交标注进入审核 — 不需要 body，task_id 和 resource_id 从 URL + Query 获取"""
    pass


# ──── 响应模型 ────


class AnnotationResponse(BaseModel):
    """标注结果响应"""

    annotation_id: int
    task_id: int
    resource_id: int
    bboxes: list[dict[str, Any]]
    version: int
    review_status: str
    reject_reasons: list[dict[str, Any]] | None
    created_by: int
    updated_at: datetime

    model_config = {"from_attributes": True}


class AnnotationHistoryResponse(BaseModel):
    """标注历史版本列表"""

    resource_id: int
    task_id: int
    versions: list[AnnotationResponse]
    count: int


class AnnotationTaskResponse(BaseModel):
    """标注任务响应"""

    task_id: int
    name: str
    data_range: dict[str, Any]
    schema_id: int
    assignee_ids: list[int]
    reviewer_id: int | None
    skip_review: bool
    status: str
    deadline: datetime | None
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True}


class AnnotationProgressResponse(BaseModel):
    """标注进度统计"""

    total: int = Field(..., description="任务范围内数据资源总数")
    annotated: int = Field(..., description="已标注的唯一资源数")
    reviewed: int = Field(..., description="已审核的唯一资源数（approved + rejected）")
    approved: int = Field(..., description="审核通过数")
    rejected: int = Field(..., description="审核驳回数")
