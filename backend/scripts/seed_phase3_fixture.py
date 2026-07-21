"""Phase3 本地评测夹具 — 不依赖杨子杰数据 / 真 YOLO 权重。

写入：3 张小图（MinIO）+ frozen 数据集 + GT 标注 + 占位 ONNX 模型。
输出 manifest：`backend/demo_assets/phase3_fixture/manifest.json`
（写在 backend 下，Docker 挂载 ./backend:/app 时重建容器不丢）

用法（项目根，需 Postgres + MinIO 可达，与 docker compose 一致）：
  conda activate model-group
  cd backend
  python scripts/seed_phase3_fixture.py
  python scripts/seed_phase3_fixture.py --force   # 删除同名夹具后重建
"""

from __future__ import annotations

import argparse
import json
import sys
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.core.database import SessionLocal  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.core.storage import upload_file  # noqa: E402
from app.models.annotation import Annotation  # noqa: E402
from app.models.annotation_task import AnnotationTask  # noqa: E402
from app.models.data_resource import DataResource  # noqa: E402
from app.models.dataset import Dataset  # noqa: E402
from app.models.dataset_item import DatasetItem  # noqa: E402
from app.models.label_schema import LabelSchema  # noqa: E402
from app.models.model_registry import Model  # noqa: E402
from app.models.model_version import ModelVersion  # noqa: E402
from app.models.user import User  # noqa: E402

FIXTURE_USER = "phase3_fixture"
FIXTURE_EMAIL = "phase3_fixture@local.test"
FIXTURE_DATASET = "phase3-eval-fixture"
FIXTURE_MODEL = "phase3-fixture-model"
FIXTURE_SCHEMA = "phase3-fixture-schema"
FIXTURE_TASK = "phase3-fixture-annotation"
# Docker 挂载 ./backend:/app → 写在 backend 下可持久化；勿写容器根 /demo_assets
ASSETS = BACKEND / "demo_assets"
MANIFEST_PATH = ASSETS / "phase3_fixture" / "manifest.json"

# 320x240，归一化 xywh + category_id（与 categories 顺序一致：pole=1, bridge=2）
IMAGE_SPECS = [
    {
        "name": "fixture_01.jpg",
        "color": (40, 120, 200),
        "bboxes": [{"x": 0.08, "y": 0.10, "w": 0.35, "h": 0.45, "category_id": 1}],
    },
    {
        "name": "fixture_02.jpg",
        "color": (180, 90, 60),
        "bboxes": [{"x": 0.45, "y": 0.20, "w": 0.40, "h": 0.50, "category_id": 2}],
    },
    {
        "name": "fixture_03.jpg",
        "color": (70, 160, 90),
        "bboxes": [
            {"x": 0.05, "y": 0.55, "w": 0.25, "h": 0.30, "category_id": 1},
            {"x": 0.55, "y": 0.15, "w": 0.30, "h": 0.35, "category_id": 2},
        ],
    },
]

IMG_W, IMG_H = 320, 240
CATEGORIES = ["pole", "bridge"]


def _render_jpeg(color: tuple[int, int, int], bboxes: list[dict]) -> bytes:
    im = Image.new("RGB", (IMG_W, IMG_H), color)
    draw = ImageDraw.Draw(im)
    for b in bboxes:
        x1 = int(b["x"] * IMG_W)
        y1 = int(b["y"] * IMG_H)
        x2 = int((b["x"] + b["w"]) * IMG_W)
        y2 = int((b["y"] + b["h"]) * IMG_H)
        draw.rectangle([x1, y1, x2, y2], outline=(255, 255, 0), width=2)
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _get_or_create_user(db) -> User:
    user = User.get_by_username(db, FIXTURE_USER)
    if user:
        return user
    user = User(
        username=FIXTURE_USER,
        email=FIXTURE_EMAIL,
        password_hash=hash_password("Phase3Fixture!"),
        role="normal",
    )
    user.save(db)
    return user


def _delete_fixture(db) -> None:
    ds = db.query(Dataset).filter(Dataset.name == FIXTURE_DATASET).first()
    if ds:
        db.query(DatasetItem).filter(DatasetItem.dataset_id == ds.dataset_id).delete()
        db.delete(ds)

    model = db.query(Model).filter(Model.name == FIXTURE_MODEL).first()
    if model:
        db.query(ModelVersion).filter(ModelVersion.model_id == model.model_id).delete()
        db.delete(model)

    task = db.query(AnnotationTask).filter(AnnotationTask.name == FIXTURE_TASK).first()
    if task:
        db.query(Annotation).filter(Annotation.task_id == task.task_id).delete()
        db.delete(task)

    schema = db.query(LabelSchema).filter(LabelSchema.name == FIXTURE_SCHEMA).first()
    if schema:
        db.delete(schema)

    for spec in IMAGE_SPECS:
        res = db.query(DataResource).filter(DataResource.name == spec["name"]).first()
        if res and (res.meta_info or {}).get("fixture") == "phase3":
            db.query(Annotation).filter(Annotation.resource_id == res.resource_id).delete()
            db.delete(res)
    db.flush()


def seed(force: bool = False) -> dict:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        existing = db.query(Dataset).filter(Dataset.name == FIXTURE_DATASET).first()
        if existing and not force:
            if MANIFEST_PATH.is_file():
                return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
            print("夹具数据集已存在但无 manifest，请使用 --force 重建")
            sys.exit(1)

        if force:
            _delete_fixture(db)
            db.commit()

        user = _get_or_create_user(db)

        schema = LabelSchema(
            name=FIXTURE_SCHEMA,
            categories=[
                {"id": "1", "name": "pole", "status": "active"},
                {"id": "2", "name": "bridge", "status": "active"},
            ],
        )
        schema.save(db)

        task = AnnotationTask.create(
            db,
            name=FIXTURE_TASK,
            data_range={"fixture": "phase3", "count": len(IMAGE_SPECS)},
            schema_id=schema.schema_id,
            assignee_ids=[user.user_id],
            reviewer_id=None,
            skip_review=True,
            status="completed",
            created_by=user.user_id,
        )

        resource_ids: list[int] = []
        for spec in IMAGE_SPECS:
            jpeg = _render_jpeg(spec["color"], spec["bboxes"])
            object_name = f"fixtures/phase3/{spec['name']}"
            file_path = upload_file(jpeg, object_name, content_type="image/jpeg")

            resource = DataResource(
                name=spec["name"],
                owner_id=user.user_id,
                modality="visible",
                file_path=file_path,
                meta_info={
                    "width": IMG_W,
                    "height": IMG_H,
                    "fixture": "phase3",
                    "scene": "fixture",
                },
                annotation_status="annotated",
                status="active",
            )
            resource.save(db)
            resource_ids.append(resource.resource_id)

            Annotation(
                task_id=task.task_id,
                resource_id=resource.resource_id,
                bboxes=spec["bboxes"],
                version=1,
                review_status="approved",
                created_by=user.user_id,
            ).save(db)

        dataset = Dataset.create(
            db,
            name=FIXTURE_DATASET,
            description="Phase3 local eval fixture (frozen test subset)",
            owner_id=user.user_id,
            filters={"modality": "visible", "fixture": "phase3"},
            split_config={"train": 0, "val": 0, "test": len(resource_ids)},
            version="v1.0",
            status="frozen",
            visibility="private",
            review_status="approved",
        )

        DatasetItem.bulk_insert(
            db,
            dataset.dataset_id,
            [{"resource_id": rid, "subset": "test"} for rid in resource_ids],
        )

        onnx_path_candidates = [
            ASSETS / "dummy_weights" / "dummy.onnx",
            ROOT / "demo_assets" / "dummy_weights" / "dummy.onnx",
            Path("/demo_assets/dummy_weights/dummy.onnx"),
        ]
        onnx_bytes = b"DEMO_ONNX_WEIGHT_V1"
        for p in onnx_path_candidates:
            if p.is_file():
                onnx_bytes = p.read_bytes()
                break
        onnx_path = upload_file(
            onnx_bytes,
            "fixtures/phase3/placeholder.onnx",
            content_type="application/octet-stream",
        )

        model = Model.register(
            db,
            name=FIXTURE_MODEL,
            owner_id=user.user_id,
            framework="onnx",
            file_path=onnx_path,
            meta_info={
                "input_size": [640, 640],
                "modalities": ["visible"],
                "categories": CATEGORIES,
                "note": "phase3 fixture placeholder onnx (infer needs real weights)",
            },
            is_baseline=False,
            is_public=True,
            status="available",
        )
        version = ModelVersion.create_version(
            db, model.model_id, onnx_path, note="phase3 fixture", parent_version_id=None
        )

        db.commit()

        manifest = {
            "fixture": "phase3-eval",
            "user": {"username": FIXTURE_USER, "user_id": user.user_id},
            "dataset": {
                "dataset_id": dataset.dataset_id,
                "name": FIXTURE_DATASET,
                "status": "frozen",
                "test_count": len(resource_ids),
            },
            "resources": [
                {"resource_id": rid, "name": IMAGE_SPECS[i]["name"]}
                for i, rid in enumerate(resource_ids)
            ],
            "model": {
                "model_id": model.model_id,
                "version_id": version.version_id,
                "name": FIXTURE_MODEL,
                "categories": CATEGORIES,
            },
            "annotation_task_id": task.task_id,
            "note": "占位 ONNX 无法真推理；用 smoke_phase3_pipeline.py 验 GT+指标链",
        }
        MANIFEST_PATH.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return manifest
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Phase3 eval fixture")
    parser.add_argument("--force", action="store_true", help="删除并重建夹具")
    args = parser.parse_args()

    # 确保 dummy onnx 存在（写到 backend/demo_assets，Docker 可持久化）
    dummy_script = BACKEND / "scripts" / "make_dummy_weight.py"
    if dummy_script.is_file():
        import subprocess

        subprocess.run([sys.executable, str(dummy_script)], check=False)

    manifest = seed(force=args.force)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\nmanifest → {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
