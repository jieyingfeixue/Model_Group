from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.schemas.data import DataListQuery
from backend.services.resource_service import get_resource, list_resources

router = APIRouter(tags=["legacy-data"])


@router.get("/data/resources")
def api_list_resources(
    modality: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    query = DataListQuery(page=page, size=page_size, modality=modality)
    return list_resources(query)


@router.get("/data/resources/{resource_id}")
def api_get_resource(resource_id: int):
    resource = get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource
