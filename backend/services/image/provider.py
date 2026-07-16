from __future__ import annotations

from abc import ABC, abstractmethod
from io import BytesIO
from typing import Protocol

from PIL import Image


class ImageProvider(ABC):
    """图片访问兼容层：业务代码只依赖此接口，不感知具体存储后端。"""

    @abstractmethod
    def get_bytes(self, file_key: str) -> bytes:
        """读取原始文件字节，供推理/评测等后端任务使用。"""

    @abstractmethod
    def exists(self, file_key: str) -> bool:
        """检查逻辑路径对应的文件是否存在。"""

    def get_pil_image(self, file_key: str) -> Image.Image:
        from backend.services.image.decoder import decode_image

        raw = self.get_bytes(file_key)
        return decode_image(raw, file_key)

    def get_display_bytes(self, file_key: str) -> tuple[bytes, str]:
        """返回浏览器可直接展示的图片字节和 MIME 类型。"""
        image = self.get_pil_image(file_key)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue(), "image/jpeg"


class SupportsImageProvider(Protocol):
    def get_bytes(self, file_key: str) -> bytes: ...

    def exists(self, file_key: str) -> bool: ...
