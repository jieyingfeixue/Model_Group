from __future__ import annotations

from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from PIL import Image

from backend.services.image.factory import get_image_provider
from backend.services.image.provider import ImageProvider
from backend.services.resource_service import get_resource

router = APIRouter(prefix="/images", tags=["images"])


def _provider() -> ImageProvider:
    return get_image_provider()


@router.get("/{resource_id}")
def get_image(resource_id: int, provider: ImageProvider = Depends(_provider)):
    resource = get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")

    file_key = resource["file_path"]
    try:
        content, media_type = provider.get_display_bytes(file_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from exc

    return Response(content=content, media_type=media_type)


@router.get("/{resource_id}/thumbnail")
def get_thumbnail(
    resource_id: int,
    size: int = 240,
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


@router.get("/{resource_id}/meta")
def get_image_meta(resource_id: int, provider: ImageProvider = Depends(_provider)):
    resource = get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")

    file_key = resource["file_path"]
    exists = provider.exists(file_key)
    return {
        "resource_id": resource_id,
        "file_path": file_key,
        "exists": exists,
        "display_url": f"/api/images/{resource_id}",
        "thumbnail_url": f"/api/images/{resource_id}/thumbnail",
    }
