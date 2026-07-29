"""SAM2-mask + LiDAR-frustum 3D box fitting (A2 path).

Pipeline
--------
    image bbox  ─►  SAM2 mask  ─►  keep LiDAR pts whose pixel falls inside mask
                                           │
                                           ├─►  DBSCAN cluster (largest cluster)
                                           │
                                           └─►  PCA-yaw + AABB → Label3D

Falls back to:
  - bbox-only frustum if mask is empty / SAM unavailable
  - ground-ray intersection if no LiDAR pts inside mask/frustum
    (delegated to the legacy ``ImageTo3DProjector``)
"""
from __future__ import annotations

import logging
from typing import Tuple

import numpy as np

from src.core.types import CalibrationBundle, Detection2D, Label3D
from src.core.constants import CLASS_SIZE_PRIORS
from src.fusion.geometry import compute_pca_yaw, estimate_ground_z_at

logger = logging.getLogger(__name__)

_MIN_PTS = 5
_Z_MIN = -3.0
_Z_MAX = 8.0


def _project_lidar_to_pixels(
    lidar_pts: np.ndarray, calib: CalibrationBundle, camera: str,
) -> Tuple[np.ndarray, np.ndarray]:
    """Return (pixels Nx2, cam_z N) for all LiDAR points wrt *camera*."""
    T = calib.extrinsics.get(camera, np.eye(4))
    pts_h = np.hstack([lidar_pts[:, :3], np.ones((len(lidar_pts), 1))])
    cam_z = (T @ pts_h.T)[2]
    pixels = calib.project_3d_to_image(lidar_pts[:, :3], camera)
    return pixels, cam_z


def _largest_dbscan_cluster(pts: np.ndarray, eps: float = 0.6, min_samples: int = 3) -> np.ndarray:
    """Return the largest DBSCAN cluster of *pts* (Nx3).  Falls back to all-pts."""
    if len(pts) < min_samples:
        return pts
    try:
        from sklearn.cluster import DBSCAN
        labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(pts)
        if labels.max() < 0:
            return pts
        # pick cluster with most points (excluding noise = -1)
        unique, counts = np.unique(labels[labels >= 0], return_counts=True)
        best = unique[counts.argmax()]
        return pts[labels == best]
    except Exception:
        return pts


def _fit_oriented_box(
    pts: np.ndarray,
    class_name: str,
    score: float,
    ground_plane: np.ndarray | None,
    source: str,
) -> Label3D:
    """Centroid + PCA-yaw + AABB-in-yawed-frame → Label3D."""
    centroid = pts.mean(axis=0)
    pca_yaw = compute_pca_yaw(pts[:, :2])
    c, s = np.cos(-pca_yaw), np.sin(-pca_yaw)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    local = (pts - centroid) @ rot.T
    mins, maxs = local.min(axis=0), local.max(axis=0)
    dims = np.maximum(maxs - mins, 0.3)

    center = centroid.copy()
    if ground_plane is not None:
        gz = estimate_ground_z_at(center[:2], ground_plane)
        center[2] = gz + dims[2] / 2.0

    prior = CLASS_SIZE_PRIORS.get(class_name)
    if prior is not None:
        dims = np.clip(dims, prior.mean * 0.5, prior.mean * 2.0)

    return Label3D(
        class_name=class_name,
        center=center,
        dimensions=dims,
        rotation=pca_yaw,
        score=float(score),
        source=source,
    )


def fit_box_with_sam2(
    image_rgb: np.ndarray,
    bbox: tuple[float, float, float, float],
    class_name: str,
    calib: CalibrationBundle,
    camera: str,
    lidar_points: np.ndarray,
    segmentor=None,
    ground_plane: np.ndarray | None = None,
    score: float = 1.0,
) -> Tuple[Label3D | None, np.ndarray | None]:
    """Fit a 3D box from a 2D bbox using SAM2-mask + LiDAR frustum.

    Returns ``(Label3D, mask)`` on success; ``(None, None)`` when no LiDAR
    points are found and the caller should fall back to the legacy projector.
    The returned mask (HxW bool) is the SAM2 mask used (may be ``None`` when
    bbox-only path was taken).
    """
    if lidar_points is None or len(lidar_points) < _MIN_PTS:
        return None, None

    h_img, w_img = image_rgb.shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    x1, x2 = max(0.0, x1), min(float(w_img - 1), x2)
    y1, y2 = max(0.0, y1), min(float(h_img - 1), y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None, None

    # 1. SAM2 mask
    mask: np.ndarray | None = None
    if segmentor is not None:
        try:
            mask = segmentor.segment(image_rgb, bbox=(x1, y1, x2, y2))
        except Exception:
            logger.exception("SAM2 segment() raised; using bbox-only path")
            mask = None

    # 2. Project LiDAR pts → pixels
    pixels, cam_z = _project_lidar_to_pixels(lidar_points, calib, camera)

    # 3. Build frustum mask (in front of camera + bbox) and (optional) refine via SAM mask
    in_bbox = (
        (cam_z > 0.1)
        & (pixels[:, 0] >= x1) & (pixels[:, 0] <= x2)
        & (pixels[:, 1] >= y1) & (pixels[:, 1] <= y2)
        & (lidar_points[:, 2] >= _Z_MIN) & (lidar_points[:, 2] <= _Z_MAX)
    )
    if mask is not None and mask.shape[:2] == (h_img, w_img):
        u = np.clip(pixels[:, 0].astype(np.int32), 0, w_img - 1)
        v = np.clip(pixels[:, 1].astype(np.int32), 0, h_img - 1)
        in_mask = mask[v, u]
        in_frustum = in_bbox & in_mask
        if in_frustum.sum() < _MIN_PTS:
            # mask was too tight (e.g. SAM segmented only a window) → fall back
            in_frustum = in_bbox
    else:
        in_frustum = in_bbox

    pts = lidar_points[in_frustum, :3]
    if len(pts) < _MIN_PTS:
        return None, mask

    # 4. DBSCAN to drop background "halo" points (road, neighbour vehicles)
    pts = _largest_dbscan_cluster(pts, eps=0.6, min_samples=3)
    if len(pts) < _MIN_PTS:
        return None, mask

    box = _fit_oriented_box(
        pts, class_name=class_name, score=score,
        ground_plane=ground_plane, source="sam2_frustum",
    )
    return box, mask
