from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import settings
from backend.services.image.decoder import SUPPORTED_SUFFIXES
from backend.services.metadata_store import load_sidecar, save_sidecar

DEFAULTS_BY_MODALITY = {
    "visible": {"scene": "daytime", "tags": ["可见光", "待标注"]},
    "infrared": {"scene": "night", "tags": ["红外", "夜间"]},
    "mmwave": {"scene": "rainy", "tags": ["毫米波", "雨天"]},
    "lidar": {"scene": "foggy", "tags": ["激光雷达", "雾天"]},
}


def ensure_sidecars() -> int:
    root = settings.image_local_root.resolve()
    created = 0
    for image_path in sorted(root.rglob("*")):
        if not image_path.is_file():
            continue
        if image_path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue

        file_key = image_path.relative_to(root).as_posix()
        if load_sidecar(file_key):
            continue

        modality = file_key.split("/", 1)[0]
        defaults = DEFAULTS_BY_MODALITY.get(modality, {"scene": "daytime", "tags": ["本地导入"]})
        payload = {
            "annotation_status": "unannotated",
            "tags": defaults["tags"],
            "metadata": {
                "scene": defaults["scene"],
                "weather": "clear",
                "source": "本地导入",
            },
        }
        save_sidecar(file_key, payload)
        created += 1
        print(f"created metadata for {file_key}")
    return created


if __name__ == "__main__":
    count = ensure_sidecars()
    print(f"Done. Created {count} sidecar file(s).")
