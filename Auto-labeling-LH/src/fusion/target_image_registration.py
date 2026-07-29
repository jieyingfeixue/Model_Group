"""Robust 2D registration between radar target anchors and image boxes."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment


@dataclass(frozen=True)
class PixelRegistration:
    scale_x: float = 1.0
    scale_y: float = 1.0
    offset_x: float = 0.0
    offset_y: float = 0.0
    center_x: float = 0.0
    center_y: float = 0.0
    match_count: int = 0
    median_error_px: float = float("inf")

    @property
    def valid(self) -> bool:
        return self.match_count > 0 and np.isfinite(self.median_error_px)


def apply_pixel_registration(
    points: np.ndarray,
    registration: PixelRegistration,
) -> np.ndarray:
    pixels = np.asarray(points, dtype=np.float64)
    center = np.array(
        [registration.center_x, registration.center_y], dtype=np.float64
    )
    scale = np.array(
        [registration.scale_x, registration.scale_y], dtype=np.float64
    )
    offset = np.array(
        [registration.offset_x, registration.offset_y], dtype=np.float64
    )
    return (pixels - center) * scale + center + offset


def _assignment(
    box_centers: np.ndarray,
    target_pixels: np.ndarray,
    box_sizes: np.ndarray,
    *,
    max_distance_px: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if not len(box_centers) or not len(target_pixels):
        empty = np.empty(0, dtype=np.int64)
        return empty, empty, np.empty(0, dtype=np.float64)
    delta = box_centers[:, None, :] - target_pixels[None, :, :]
    distances = np.linalg.norm(delta, axis=2)
    rows, cols = linear_sum_assignment(distances)
    limits = np.maximum(
        max_distance_px,
        0.65 * np.linalg.norm(box_sizes[rows], axis=1),
    )
    keep = distances[rows, cols] <= limits
    return rows[keep], cols[keep], distances[rows[keep], cols[keep]]


def estimate_pixel_registration(
    boxes_xyxy: np.ndarray,
    target_pixels: np.ndarray,
    image_size: tuple[int, int],
    *,
    max_distance_px: float | None = None,
) -> PixelRegistration:
    """Estimate a conservative scale plus translation registration.

    Candidate translations are generated from every box/target pair. The best
    candidate maximizes one-to-one matches before a small scale correction is
    fitted from the accepted anchors.
    """
    boxes = np.asarray(boxes_xyxy, dtype=np.float64).reshape(-1, 4)
    targets = np.asarray(target_pixels, dtype=np.float64).reshape(-1, 2)
    width, height = map(float, image_size)
    center = np.array([width * 0.5, height * 0.5], dtype=np.float64)
    fallback = PixelRegistration(center_x=center[0], center_y=center[1])
    if not len(boxes) or not len(targets):
        return fallback

    valid_boxes = (
        np.all(np.isfinite(boxes), axis=1)
        & (boxes[:, 2] > boxes[:, 0])
        & (boxes[:, 3] > boxes[:, 1])
    )
    valid_targets = np.all(np.isfinite(targets), axis=1)
    boxes = boxes[valid_boxes]
    targets = targets[valid_targets]
    if not len(boxes) or not len(targets):
        return fallback

    box_centers = (boxes[:, :2] + boxes[:, 2:]) * 0.5
    box_sizes = boxes[:, 2:] - boxes[:, :2]
    threshold = (
        float(max_distance_px)
        if max_distance_px is not None
        else max(55.0, min(width, height) * 0.09)
    )

    best: tuple[int, float, np.ndarray, np.ndarray] | None = None
    for box_center in box_centers:
        for target in targets:
            offset = box_center - target
            if abs(offset[0]) > width * 0.55 or abs(offset[1]) > height * 0.55:
                continue
            shifted = targets + offset
            rows, cols, distances = _assignment(
                box_centers,
                shifted,
                box_sizes,
                max_distance_px=threshold,
            )
            if not len(rows):
                continue
            score = (len(rows), -float(np.median(distances)))
            if best is None or score > (best[0], best[1]):
                best = (score[0], score[1], rows, cols)
                best_offset = offset
    if best is None:
        return fallback

    rows, cols = best[2], best[3]
    matched_boxes = box_centers[rows]
    matched_targets = targets[cols]
    scale_x = 1.0
    scale_y = 1.0
    if len(rows) >= 2:
        target_span_x = float(np.ptp(matched_targets[:, 0]))
        target_span_y = float(np.ptp(matched_targets[:, 1]))
        if target_span_x >= width * 0.06:
            scale_x = float(
                np.clip(
                    np.ptp(matched_boxes[:, 0]) / target_span_x,
                    0.82,
                    1.18,
                )
            )
        if len(rows) >= 3 and target_span_y >= height * 0.08:
            scale_y = float(
                np.clip(
                    np.ptp(matched_boxes[:, 1]) / target_span_y,
                    0.90,
                    1.10,
                )
            )

    scaled_targets = (
        (targets - center)
        * np.array([scale_x, scale_y], dtype=np.float64)
        + center
    )
    offset = np.median(
        matched_boxes - scaled_targets[cols],
        axis=0,
    )
    offset[0] = np.clip(offset[0], -width * 0.55, width * 0.55)
    offset[1] = np.clip(offset[1], -height * 0.55, height * 0.55)
    transformed = scaled_targets + offset
    rows, cols, distances = _assignment(
        box_centers,
        transformed,
        box_sizes,
        max_distance_px=threshold,
    )
    if not len(rows):
        return fallback

    # A single anchor may correct camera shake by translation. Scale changes
    # require at least two independent correspondences.
    if len(rows) == 1:
        scale_x = scale_y = 1.0
        offset = box_centers[rows[0]] - targets[cols[0]]
        transformed = targets + offset
        distances = np.linalg.norm(
            box_centers[rows] - transformed[cols], axis=1
        )

    return PixelRegistration(
        scale_x=scale_x,
        scale_y=scale_y,
        offset_x=float(offset[0]),
        offset_y=float(offset[1]),
        center_x=float(center[0]),
        center_y=float(center[1]),
        match_count=int(len(rows)),
        median_error_px=float(np.median(distances)),
    )
