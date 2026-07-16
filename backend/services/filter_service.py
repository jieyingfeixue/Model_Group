from __future__ import annotations

from datetime import datetime
from typing import Any

from backend.schemas.data import DataListQuery


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _matches_keyword(item: dict[str, Any], keyword: str) -> bool:
    needle = keyword.strip().lower()
    if not needle:
        return True
    haystack = item.get("name", "").lower()
    return needle in haystack


def _matches_scene(item: dict[str, Any], scene: str) -> bool:
    return item.get("metadata", {}).get("scene") == scene


def _matches_date_range(
    item: dict[str, Any],
    start_date: datetime | None,
    end_date: datetime | None,
) -> bool:
    created_at = _parse_datetime(item.get("created_at"))
    if created_at is None:
        return True
    if start_date and created_at.date() < start_date.date():
        return False
    if end_date and created_at.date() > end_date.date():
        return False
    return True


def _matches_tags(item: dict[str, Any], tags: list[str]) -> bool:
    if not tags:
        return True
    item_tags = {str(tag) for tag in item.get("tags", [])}
    return any(tag in item_tags for tag in tags)


def _matches_category(item: dict[str, Any], category_id: int) -> bool:
    bboxes = item.get("bboxes") or []
    return any(box.get("category_id") == category_id for box in bboxes)


def apply_data_filters(items: list[dict[str, Any]], query: DataListQuery) -> list[dict[str, Any]]:
    """联合筛选：不同维度之间 AND；tags 参数内部 OR（命中任一标签即可）。"""
    filtered = items

    if query.modality:
        filtered = [item for item in filtered if item.get("modality") == query.modality]
    if query.annotation_status:
        filtered = [
            item for item in filtered if item.get("annotation_status") == query.annotation_status
        ]
    if query.scene:
        filtered = [item for item in filtered if _matches_scene(item, query.scene)]
    if query.keyword:
        filtered = [item for item in filtered if _matches_keyword(item, query.keyword)]
    if query.tag_list():
        filtered = [item for item in filtered if _matches_tags(item, query.tag_list())]
    if query.category_id is not None:
        filtered = [item for item in filtered if _matches_category(item, query.category_id)]
    if query.start_date or query.end_date:
        filtered = [
            item
            for item in filtered
            if _matches_date_range(item, query.start_date, query.end_date)
        ]

    return filtered


def apply_dataset_filters(
    items: list[dict[str, Any]],
    *,
    visibility: str | None = None,
    modality: str | None = None,
    keyword: str | None = None,
    is_official: bool | None = None,
) -> list[dict[str, Any]]:
    filtered = items
    if visibility:
        filtered = [item for item in filtered if item.get("visibility") == visibility]
    if modality:
        filtered = [item for item in filtered if item.get("modality") == modality]
    if keyword:
        needle = keyword.strip().lower()
        filtered = [item for item in filtered if needle in item.get("name", "").lower()]
    if is_official is not None:
        filtered = [item for item in filtered if bool(item.get("is_official")) is is_official]
    return filtered
