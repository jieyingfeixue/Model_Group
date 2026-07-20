"""标签体系 Schema — 创建 / 类别 / 响应 / 导出"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ──── 请求模型 ────


class LabelSchemaCreate(BaseModel):
    """创建标签体系"""

    name: str = Field(..., min_length=1, max_length=100, description="标签体系名称")


class CategoryCreate(BaseModel):
    """新增类别"""

    name: str = Field(..., min_length=1, max_length=50, description="类别名称")
    shortcut: str | None = Field(None, max_length=1, description="快捷键单字符")
    depth_required: bool = Field(False, description="是否需要标注深度")
    occlusion_required: bool = Field(False, description="是否需要标注遮挡程度")
    truncation_required: bool = Field(False, description="是否需要标注截断程度")


class CategoryUpdate(BaseModel):
    """修改类别 — 所有字段可选，只更新传入的"""

    name: str | None = Field(None, min_length=1, max_length=50)
    shortcut: str | None = Field(None, max_length=1)
    depth_required: bool | None = None
    occlusion_required: bool | None = None
    truncation_required: bool | None = None


class CategoryDeprecateRequest(BaseModel):
    """废弃类别"""

    reason: str = Field(..., min_length=1, description="废弃原因")
    alternative_id: str | None = Field(None, description="替代类别 ID（可选）")


# ──── 响应模型 ────


class LabelSchemaResponse(BaseModel):
    """标签体系响应"""

    schema_id: int
    name: str
    categories: list[dict[str, Any]]
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LabelSchemaExport(BaseModel):
    """标签体系导出格式 — 也用于导入时的 Pydantic 校验"""

    name: str
    version: int
    categories: list[dict[str, Any]]


class CategoryItem(BaseModel):
    """单个类别结构（用于导出/导入校验）"""

    id: str
    name: str
    shortcut: str | None = None
    depth_required: bool = False
    occlusion_required: bool = False
    truncation_required: bool = False
    status: str = "active"


class LabelSchemaImport(BaseModel):
    """导入标签体系 — 用于 Pydantic 校验"""

    name: str = Field(..., min_length=1, max_length=100)
    version: int = Field(1, ge=1)
    categories: list[CategoryItem] = Field(..., min_length=1)
