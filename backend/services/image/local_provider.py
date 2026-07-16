from __future__ import annotations

from pathlib import Path

from backend.config import settings
from backend.services.image.provider import ImageProvider


class LocalDemoProvider(ImageProvider):
    """Demo 阶段：从本地 demo_assets/images 目录读取图片。"""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.image_local_root).resolve()

    def _resolve(self, file_key: str) -> Path:
        normalized = file_key.replace("\\", "/").lstrip("/")
        path = (self.root / normalized).resolve()
        if self.root not in path.parents and path != self.root:
            raise ValueError(f"Invalid file key: {file_key}")
        return path

    def exists(self, file_key: str) -> bool:
        return self._resolve(file_key).is_file()

    def get_bytes(self, file_key: str) -> bytes:
        path = self._resolve(file_key)
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {file_key}")
        return path.read_bytes()
