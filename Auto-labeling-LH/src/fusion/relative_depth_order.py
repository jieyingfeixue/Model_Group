"""Box-level relative depth ordering from an inverse-depth map."""

from __future__ import annotations

import numpy as np


def score_boxes(
    inverse_depth: np.ndarray,
    boxes: list[dict],
) -> list[float | None]:
    """Return robust box scores; larger values mean nearer objects."""
    depth = np.asarray(inverse_depth, dtype=np.float32)
    h, w = depth.shape[:2]
    scores: list[float | None] = []
    for box in boxes:
        x0, y0, x1, y1 = [float(v) for v in box["bbox_xyxy"]]
        bw, bh = max(1.0, x1 - x0), max(1.0, y1 - y0)
        # Inset suppresses sky, wires, and neighboring objects at box borders.
        xa = max(0, min(w, int(round(x0 + 0.18 * bw))))
        xb = max(0, min(w, int(round(x1 - 0.18 * bw))))
        ya = max(0, min(h, int(round(y0 + 0.18 * bh))))
        yb = max(0, min(h, int(round(y1 - 0.12 * bh))))
        crop = depth[ya:yb, xa:xb]
        valid = crop[np.isfinite(crop) & (crop > 0)]
        if valid.size < 16:
            scores.append(None)
            continue
        scores.append(float(np.percentile(valid, 60)))
    return scores


def relative_tiers(scores: list[float | None]) -> list[str | None]:
    """Split valid scores into stable near/middle/far quantile tiers."""
    valid = np.asarray([v for v in scores if v is not None], dtype=np.float64)
    if valid.size == 0:
        return [None] * len(scores)
    if valid.size == 1 or float(np.ptp(valid)) < 1e-6:
        return ["middle" if v is not None else None for v in scores]
    q_near, q_far = np.percentile(valid, [66.7, 33.3])
    result = []
    for value in scores:
        if value is None:
            result.append(None)
        elif value >= q_near:
            result.append("near")
        elif value <= q_far:
            result.append("far")
        else:
            result.append("middle")
    return result


def reject_metric_order_conflicts(
    boxes: list[dict],
    *,
    inversion_ratio: float = 1.15,
) -> list[dict]:
    """Remove unsupported metric depths that invert a clear near/far order."""
    result = [dict(box) for box in boxes]
    map_backed = [
        bool(box.get("target_id"))
        or str(box.get("method", "")).startswith("gps_db")
        for box in result
    ]
    reject = set()
    for near_i, near in enumerate(result):
        if near.get("relative_depth_tier") != "near":
            continue
        near_depth = near.get("depth_m")
        if not isinstance(near_depth, (int, float)):
            continue
        for far_i, far in enumerate(result):
            if far.get("relative_depth_tier") != "far":
                continue
            far_depth = far.get("depth_m")
            if not isinstance(far_depth, (int, float)):
                continue
            if float(near_depth) <= float(far_depth) * inversion_ratio:
                continue
            if map_backed[near_i] and map_backed[far_i]:
                continue
            if map_backed[near_i]:
                reject.add(far_i)
            elif map_backed[far_i]:
                reject.add(near_i)
            else:
                reject.update((near_i, far_i))

    tier_text = {"near": "相对近", "middle": "相对中", "far": "相对远"}
    for index in reject:
        row = result[index]
        row["rejected_depth_m"] = row.get("depth_m")
        row["depth_m"] = None
        row["depth_text"] = tier_text.get(
            row.get("relative_depth_tier"), "相对深度冲突"
        )
        row["method"] = "relative_order_conflict_rejected"
    return result
