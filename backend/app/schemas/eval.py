"""评测 Schema — 对齐 API 契约 §10"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvalTaskCreate(BaseModel):
    model_id: int
    model_version_id: int | None = None
    dataset_id: int
    metric_config: dict[str, Any] = Field(
        default_factory=lambda: {"iou_thresholds": [0.5, 0.75], "max_detections": 100}
    )

    model_config = {"protected_namespaces": ()}


class EvalTaskResponse(BaseModel):
    task_id: int
    model_id: int
    model_version_id: int | None = None
    dataset_id: int
    metric_config: dict[str, Any]
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class EvalCompareRequest(BaseModel):
    model_ids: list[int] = Field(..., min_length=1, max_length=5)
    dataset_id: int

    model_config = {"protected_namespaces": ()}


class EvalMetricsResponse(BaseModel):
    task_id: int
    overall_metrics: dict[str, Any]
    per_class_metrics: list[dict[str, Any]] | None = None
    per_size_metrics: dict[str, Any] | None = None
    per_scene_metrics: dict[str, Any] | None = None

    model_config = {"protected_namespaces": ()}
