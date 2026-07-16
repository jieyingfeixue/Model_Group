from __future__ import annotations

from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from PIL import Image


def decode_standard(raw: bytes, _file_key: str) -> Image.Image:
    return Image.open(BytesIO(raw)).convert("RGB")


# 格式确定后在此注册新解码器，例如 ".raw": decode_infrared
DECODERS: dict[str, Callable[[bytes, str], Image.Image]] = {
    ".jpg": decode_standard,
    ".jpeg": decode_standard,
    ".png": decode_standard,
    ".webp": decode_standard,
}

SUPPORTED_SUFFIXES = frozenset(DECODERS)


def decode_image(raw: bytes, file_key: str) -> Image.Image:
    suffix = Path(file_key).suffix.lower()
    decoder = DECODERS.get(suffix)
    if decoder is None:
        supported = ", ".join(sorted(DECODERS))
        raise ValueError(
            f"Unsupported image format '{suffix}' for '{file_key}'. "
            f"Supported: {supported}"
        )
    return decoder(raw, file_key)
