from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.schemas.data import DatasetListQuery
from backend.services.dataset_service import get_dataset, list_datasets

router = APIRouter(prefix="/datasets", tags=["datasets"])


def _parse_query(
    visibility: str | None = Query(default=None),
    modality: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    is_official: bool | None = Query(default=None),
) -> DatasetListQuery:
    return DatasetListQuery(
        visibility=visibility or None,
        modality=modality or None,
        keyword=keyword or None,
        is_official=is_official,
    )


@router.get("")
def api_list_datasets(query: DatasetListQuery = Depends(_parse_query)):
    return list_datasets(query)


@router.get("/{dataset_id}")
def api_get_dataset(dataset_id: int):
    dataset = get_dataset(dataset_id)
    if dataset is None:
        raise HTTPException(status_code=404, detail="Dataset not found")
    return dataset
