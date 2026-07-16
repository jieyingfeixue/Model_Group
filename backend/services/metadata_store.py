from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config import settings


def _sidecar_path(file_key: str) -> Path:
    path = Path(file_key)
    return settings.metadata_root / path.with_suffix(".json")


def load_sidecar(file_key: str) -> dict[str, Any]:
    sidecar = _sidecar_path(file_key)
    if not sidecar.is_file():
        return {}
    try:
        with sidecar.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_sidecar(file_key: str, payload: dict[str, Any]) -> None:
    sidecar = _sidecar_path(file_key)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    with sidecar.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def default_created_at(image_path: Path) -> str:
    timestamp = image_path.stat().st_mtime
    return datetime.fromtimestamp(timestamp, tz=UTC).isoformat()


def format_file_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes}B"
    if num_bytes < 1024 * 1024:
        return f"{round(num_bytes / 1024)}KB"
    return f"{round(num_bytes / (1024 * 1024), 1)}MB"
