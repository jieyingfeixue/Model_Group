"""模型 / 训练 / 推理 Schema — 对齐 API 契约 §7–§9"""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ModelFramework(str, Enum):
    pytorch = "pytorch"
    tensorflow = "tensorflow"
    onnx = "onnx"


class ModelStatus(str, Enum):
    pending = "pending"
    available = "available"
    deprecated = "deprecated"


class ModelResponse(BaseModel):
    model_id: int
    name: str
    owner_id: int | None
    framework: str
    file_path: str
    meta_info: dict[str, Any]
    is_baseline: bool
    is_public: bool
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class ModelVersionResponse(BaseModel):
    version_id: int
    model_id: int
    version_number: str
    file_path: str
    trained_on_dataset_id: int | None = None
    trained_on_dataset_version: str | None = None
    metrics_snapshot: dict[str, Any] | None = None
    change_note: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class ModelDetailResponse(ModelResponse):
    versions: list[ModelVersionResponse] = Field(default_factory=list)


class ModelVisibilityRequest(BaseModel):
    is_public: bool


class TrainTaskCreate(BaseModel):
    model_id: int
    dataset_id: int
    config: dict[str, Any] = Field(default_factory=dict)
    gpu_config: dict[str, Any] = Field(default_factory=dict)

    model_config = {"protected_namespaces": ()}


class TrainTaskResponse(BaseModel):
    task_id: int
    model_id: int
    model_version_id: int | None = None
    dataset_id: int
    config: dict[str, Any]
    gpu_config: dict[str, Any]
    status: str
    progress: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_log: str | None = None
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class InferTaskCreate(BaseModel):
    model_id: int
    dataset_id: int | None = None
    image_id: int | None = None

    model_config = {"protected_namespaces": ()}


class InferTaskResponse(BaseModel):
    task_id: int
    model_id: int
    dataset_id: int | None = None
    image_id: int | None = None
    status: str
    results: dict[str, Any] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_by: int
    created_at: datetime

    model_config = {"from_attributes": True, "protected_namespaces": ()}
