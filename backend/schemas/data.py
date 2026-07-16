from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DataListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=12, ge=1, le=200)
    modality: str | None = None
    annotation_status: str | None = None
    scene: str | None = None
    keyword: str | None = None
    tags: str | None = None
    category_id: int | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None

    def tag_list(self) -> list[str]:
        if not self.tags:
            return []
        return [part.strip() for part in self.tags.split(",") if part.strip()]


class DatasetListQuery(BaseModel):
    visibility: str | None = None
    modality: str | None = None
    keyword: str | None = None
    is_official: bool | None = None


class PaginatedResponse(BaseModel):
    items: list[dict[str, Any]]
    total: int
