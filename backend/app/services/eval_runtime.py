"""评测编排 — 拉 GT、跑/复用推理、调用 MetricsEngine（Phase3）。"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from PIL import Image
from sqlalchemy.orm import Session

from app.core.storage import download_file
from app.eval_engine.coco_adapter import (
    gt_from_annotation_bboxes,
    predictions_from_infer_detection,
)
from app.eval_engine.metrics_engine import ImageEvalInput, evaluate_detection
from app.models.annotation import Annotation
from app.models.data_resource import DataResource
from app.models.model_registry import Model
from app.services import infer_runtime


def _image_size(db: Session, resource_id: int) -> tuple[int, int]:
    resource = (
        db.query(DataResource).filter(DataResource.resource_id == resource_id).first()
    )
    if resource is None:
        return 640, 480
    meta = resource.meta_info or {}
    w = meta.get("width") or meta.get("image_width")
    h = meta.get("height") or meta.get("image_height")
    if w and h:
        return int(w), int(h)
    try:
        raw = download_file(resource.file_path)
        im = Image.open(BytesIO(raw))
        return im.size
    except Exception:
        return 640, 480


def load_gt_for_images(
    db: Session, image_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """每个 resource 取全局最新一条标注作为 GT。"""
    gt_map: dict[int, list[dict[str, Any]]] = {i: [] for i in image_ids}
    for rid in image_ids:
        ann = Annotation.get_latest_for_resource(db, rid)
        if ann is None or not ann.bboxes:
            continue
        w, h = _image_size(db, rid)
        gt_map[rid] = gt_from_annotation_bboxes(ann.bboxes, w, h)
        for box in gt_map[rid]:
            box["image_width"] = w
            box["image_height"] = h
    return gt_map


def build_eval_inputs(
    infer_results: dict[str, Any],
    gt_map: dict[int, list[dict[str, Any]]],
) -> list[ImageEvalInput]:
    inputs: list[ImageEvalInput] = []
    detections = infer_results.get("detections") or []
    seen: set[int] = set()

    for det in detections:
        image_id = int(det["image_id"])
        seen.add(image_id)
        w = int(det.get("image_width") or 0) or 640
        h = int(det.get("image_height") or 0) or 480
        preds = predictions_from_infer_detection({**det, "image_width": w, "image_height": h})
        gts = gt_map.get(image_id) or []
        inputs.append(
            ImageEvalInput(
                image_id=image_id,
                width=w,
                height=h,
                gt_boxes=gts,
                pred_boxes=preds,
            )
        )

    # GT 有但推理未返回的图（理论少见）
    for image_id, gts in gt_map.items():
        if image_id in seen:
            continue
        w = int(gts[0]["image_width"]) if gts else 640
        h = int(gts[0]["image_height"]) if gts else 480
        inputs.append(
            ImageEvalInput(
                image_id=image_id,
                width=w,
                height=h,
                gt_boxes=gts,
                pred_boxes=[],
            )
        )
    return inputs


def run_eval_pipeline(
    db: Session,
    *,
    model_id: int,
    dataset_id: int,
    metric_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """整集推理 → 对齐 GT → MetricsEngine。"""
    cfg = metric_config or {}
    conf_thres = float(cfg.get("conf_thres", 0.25))

    infer_results = infer_runtime.run_dataset_infer(
        db,
        model_id=model_id,
        dataset_id=dataset_id,
        conf_thres=conf_thres,
    )
    image_ids = [int(d["image_id"]) for d in infer_results.get("detections") or []]
    gt_map = load_gt_for_images(db, image_ids)
    inputs = build_eval_inputs(infer_results, gt_map)

    model = db.query(Model).filter(Model.model_id == model_id).first()
    categories = (model.meta_info or {}).get("categories") if model else None
    name_map: dict[int, str] = {}
    if isinstance(categories, list):
        for i, name in enumerate(categories):
            name_map[i + 1] = str(name)

    metrics = evaluate_detection(inputs, category_names=name_map)

    metrics["infer_summary"] = {
        "total_images": infer_results.get("total_images"),
        "failed_images": infer_results.get("failed_images"),
        "subset": infer_results.get("subset"),
        "weight_path": infer_results.get("weight_path"),
        "gt_images": sum(1 for v in gt_map.values() if v),
    }
    return metrics
