"""Refine 3D boxes using LiDAR point cloud fitting."""

from __future__ import annotations

import numpy as np

from src.core.types import Label3D
from .geometry import extract_points_in_box, compute_pca_yaw, estimate_ground_z_at


class LiDARFitter:
    """Fit / refine a 3D bounding box using LiDAR points."""

    def __init__(self, expand_search: float = 1.5, min_points: int = 3):
        self.expand_search = expand_search
        self.min_points = min_points

    def fit(
        self,
        box: Label3D,
        points: np.ndarray,
        ground_plane: np.ndarray | None = None,
    ) -> Label3D:
        """Refine *box* centre/dimensions/yaw using enclosed LiDAR points."""
        pts = extract_points_in_box(points, box, expand=self.expand_search)
        if len(pts) < self.min_points:
            return box  # not enough support

        pts_3d = pts[:, :3]
        result = box.copy()

        # Centre from point cloud centroid
        centroid = pts_3d.mean(axis=0)
        result.center = centroid.copy()

        # Dimensions from min/max along principal axes
        pca_yaw = compute_pca_yaw(pts_3d[:, :2])
        c, s = np.cos(-pca_yaw), np.sin(-pca_yaw)
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        local = (pts_3d - centroid) @ rot.T
        mins = local.min(axis=0)
        maxs = local.max(axis=0)
        fitted_dims = maxs - mins
        # Don't let fitted dims be unreasonably small
        fitted_dims = np.maximum(fitted_dims, 0.3)
        result.dimensions = fitted_dims
        result.rotation = pca_yaw

        # Snap bottom to ground plane
        if ground_plane is not None:
            gz = estimate_ground_z_at(result.center[:2], ground_plane)
            result.center[2] = gz + result.dimensions[2] / 2.0

        result.source = "refined"
        return result
