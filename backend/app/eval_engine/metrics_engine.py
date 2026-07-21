"""MetricsEngine — 目标检测指标（Phase3）。

优先尝试 pycocotools；不可用时使用内置 IoU/AP 实现（保证空预测不崩、可单测）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from app.eval_engine.coco_adapter import (
    enrich_norm_fields,
    to_coco_gt,
    xyxy_to_coco_bbox,
)


@dataclass
class ImageEvalInput:
    image_id: int
    width: int
    height: int
    gt_boxes: list[dict[str, Any]]  # x1,y1,x2,y2,category_id
    pred_boxes: list[dict[str, Any]]  # + confidence


def _iou_xyxy(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a (N,4), b (M,4) → (N,M)"""
    if a.size == 0 or b.size == 0:
        return np.zeros((a.shape[0], b.shape[0]), dtype=np.float64)
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(rb - lt, 0, None)
    inter = wh[:, :, 0] * wh[:, :, 1]
    area_a = np.clip(a[:, 2] - a[:, 0], 0, None) * np.clip(a[:, 3] - a[:, 1], 0, None)
    area_b = np.clip(b[:, 2] - b[:, 0], 0, None) * np.clip(b[:, 3] - b[:, 1], 0, None)
    union = area_a[:, None] + area_b[None, :] - inter + 1e-9
    return inter / union


def _boxes_array(boxes: list[dict[str, Any]], with_score: bool = False) -> np.ndarray:
    rows = []
    for b in boxes:
        row = [float(b["x1"]), float(b["y1"]), float(b["x2"]), float(b["y2"])]
        if with_score:
            row.append(float(b.get("confidence", 0.0)))
        rows.append(row)
    if not rows:
        return np.zeros((0, 5 if with_score else 4), dtype=np.float64)
    return np.asarray(rows, dtype=np.float64)


def _ap_from_pr(recalls: np.ndarray, precisions: np.ndarray) -> float:
    """VOC-style all-point AP。"""
    if recalls.size == 0:
        return 0.0
    mrec = np.concatenate(([0.0], recalls, [1.0]))
    mpre = np.concatenate(([0.0], precisions, [0.0]))
    for i in range(mpre.size - 1, 0, -1):
        mpre[i - 1] = max(mpre[i - 1], mpre[i])
    idx = np.where(mrec[1:] != mrec[:-1])[0]
    return float(np.sum((mrec[idx + 1] - mrec[idx]) * mpre[idx + 1]))


def _eval_class_at_iou(
    gts: list[dict[str, Any]],
    preds: list[dict[str, Any]],
    iou_thr: float,
) -> tuple[float, list[tuple[float, float]], dict[str, int]]:
    """单类 AP + PR 点 + tp/fp/fn 计数（按匹配）。"""
    # group by image
    gt_by: dict[int, list[dict[str, Any]]] = {}
    for g in gts:
        gt_by.setdefault(int(g["image_id"]), []).append(g)
    pred_by: dict[int, list[dict[str, Any]]] = {}
    for p in preds:
        pred_by.setdefault(int(p["image_id"]), []).append(p)

    # sort all preds by confidence desc
    all_preds = sorted(preds, key=lambda x: float(x.get("confidence", 0)), reverse=True)
    tp = np.zeros(len(all_preds), dtype=np.float64)
    fp = np.zeros(len(all_preds), dtype=np.float64)
    matched: dict[int, set[int]] = {i: set() for i in gt_by}

    for i, pred in enumerate(all_preds):
        img_id = int(pred["image_id"])
        gt_list = gt_by.get(img_id) or []
        if not gt_list:
            fp[i] = 1
            continue
        gt_arr = _boxes_array(gt_list)
        pred_arr = _boxes_array([pred])
        ious = _iou_xyxy(pred_arr, gt_arr)[0]
        best = int(np.argmax(ious)) if ious.size else -1
        best_iou = float(ious[best]) if best >= 0 else 0.0
        if best_iou >= iou_thr and best not in matched[img_id]:
            tp[i] = 1
            matched[img_id].add(best)
        else:
            fp[i] = 1

    npos = len(gts)
    if npos == 0:
        # 无 GT：若也无预测，AP 视为 1；有预测则全是 FP → AP=0
        return (1.0 if not preds else 0.0), [[0.0, 1.0], [1.0, 0.0]], {
            "tp": 0,
            "fp": len(preds),
            "fn": 0,
        }

    cum_tp = np.cumsum(tp)
    cum_fp = np.cumsum(fp)
    recalls = cum_tp / npos
    precisions = cum_tp / np.maximum(cum_tp + cum_fp, 1e-9)
    ap = _ap_from_pr(recalls, precisions)
    points = [[float(p), float(r)] for p, r in zip(precisions.tolist(), recalls.tolist())]
    if not points:
        points = [[1.0, 0.0], [0.0, 0.0]]
    fn = npos - int(cum_tp[-1]) if len(cum_tp) else npos
    return ap, points, {"tp": int(cum_tp[-1]) if len(cum_tp) else 0, "fp": int(cum_fp[-1]) if len(cum_fp) else 0, "fn": fn}


def _collect_error_samples(
    images: list[ImageEvalInput],
    iou_thr: float = 0.5,
) -> dict[str, list[dict[str, Any]]]:
    fp_list: list[dict[str, Any]] = []
    fn_list: list[dict[str, Any]] = []
    tp_list: list[dict[str, Any]] = []

    for im in images:
        gts = [{**g, "image_id": im.image_id} for g in im.gt_boxes]
        preds = sorted(
            [{**p, "image_id": im.image_id} for p in im.pred_boxes],
            key=lambda x: float(x.get("confidence", 0)),
            reverse=True,
        )
        gt_arr = _boxes_array(gts)
        matched_gt: set[int] = set()
        for pred in preds:
            if gt_arr.size == 0:
                fp_list.append(
                    enrich_norm_fields(
                        {
                            "image_id": im.image_id,
                            "error_type": "fp",
                            "category_id": int(pred["category_id"]),
                            "confidence": float(pred.get("confidence", 0)),
                            "x1": pred["x1"],
                            "y1": pred["y1"],
                            "x2": pred["x2"],
                            "y2": pred["y2"],
                            "image_width": im.width,
                            "image_height": im.height,
                            "thumbnail_url": f"/api/data/{im.image_id}/thumbnail",
                        }
                    )
                )
                continue
            ious = _iou_xyxy(_boxes_array([pred]), gt_arr)[0]
            # same-class match preferred
            best_j = -1
            best_iou = 0.0
            for j, gt in enumerate(gts):
                if j in matched_gt:
                    continue
                if int(gt["category_id"]) != int(pred["category_id"]):
                    continue
                if float(ious[j]) >= iou_thr and float(ious[j]) > best_iou:
                    best_iou = float(ious[j])
                    best_j = j
            if best_j >= 0:
                matched_gt.add(best_j)
                tp_list.append(
                    enrich_norm_fields(
                        {
                            "image_id": im.image_id,
                            "error_type": "tp",
                            "category_id": int(pred["category_id"]),
                            "confidence": float(pred.get("confidence", 0)),
                            "x1": pred["x1"],
                            "y1": pred["y1"],
                            "x2": pred["x2"],
                            "y2": pred["y2"],
                            "image_width": im.width,
                            "image_height": im.height,
                            "thumbnail_url": f"/api/data/{im.image_id}/thumbnail",
                        }
                    )
                )
            else:
                fp_list.append(
                    enrich_norm_fields(
                        {
                            "image_id": im.image_id,
                            "error_type": "fp",
                            "category_id": int(pred["category_id"]),
                            "confidence": float(pred.get("confidence", 0)),
                            "x1": pred["x1"],
                            "y1": pred["y1"],
                            "x2": pred["x2"],
                            "y2": pred["y2"],
                            "image_width": im.width,
                            "image_height": im.height,
                            "thumbnail_url": f"/api/data/{im.image_id}/thumbnail",
                        }
                    )
                )
        for j, gt in enumerate(gts):
            if j in matched_gt:
                continue
            fn_list.append(
                enrich_norm_fields(
                    {
                        "image_id": im.image_id,
                        "error_type": "fn",
                        "category_id": int(gt["category_id"]),
                        "x1": gt["x1"],
                        "y1": gt["y1"],
                        "x2": gt["x2"],
                        "y2": gt["y2"],
                        "image_width": im.width,
                        "image_height": im.height,
                        "thumbnail_url": f"/api/data/{im.image_id}/thumbnail",
                    }
                )
            )

    return {"fp": fp_list, "fn": fn_list, "tp": tp_list}


def _confusion_matrix(
    images: list[ImageEvalInput], iou_thr: float, labels: list[int]
) -> list[list[int]]:
    index = {c: i for i, c in enumerate(labels)}
    n = len(labels)
    # +1 background column/row for FP/FN against bg — keep square on classes only; FN as miss counted per GT class vs predicted
    mat = [[0 for _ in range(n)] for _ in range(n)]
    bg_fp = [0 for _ in range(n)]  # not returned in square; absorbed as diagonal noise skip

    for im in images:
        gts = list(im.gt_boxes)
        preds = sorted(im.pred_boxes, key=lambda x: float(x.get("confidence", 0)), reverse=True)
        gt_arr = _boxes_array(gts)
        matched: set[int] = set()
        for pred in preds:
            pc = int(pred["category_id"])
            if pc not in index:
                continue
            if gt_arr.size == 0:
                bg_fp[index[pc]] += 1
                continue
            ious = _iou_xyxy(_boxes_array([pred]), gt_arr)[0]
            best_j, best_iou = -1, 0.0
            for j, _gt in enumerate(gts):
                if j in matched:
                    continue
                if float(ious[j]) >= iou_thr and float(ious[j]) > best_iou:
                    best_iou = float(ious[j])
                    best_j = j
            if best_j >= 0:
                matched.add(best_j)
                gc = int(gts[best_j]["category_id"])
                if gc in index:
                    mat[index[gc]][index[pc]] += 1
            else:
                bg_fp[index[pc]] += 1
        for j, gt in enumerate(gts):
            if j in matched:
                continue
            gc = int(gt["category_id"])
            if gc in index:
                # FN: count on diagonal as 0 add; leave unmatched — optional row sum gap
                pass
    _ = bg_fp
    return mat


def evaluate_detection(
    images: list[ImageEvalInput],
    *,
    category_names: dict[int, str] | None = None,
    iou_thresholds: list[float] | None = None,
) -> dict[str, Any]:
    """主入口：返回 overall / per_class / pr / confusion / errors。

    无 GT 且无预测：指标为 0，不抛错。
    有 GT 无预测：mAP=0，errors 全 fn。
    """
    category_names = category_names or {}
    iou_thresholds = iou_thresholds or [round(x, 2) for x in np.arange(0.5, 1.0, 0.05)]

    # flatten with image_id
    all_gt: list[dict[str, Any]] = []
    all_pred: list[dict[str, Any]] = []
    for im in images:
        for g in im.gt_boxes:
            all_gt.append({**g, "image_id": im.image_id})
        for p in im.pred_boxes:
            all_pred.append({**p, "image_id": im.image_id})

    cat_ids = sorted(
        {
            int(x["category_id"])
            for x in all_gt + all_pred
            if x.get("category_id") is not None
        }
    )
    if not cat_ids:
        cat_ids = [1]

    # try pycocotools path for mAP when possible
    coco_stats = _try_pycocotools(images, cat_ids)

    per_class: list[dict[str, Any]] = []
    pr_by_class: dict[str, list[list[float]]] = {}
    ap50_list: list[float] = []
    ap_list_all_thr: list[float] = []

    for cid in cat_ids:
        gts = [g for g in all_gt if int(g["category_id"]) == cid]
        preds = [p for p in all_pred if int(p["category_id"]) == cid]
        ap50, points, _counts = _eval_class_at_iou(gts, preds, 0.5)
        ap50_list.append(ap50)
        pr_by_class[str(cid)] = points
        aps = []
        for thr in iou_thresholds:
            ap_t, _, _ = _eval_class_at_iou(gts, preds, float(thr))
            aps.append(ap_t)
        ap_list_all_thr.append(float(np.mean(aps)) if aps else 0.0)
        per_class.append(
            {
                "category_id": cid,
                "name": category_names.get(cid, str(cid)),
                "ap50": round(ap50, 4),
                "ap": round(float(np.mean(aps)) if aps else 0.0, 4),
            }
        )

    mAP50 = float(np.mean(ap50_list)) if ap50_list else 0.0
    mAP50_95 = float(np.mean(ap_list_all_thr)) if ap_list_all_thr else 0.0
    if coco_stats:
        mAP50 = float(coco_stats.get("mAP50", mAP50))
        mAP50_95 = float(coco_stats.get("mAP50_95", mAP50_95))

    # micro P/R at 0.5 across classes via error samples counts
    errors = _collect_error_samples(images, iou_thr=0.5)
    tp_n = len(errors["tp"])
    fp_n = len(errors["fp"])
    fn_n = len(errors["fn"])
    precision = tp_n / (tp_n + fp_n) if (tp_n + fp_n) else 0.0
    recall = tp_n / (tp_n + fn_n) if (tp_n + fn_n) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    )

    # overall PR: use first class or micro approximate from all
    overall_pr = pr_by_class.get(str(cat_ids[0])) or [[1.0, 0.0], [0.0, 0.0]]
    if len(cat_ids) > 1:
        # merge by evaluating all classes together at 0.5 (ignore class mismatch → treat all as one)
        merged_gt = [{**g, "category_id": 1} for g in all_gt]
        merged_pred = [{**p, "category_id": 1} for p in all_pred]
        _, overall_pr, _ = _eval_class_at_iou(merged_gt, merged_pred, 0.5)

    labels = [category_names.get(c, str(c)) for c in cat_ids]
    confusion = _confusion_matrix(images, 0.5, cat_ids)

    # per-size rough by GT box area
    size_buckets = {"small": [], "medium": [], "large": []}
    for cid in cat_ids:
        gts = [g for g in all_gt if int(g["category_id"]) == cid]
        preds = [p for p in all_pred if int(p["category_id"]) == cid]
        for bucket, lo, hi in (
            ("small", 0, 32**2),
            ("medium", 32**2, 96**2),
            ("large", 96**2, 1e18),
        ):
            g_b = [
                g
                for g in gts
                if lo <= max(0.0, (g["x2"] - g["x1"]) * (g["y2"] - g["y1"])) < hi
            ]
            if not g_b and not preds:
                continue
            ap_b, _, _ = _eval_class_at_iou(g_b, preds, 0.5)
            size_buckets[bucket].append(ap_b)
    per_size = {
        k: round(float(np.mean(v)), 4) if v else 0.0 for k, v in size_buckets.items()
    }

    return {
        "overall_metrics": {
            "mAP50": round(mAP50, 4),
            "mAP50_95": round(mAP50_95, 4),
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "fps": None,
            "engine": coco_stats.get("engine") if coco_stats else "builtin_iou",
        },
        "per_class_metrics": per_class,
        "per_size_metrics": per_size,
        "per_scene_metrics": {},
        "pr_curve_data": {"points": overall_pr, "by_class": pr_by_class},
        "confusion_matrix": confusion,
        "confusion_labels": labels,
        "error_samples": errors,
    }


def _try_pycocotools(
    images: list[ImageEvalInput], cat_ids: list[int]
) -> dict[str, Any] | None:
    try:
        from pycocotools.coco import COCO
        from pycocotools.cocoeval import COCOeval
    except ImportError:
        return None

    if not images:
        return {"mAP50": 0.0, "mAP50_95": 0.0, "engine": "pycocotools"}

    coco_images = []
    coco_anns = []
    coco_cats = [{"id": c, "name": str(c)} for c in cat_ids]
    ann_id = 1
    for im in images:
        coco_images.append(
            {"id": im.image_id, "width": im.width, "height": im.height, "file_name": str(im.image_id)}
        )
        for g in im.gt_boxes:
            x, y, w, h = xyxy_to_coco_bbox(g["x1"], g["y1"], g["x2"], g["y2"])
            coco_anns.append(
                {
                    "id": ann_id,
                    "image_id": im.image_id,
                    "category_id": int(g["category_id"]),
                    "bbox": [x, y, w, h],
                    "area": float(w * h),
                    "iscrowd": 0,
                }
            )
            ann_id += 1

    # pycocotools 要求至少有 annotations 结构
    gt = to_coco_gt(coco_images, coco_anns, coco_cats)
    if not coco_anns:
        # 无 GT：COCOeval 不稳定，退回内置
        return None

    coco_gt = COCO()
    coco_gt.dataset = gt
    coco_gt.createIndex()

    dts = []
    for im in images:
        for p in im.pred_boxes:
            x, y, w, h = xyxy_to_coco_bbox(p["x1"], p["y1"], p["x2"], p["y2"])
            dts.append(
                {
                    "image_id": im.image_id,
                    "category_id": int(p["category_id"]),
                    "bbox": [x, y, w, h],
                    "score": float(p.get("confidence", 0.0)),
                }
            )
    if not dts:
        # 空预测合法
        return {"mAP50": 0.0, "mAP50_95": 0.0, "engine": "pycocotools"}

    coco_dt = coco_gt.loadRes(dts)
    ev = COCOeval(coco_gt, coco_dt, "bbox")
    ev.evaluate()
    ev.accumulate()
    ev.summarize()
    # stats: 0=AP 0.5:0.95, 1=AP50
    return {
        "mAP50_95": float(ev.stats[0]),
        "mAP50": float(ev.stats[1]),
        "engine": "pycocotools",
    }
