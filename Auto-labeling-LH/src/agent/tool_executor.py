"""Tool executor and FrameContext for the agent system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from src.core.types import Label3D
from src.fusion.geometry import (
    count_points_in_box,
    extract_points_in_box,
    compute_pca_yaw,
    compute_bev_iou,
)
from src.fusion.radar_projection import compute_radar_stats


@dataclass
class FrameContext:
    """All data needed by the agent to review a frame."""

    seq_id: str = ""
    frame_id: str = ""
    boxes: list[Label3D] = field(default_factory=list)
    lidar_points: np.ndarray | None = None
    radar_tensor: np.ndarray | None = None
    radar_config: dict[str, Any] | None = None
    ground_plane: np.ndarray | None = None
    sensor_fov: dict[str, float] | None = None

    def get_box(self, box_id: str) -> Label3D | None:
        for b in self.boxes:
            if b.object_id == box_id:
                return b
        return None


def execute_tool(name: str, params: dict, ctx: FrameContext) -> dict:
    """Execute an agent tool and return JSON-serializable result."""
    handler = _TOOL_MAP.get(name)
    if handler is None:
        return {"error": f"Unknown tool: {name}"}
    return handler(params, ctx)


# ── Tool implementations ───────────────────────────────────────────

def _get_box_info(params: dict, ctx: FrameContext) -> dict:
    box = ctx.get_box(params["box_id"])
    if box is None:
        return {"error": f"Box {params['box_id']} not found"}
    lidar_count = count_points_in_box(ctx.lidar_points, box) if ctx.lidar_points is not None else 0
    radar_stats = compute_radar_stats(ctx.radar_tensor, box, ctx.radar_config)
    return {
        "box_id": box.object_id,
        "class": box.class_name,
        "center": box.center.tolist(),
        "dimensions": box.dimensions.tolist(),
        "yaw_deg": float(np.rad2deg(box.rotation)),
        "score": box.score,
        "source": box.source,
        "lidar_points_in_box": lidar_count,
        "radar_max_power": radar_stats.get("max_power", 0.0),
        "radar_mean_power": radar_stats.get("mean_power", 0.0),
        "distance_from_origin": float(np.linalg.norm(box.center[:2])),
    }


def _get_nearby_boxes(params: dict, ctx: FrameContext) -> dict:
    box = ctx.get_box(params["box_id"])
    if box is None:
        return {"error": "Box not found"}
    radius = params.get("radius", 10.0)
    nearby = []
    for b in ctx.boxes:
        if b.object_id == box.object_id:
            continue
        dist = float(np.linalg.norm(b.center[:2] - box.center[:2]))
        if dist <= radius:
            nearby.append({
                "box_id": b.object_id,
                "class": b.class_name,
                "distance": round(dist, 2),
                "bev_iou": round(compute_bev_iou(box, b), 3),
            })
    return {"nearby": nearby}


def _get_lidar_cluster_stats(params: dict, ctx: FrameContext) -> dict:
    box = ctx.get_box(params["box_id"])
    if box is None:
        return {"error": "Box not found"}
    expand = params.get("expand_ratio", 1.0)
    pts = extract_points_in_box(ctx.lidar_points, box, expand=expand) if ctx.lidar_points is not None else np.empty((0, 4))
    if len(pts) == 0:
        return {"count": 0}
    pts3 = pts[:, :3]
    return {
        "count": len(pts),
        "centroid": pts3.mean(axis=0).tolist(),
        "min": pts3.min(axis=0).tolist(),
        "max": pts3.max(axis=0).tolist(),
        "std": pts3.std(axis=0).tolist(),
        "pca_yaw_deg": float(np.rad2deg(compute_pca_yaw(pts3[:, :2]))),
    }


def _get_radar_power(params: dict, ctx: FrameContext) -> dict:
    box = ctx.get_box(params["box_id"])
    if box is None:
        return {"error": "Box not found"}
    return compute_radar_stats(ctx.radar_tensor, box, ctx.radar_config)


def _adjust_box(params: dict, ctx: FrameContext) -> dict:
    return {"status": "recorded", "box_id": params["box_id"], "adjustments": params.get("adjustments", {})}


def _delete_box(params: dict, ctx: FrameContext) -> dict:
    return {"status": "recorded", "box_id": params["box_id"]}


def _confirm_box(params: dict, ctx: FrameContext) -> dict:
    return {"status": "confirmed", "box_id": params["box_id"]}


def _refit_box(params: dict, ctx: FrameContext) -> dict:
    box = ctx.get_box(params["box_id"])
    if box is None:
        return {"error": "Box not found"}
    if ctx.lidar_points is None:
        return {"error": "No LiDAR data"}
    from src.fusion.lidar_fitting import LiDARFitter
    fitter = LiDARFitter()
    refitted = fitter.fit(box, ctx.lidar_points, ctx.ground_plane)
    return {
        "status": "refitted",
        "old_center": box.center.tolist(),
        "new_center": refitted.center.tolist(),
        "old_dims": box.dimensions.tolist(),
        "new_dims": refitted.dimensions.tolist(),
    }


def _get_frame_summary(params: dict, ctx: FrameContext) -> dict:
    class_counts: dict[str, int] = {}
    total_lidar = 0
    for b in ctx.boxes:
        class_counts[b.class_name] = class_counts.get(b.class_name, 0) + 1
        if ctx.lidar_points is not None:
            total_lidar += count_points_in_box(ctx.lidar_points, b)
    return {
        "total_boxes": len(ctx.boxes),
        "class_counts": class_counts,
        "avg_lidar_pts": total_lidar / max(len(ctx.boxes), 1),
    }


def _get_temporal_context(params: dict, ctx: FrameContext) -> dict:
    # Temporal context requires cross-frame data not available in single-frame context
    return {"status": "not_available", "reason": "Temporal context requires multi-frame loading"}


_TOOL_MAP = {
    "get_box_info": _get_box_info,
    "get_nearby_boxes": _get_nearby_boxes,
    "get_lidar_cluster_stats": _get_lidar_cluster_stats,
    "get_radar_power_in_box": _get_radar_power,
    "adjust_box": _adjust_box,
    "delete_box": _delete_box,
    "confirm_box": _confirm_box,
    "refit_box_to_lidar": _refit_box,
    "get_frame_summary": _get_frame_summary,
    "get_temporal_context": _get_temporal_context,
}
