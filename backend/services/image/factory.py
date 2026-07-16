from __future__ import annotations

from backend.config import settings
from backend.services.image.local_provider import LocalDemoProvider
from backend.services.image.provider import ImageProvider


class HttpUrlProvider(ImageProvider):
    """预留：从云服务器 HTTP URL 拉取图片。"""

    def __init__(self, base_url: str = "") -> None:
        self.base_url = base_url.rstrip("/")

    def exists(self, file_key: str) -> bool:
        raise NotImplementedError("HttpUrlProvider is reserved for cloud deployment.")

    def get_bytes(self, file_key: str) -> bytes:
        raise NotImplementedError("HttpUrlProvider is reserved for cloud deployment.")


def get_image_provider() -> ImageProvider:
    mode = settings.image_storage_mode.lower()
    if mode == "local":
        return LocalDemoProvider()
    if mode == "http":
        return HttpUrlProvider()
    raise ValueError(f"Unsupported IMAGE_STORAGE_MODE: {settings.image_storage_mode}")
