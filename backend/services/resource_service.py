from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image

from backend.config import settings
from backend.schemas.data import DataListQuery
from backend.services.filter_service import apply_data_filters
from backend.services.image.decoder import SUPPORTED_SUFFIXES
from backend.services.metadata_store import (
    default_created_at,
    format_file_size,
    load_sidecar,
)

MODALITIES = frozenset({"visible", "infrared", "mmwave", "lidar"})
SCENE_DEFAULT = "daytime"


def _infer_modality(file_key: str) -> str:
    parts = Path(file_key).parts
    if len(parts) > 1 and parts[0] in MODALITIES:
        return parts[0]
    return "unknown"


def _read_image_info(image_path: Path) -> dict[str, Any]:
    info: dict[str, Any] = {}
    try:
        stat = image_path.stat()
        info["file_size"] = format_file_size(stat.st_size)
    except OSError:
        info["file_size"] = "-"

    try:
        with Image.open(image_path) as image:
            width, height = image.size
            info["width"] = width
            info["height"] = height
            info["channels"] = len(image.getbands())
    except OSError:
        pass
    return info


def _build_resource_record(image_path: Path, root: Path) -> dict[str, Any]:
    file_key = image_path.relative_to(root).as_posix()
    sidecar = load_sidecar(file_key)
    image_info = _read_image_info(image_path)

    metadata = {
        "width": image_info.get("width"),
        "height": image_info.get("height"),
        "channels": image_info.get("channels", 3),
        "file_size": image_info.get("file_size", "-"),
        "device": "DJI Mavic 3",
        "scene": SCENE_DEFAULT,
        "weather": "clear",
        "time_of_day": "day",
        "geo_location": "30.5N, 114.3E",
        "batch_id": "2024Q1",
        "source": "本地导入",
    }
    metadata.update(sidecar.get("metadata") or {})

    if metadata.get("scene") == "night":
        metadata["time_of_day"] = "night"

    bboxes = sidecar.get("bboxes") or []
    annotation_status = sidecar.get("annotation_status")
    if not annotation_status:
        annotation_status = "annotated" if bboxes else "unannotated"

    created_at = sidecar.get("created_at") or default_created_at(image_path)
    updated_at = sidecar.get("updated_at") or created_at

    return {
        "name": image_path.name,
        "owner_id": sidecar.get("owner_id", 1),
        "modality": _infer_modality(file_key),
        "file_path": file_key,
        "metadata": metadata,
        "tags": sidecar.get("tags") or [],
        "version": sidecar.get("version") or (2 if bboxes else 1),
        "annotation_status": annotation_status,
        "status": sidecar.get("status", "active"),
        "bboxes": bboxes,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def scan_resources() -> list[dict[str, Any]]:
    root = settings.image_local_root.resolve()
    if not root.is_dir():
        return []

    items: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        items.append(_build_resource_record(path, root))

    for index, item in enumerate(items, start=1):
        item["resource_id"] = index
    return items


def get_resource(resource_id: int) -> dict[str, Any] | None:
    for item in scan_resources():
        if item.get("resource_id") == resource_id:
            return item
    return None


def list_resources(query: DataListQuery) -> dict[str, Any]:
    all_items = scan_resources()
    filtered = apply_data_filters(all_items, query)
    start = (query.page - 1) * query.size
    end = start + query.size
    return {
        "items": filtered[start:end],
        "total": len(filtered),
    }


def list_all_tags() -> list[str]:
    tags: set[str] = set()
    for item in scan_resources():
        tags.update(str(tag) for tag in item.get("tags", []))
    return sorted(tags)


def get_versions(resource_id: int) -> list[dict[str, Any]]:
    resource = get_resource(resource_id)
    if resource is None:
        return []

    sidecar = load_sidecar(resource["file_path"])
    versions = sidecar.get("versions")
    if isinstance(versions, list) and versions:
        return versions

    return [
        {
            "version_id": resource_id * 10 + 1,
            "resource_id": resource_id,
            "version_number": resource.get("version", 1),
            "change_note": "初始导入",
            "metadata_snapshot": {
                "scene": resource.get("metadata", {}).get("scene"),
                "weather": resource.get("metadata", {}).get("weather"),
            },
            "created_by": resource.get("owner_id", 1),
            "created_at": resource.get("created_at"),
        }
    ]
