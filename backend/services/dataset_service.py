from __future__ import annotations

import json
from typing import Any

from backend.config import settings
from backend.schemas.data import DatasetListQuery
from backend.services.filter_service import apply_dataset_filters


def _load_datasets() -> list[dict[str, Any]]:
    path = settings.datasets_path.resolve()
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, list) else []


def list_datasets(query: DatasetListQuery) -> dict[str, Any]:
    items = apply_dataset_filters(
        _load_datasets(),
        visibility=query.visibility,
        modality=query.modality,
        keyword=query.keyword,
        is_official=query.is_official,
    )
    return {"items": items, "total": len(items)}


def get_dataset(dataset_id: int) -> dict[str, Any] | None:
    for item in _load_datasets():
        if item.get("dataset_id") == dataset_id:
            return item
    return None
