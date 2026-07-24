"""标签体系 Schema"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LabelCategory(BaseModel):
    """标签类别定义"""
    id: str = Field(..., description="类别唯一标识")
    name: str = Field(..., description="类别名称")
    color: str | None = Field(default=None, description="显示颜色")
    supercategory: str | None = Field(default=None, description="父类别")
    attributes: list[dict[str, Any]] = Field(default_factory=list, description="属性定义")
    status: str = Field(default="active", description="active / deprecated")


class LabelSchemaCreateRequest(BaseModel):
    """创建标签体系请求"""
    name: str = Field(..., min_length=1, max_length=100, description="标签体系名称")
    categories: list[LabelCategory] = Field(..., min_length=1, description="类别列表")


class LabelSchemaResponse(BaseModel):
    """标签体系响应"""
    schema_id: int
    name: str
    categories: list[dict[str, Any]]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LabelSchemaListResponse(BaseModel):
    """标签体系列表响应"""
    items: list[LabelSchemaResponse]
    total: int
    page: int = 1
    size: int = 20


class AddCategoryRequest(BaseModel):
    """新增类别请求"""
    category: LabelCategory


class CategoryResponse(BaseModel):
    """类别操作响应"""
    schema_id: int
    message: str
