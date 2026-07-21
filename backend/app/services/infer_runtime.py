"""推理编排 — 解析权重（含 pt→onnx）、单图/整集 ONNX 推理（Phase3 Step2）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.storage import download_file, upload_file
from app.models.data_resource import DataResource
from app.models.dataset_item import DatasetItem
from app.models.model_registry import Model
from app.models.model_version import ModelVersion
from app.services import onnx_runtime_service
from app.services.pytorch_convert import convert_pt_bytes_to_onnx

ProgressCallback = Callable[[dict[str, Any]], None]


def _is_onnx_path(path: str) -> bool:
    return path.lower().endswith(".onnx")


def _is_torch_path(path: str) -> bool:
    lower = path.lower()
    return lower.endswith(".pt") or lower.endswith(".pth")


def resolve_infer_weight(
    db: Session, model_id: int
) -> tuple[Model, ModelVersion | None, str, bytes]:
    """选择用于推理的 ONNX 权重。

    优先级：
    1. meta_info.runtime_onnx_path（已转换缓存）
    2. 当前版本/模型路径本身是 .onnx
    3. .pt/.pth → 尽力转换并上传缓存
    """
    model = db.query(Model).filter(Model.model_id == model_id).first()
    if model is None:
        raise FileNotFoundError(f"模型 {model_id} 不存在")

    version = ModelVersion.get_latest(db, model_id)
    file_path = version.file_path if version is not None else model.file_path
    meta = dict(model.meta_info or {})

    cached = meta.get("runtime_onnx_path")
    if isinstance(cached, str) and cached:
        try:
            return model, version, cached, download_file(cached)
        except FileNotFoundError:
            pass

    if _is_onnx_path(file_path):
        return model, version, file_path, download_file(file_path)

    if not _is_torch_path(file_path):
        raise ValueError(
            f"不支持的权重格式: {file_path}（需要 .onnx 或 .pt/.pth）"
        )

    pt_bytes = download_file(file_path)
    input_size = onnx_runtime_service.resolve_input_size(meta)
    onnx_bytes = convert_pt_bytes_to_onnx(pt_bytes, input_size=input_size)

    owner = model.owner_id or 0
    ver_id = version.version_id if version else 0
    object_name = f"models/{owner}/{model_id}/runtime_v{ver_id}.onnx"
    onnx_path = upload_file(
        onnx_bytes, object_name, content_type="application/octet-stream"
    )

    meta["runtime_onnx_path"] = onnx_path
    meta["runtime_onnx_from"] = file_path
    model.meta_info = meta
    model.save(db)
    db.commit()

    return model, version, onnx_path, onnx_bytes


def load_image_bytes(db: Session, image_id: int) -> bytes:
    resource = (
        db.query(DataResource).filter(DataResource.resource_id == image_id).first()
    )
    if resource is None:
        raise FileNotFoundError(f"图片资源 {image_id} 不存在")
    return download_file(resource.file_path)


def list_dataset_image_ids(
    db: Session, dataset_id: int, prefer_subset: str = "test"
) -> tuple[list[int], str]:
    """整集推理用的 resource_id 列表：优先 test，若空则用全部条目。

    返回 (ids, subset_used)，subset_used 为 'test' 或 'all'。
    """
    items = DatasetItem.list_by_dataset(db, dataset_id, subset=prefer_subset)
    subset_used = prefer_subset
    if not items:
        items = DatasetItem.list_by_dataset(db, dataset_id, subset=None)
        subset_used = "all"
    if not items:
        raise ValueError(f"数据集 {dataset_id} 没有可推理的图片条目")

    seen: set[int] = set()
    ids: list[int] = []
    for it in items:
        if it.resource_id in seen:
            continue
        seen.add(it.resource_id)
        ids.append(it.resource_id)
    return ids, subset_used


def _run_one(
    session,
    db: Session,
    *,
    image_id: int,
    input_size: tuple[int, int],
    conf_thres: float,
    num_classes: int | None,
) -> dict[str, Any]:
    image_bytes = load_image_bytes(db, image_id)
    detected, orig_w, orig_h = onnx_runtime_service.run_detection_on_image(
        session,
        image_bytes,
        input_size=input_size,
        conf_thres=conf_thres,
        num_classes=num_classes,
    )
    boxes = onnx_runtime_service.detections_to_api_boxes(detected, orig_w, orig_h)
    return {
        "image_id": image_id,
        "image_width": orig_w,
        "image_height": orig_h,
        "boxes": boxes,
        "error": None,
    }


def run_single_image_infer(
    db: Session,
    *,
    model_id: int,
    image_id: int,
    conf_thres: float = 0.25,
) -> dict[str, Any]:
    """单图推理。"""
    model, version, file_path, weight_bytes = resolve_infer_weight(db, model_id)
    cache_key = f"{model_id}:{version.version_id if version else 0}:{file_path}"
    session = onnx_runtime_service.load_onnx_session(weight_bytes, cache_key)
    input_size = onnx_runtime_service.resolve_input_size(model.meta_info)
    categories = (model.meta_info or {}).get("categories") or []
    num_classes = len(categories) if categories else None

    det = _run_one(
        session,
        db,
        image_id=image_id,
        input_size=input_size,
        conf_thres=conf_thres,
        num_classes=num_classes,
    )
    return {
        "total_images": 1,
        "completed": 1,
        "failed_images": 0,
        "engine": "onnxruntime",
        "model_id": model_id,
        "model_version_id": version.version_id if version else None,
        "weight_path": file_path,
        "coord_space": "both",
        "coord_note": "internal=pixel xyxy; API default includes xywh_norm + xyxy_pixel",
        "detections": [det],
    }


def run_dataset_infer(
    db: Session,
    *,
    model_id: int,
    dataset_id: int,
    conf_thres: float = 0.25,
    prefer_subset: str = "test",
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    """整集批量推理：优先 test 子集，否则全部 dataset_items。"""
    model, version, file_path, weight_bytes = resolve_infer_weight(db, model_id)
    cache_key = f"{model_id}:{version.version_id if version else 0}:{file_path}"
    session = onnx_runtime_service.load_onnx_session(weight_bytes, cache_key)
    input_size = onnx_runtime_service.resolve_input_size(model.meta_info)
    categories = (model.meta_info or {}).get("categories") or []
    num_classes = len(categories) if categories else None

    image_ids, subset_used = list_dataset_image_ids(
        db, dataset_id, prefer_subset=prefer_subset
    )
    total = len(image_ids)
    detections: list[dict[str, Any]] = []
    failed = 0

    for idx, image_id in enumerate(image_ids, start=1):
        try:
            detections.append(
                _run_one(
                    session,
                    db,
                    image_id=image_id,
                    input_size=input_size,
                    conf_thres=conf_thres,
                    num_classes=num_classes,
                )
            )
        except Exception as exc:
            failed += 1
            detections.append(
                {
                    "image_id": image_id,
                    "image_width": None,
                    "image_height": None,
                    "boxes": [],
                    "error": str(exc),
                }
            )

        if on_progress is not None:
            on_progress(
                {
                    "total_images": total,
                    "completed": idx,
                    "failed_images": failed,
                    "current_image_id": image_id,
                    "subset": subset_used,
                }
            )

    return {
        "total_images": total,
        "completed": total,
        "failed_images": failed,
        "engine": "onnxruntime",
        "model_id": model_id,
        "model_version_id": version.version_id if version else None,
        "dataset_id": dataset_id,
        "subset": subset_used,
        "weight_path": file_path,
        "coord_space": "both",
        "coord_note": "internal=pixel xyxy; API default includes xywh_norm + xyxy_pixel",
        "detections": detections,
    }
