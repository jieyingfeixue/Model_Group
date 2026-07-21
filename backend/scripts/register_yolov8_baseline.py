"""将真实 YOLOv8 ONNX 注册为平台基线模型（模板脚本）。

前置：
  1. 已导出 YOLOv8 `.onnx`（建议 opset 12+，输入 1x3x640x640）
  2. Postgres + MinIO 可达（docker compose up）
  3. 可选：先跑 seed_baseline_models.sql 了解占位基线结构

用法示例：
  cd backend
  python scripts/register_yolov8_baseline.py \\
    --onnx-path "D:/weights/yolov8n_visible.onnx" \\
    --name baseline-yolo-visible-v8 \\
    --modality visible \\
    --categories pole,bridge

  # 覆盖已有同名基线（删旧版本记录后重建）
  python scripts/register_yolov8_baseline.py ... --replace
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.database import SessionLocal  # noqa: E402
from app.core.storage import upload_file  # noqa: E402
from app.models.model_registry import Model  # noqa: E402
from app.models.model_version import ModelVersion  # noqa: E402


def register(
    onnx_path: Path,
    name: str,
    modality: str,
    categories: list[str],
    input_size: tuple[int, int],
    replace: bool,
) -> None:
    if not onnx_path.is_file():
        raise FileNotFoundError(onnx_path)

    data = onnx_path.read_bytes()
    if len(data) < 1024:
        print("警告: 文件过小，可能不是有效 ONNX")

    db = SessionLocal()
    try:
        existing = db.query(Model).filter(Model.name == name, Model.is_baseline == True).first()
        if existing and not replace:
            print(
                f"基线已存在 model_id={existing.model_id}，加 --replace 覆盖或换 --name"
            )
            return

        if existing and replace:
            db.query(ModelVersion).filter(ModelVersion.model_id == existing.model_id).delete()
            db.delete(existing)
            db.flush()

        object_name = f"baselines/{name}/v1.0.0/{onnx_path.name}"
        file_path = upload_file(data, object_name, content_type="application/octet-stream")

        meta = {
            "input_size": list(input_size),
            "modalities": [modality],
            "categories": categories,
            "source": "yolov8_onnx",
            "note": "registered via register_yolov8_baseline.py",
        }

        model = Model.register(
            db,
            name=name,
            owner_id=None,
            framework="onnx",
            file_path=file_path,
            meta_info=meta,
            is_baseline=True,
            is_public=True,
            status="available",
        )
        version = ModelVersion.create_version(
            db,
            model.model_id,
            file_path,
            note="yolov8 baseline",
            parent_version_id=None,
        )
        db.commit()
        print(
            json.dumps(
                {
                    "model_id": model.model_id,
                    "version_id": version.version_id,
                    "name": name,
                    "file_path": file_path,
                    "categories": categories,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Register YOLOv8 ONNX as platform baseline")
    parser.add_argument("--onnx-path", required=True, help="本地 .onnx 文件路径")
    parser.add_argument("--name", required=True, help="基线模型名，如 baseline-yolo-visible-v8")
    parser.add_argument(
        "--modality",
        default="visible",
        choices=["visible", "infrared", "mmwave", "lidar"],
    )
    parser.add_argument(
        "--categories",
        default="pole,bridge",
        help="逗号分隔类别名，顺序对应 category_id 1,2,...",
    )
    parser.add_argument("--input-h", type=int, default=640)
    parser.add_argument("--input-w", type=int, default=640)
    parser.add_argument("--replace", action="store_true", help="替换同名基线")
    args = parser.parse_args()

    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    register(
        Path(args.onnx_path).expanduser().resolve(),
        args.name.strip(),
        args.modality,
        cats,
        (args.input_h, args.input_w),
        args.replace,
    )


if __name__ == "__main__":
    main()
