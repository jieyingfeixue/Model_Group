"""Deterministic rule engine — zero latency checks."""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

from src.core.types import AutoAction, Label3D, RuleResult
from src.core.constants import CLASS_SIZE_PRIORS
from src.fusion.geometry import (
    count_points_in_box,
    extract_points_in_box,
    compute_bev_iou,
    compute_pca_yaw,
    angle_diff,
    estimate_ground_z_at,
)
from .tool_executor import FrameContext

logger = logging.getLogger(__name__)


class RuleEngine:
    """Deterministic rule checks — each box < 1 ms."""

    def __init__(self, config: dict[str, Any] | None = None):
        cfg = config or {}
        self.lidar_min_points = cfg.get("lidar_min_points", 3)
        self.lidar_zero_action = cfg.get("lidar_zero_action", "delete")
        self.dim_sigma = cfg.get("dimension_sigma_threshold", 3.0)
        self.overlap_iou = cfg.get("overlap_iou_threshold", 0.5)
        self.ground_pen = cfg.get("ground_penetration_threshold", 0.3)
        self.yaw_dev = np.deg2rad(cfg.get("yaw_deviation_threshold", 30))

    def check_all_boxes(self, ctx: FrameContext) -> list[RuleResult]:
        """Run all rules on every box in the frame."""
        results: list[RuleResult] = []
        for box in ctx.boxes:
            results.extend(self.check_all(box, ctx))
        return results

    def check_all(self, box: Label3D, ctx: FrameContext) -> list[RuleResult]:
        results = [
            self.check_lidar_support(box, ctx),
            self.check_dimension_prior(box),
            self.check_overlap(box, ctx.boxes),
            self.check_ground_penetration(box, ctx.ground_plane),
            self.check_yaw_consistency(box, ctx),
        ]
        return results

    def check_lidar_support(self, box: Label3D, ctx: FrameContext) -> RuleResult:
        pts = count_points_in_box(ctx.lidar_points, box) if ctx.lidar_points is not None else -1
        if pts == 0:
            return RuleResult(
                rule="lidar_support",
                severity="error",
                message=f"框内 0 个 LiDAR 点",
                auto_action=AutoAction(type="delete", confidence=0.9),
                box_id=box.object_id,
            )
        elif 0 < pts < self.lidar_min_points:
            return RuleResult(
                rule="lidar_support",
                severity="warning",
                message=f"框内仅 {pts} 个 LiDAR 点，建议复查",
                box_id=box.object_id,
            )
        return RuleResult(rule="lidar_support", severity="ok", box_id=box.object_id)

    def check_dimension_prior(self, box: Label3D) -> RuleResult:
        prior = CLASS_SIZE_PRIORS.get(box.class_name)
        if prior is None:
            return RuleResult(rule="dimension_prior", severity="ok", box_id=box.object_id)

        deviation = np.abs(box.dimensions - prior.mean) / np.maximum(prior.std, 1e-6)
        if np.any(deviation > self.dim_sigma):
            clamped = np.clip(
                box.dimensions,
                prior.mean - 2 * prior.std,
                prior.mean + 2 * prior.std,
            )
            return RuleResult(
                rule="dimension_prior",
                severity="warning",
                message=f"尺寸偏差 > {self.dim_sigma}σ: {deviation.max():.1f}σ",
                auto_action=AutoAction(
                    type="adjust_dimensions",
                    value=clamped.tolist(),
                    confidence=0.7,
                ),
                box_id=box.object_id,
            )
        return RuleResult(rule="dimension_prior", severity="ok", box_id=box.object_id)

    def check_overlap(self, box: Label3D, others: list[Label3D]) -> RuleResult:
        for other in others:
            if other.object_id == box.object_id:
                continue
            iou = compute_bev_iou(box, other)
            if iou > self.overlap_iou:
                return RuleResult(
                    rule="overlap",
                    severity="error",
                    message=f"与 {other.object_id} BEV IoU={iou:.2f}",
                    auto_action=AutoAction(type="delete_lower_score", confidence=0.85),
                    box_id=box.object_id,
                )
        return RuleResult(rule="overlap", severity="ok", box_id=box.object_id)

    def check_ground_penetration(self, box: Label3D, ground: np.ndarray | None) -> RuleResult:
        if ground is None:
            return RuleResult(rule="ground_penetration", severity="ok", box_id=box.object_id)
        bottom_z = box.center[2] - box.dimensions[2] / 2
        ground_z = estimate_ground_z_at(box.center[:2], ground)
        penetration = ground_z - bottom_z
        if penetration > self.ground_pen:
            corrected_z = box.center[2] + penetration
            return RuleResult(
                rule="ground_penetration",
                severity="warning",
                message=f"框底面穿入地面 {penetration:.2f}m",
                auto_action=AutoAction(
                    type="adjust_center_z",
                    value=float(corrected_z),
                    confidence=0.9,
                ),
                box_id=box.object_id,
            )
        return RuleResult(rule="ground_penetration", severity="ok", box_id=box.object_id)

    def check_yaw_consistency(self, box: Label3D, ctx: FrameContext) -> RuleResult:
        if ctx.lidar_points is None:
            return RuleResult(rule="yaw_consistency", severity="skip", box_id=box.object_id)
        pts = extract_points_in_box(ctx.lidar_points, box)
        if len(pts) < 10:
            return RuleResult(rule="yaw_consistency", severity="skip", box_id=box.object_id)
        pca_yaw = compute_pca_yaw(pts[:, :2])
        yaw_diff = angle_diff(box.rotation, pca_yaw)
        if yaw_diff > self.yaw_dev:
            return RuleResult(
                rule="yaw_consistency",
                severity="warning",
                message=f"航向角与点云主轴偏差 {np.rad2deg(yaw_diff):.0f}°",
                auto_action=AutoAction(
                    type="adjust_yaw",
                    value=float(pca_yaw),
                    confidence=0.6,
                ),
                box_id=box.object_id,
            )
        return RuleResult(rule="yaw_consistency", severity="ok", box_id=box.object_id)
