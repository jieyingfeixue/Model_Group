from __future__ import annotations

from datetime import datetime
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from PIL import Image

from backend.schemas.data import DataListQuery
from backend.services.image.factory import get_image_provider
from backend.services.image.provider import ImageProvider
from backend.services.resource_service import get_resource, get_versions, list_all_tags, list_resources

router = APIRouter(prefix="/data", tags=["data"])


def _provider() -> ImageProvider:
    return get_image_provider()


def _parse_query(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=12, ge=1, le=200),
    modality: str | None = Query(default=None),
    annotation_status: str | None = Query(default=None),
    scene: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    tags: str | None = Query(default=None),
    category_id: int | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
) -> DataListQuery:
    return DataListQuery(
        page=page,
        size=size,
        modality=modality or None,
        annotation_status=annotation_status or None,
        scene=scene or None,
        keyword=keyword or None,
        tags=tags or None,
        category_id=category_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("")
def api_list_data(query: DataListQuery = Depends(_parse_query)):
    return list_resources(query)


@router.get("/tags")
def api_list_tags():
    return {"items": list_all_tags()}


@router.get("/{resource_id}")
def api_get_data(resource_id: int):
    resource = get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.get("/{resource_id}/versions")
def api_get_versions(resource_id: int):
    if get_resource(resource_id) is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return get_versions(resource_id)


@router.get("/{resource_id}/thumbnail")
def api_get_thumbnail(
    resource_id: int,
    size: int = Query(default=480, ge=64, le=1920),
    provider: ImageProvider = Depends(_provider),
):
    resource = get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")

    file_key = resource["file_path"]
    try:
        image = provider.get_pil_image(file_key)
        image.thumbnail((size, size))
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=85)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    return Response(content=buffer.getvalue(), media_type="image/jpeg")
