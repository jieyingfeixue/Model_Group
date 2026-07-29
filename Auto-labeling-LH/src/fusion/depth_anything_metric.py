"""DepthAnythingV2 metric calibration + virtual point cloud generation.

Purpose
-------
LiDAR sees only the visible *surface* of objects, and far-range returns are
sparse (10-30 pts on a car at 25 m).  We use DepthAnythingV2 (DA2) on the
2D bbox crop to densify the cluster:

    1.  DA2 returns a *relative* depth map  d_rel(u, v)  (no metric scale).
    2.  We project the real LiDAR points inside the bbox onto the same
        crop and pair them with DA2's relative depths at those pixels.
    3.  Linear regression  d_metric = a * d_rel + b  gives the metric scale.
    4.  All bbox pixels are then back-projected to 3D using d_metric and the
        camera intrinsics to produce *virtual LiDAR points* in the LiDAR
        (world) frame.

These virtual points complement the real LiDAR.  They are noisier (RMS
~0.5 m at 25 m for DA2 ViT-S) so the caller should weight them lower than
real LiDAR returns.

Public API
----------
    pts_world = generate_virtual_pts(image_rgb, bbox, depth_estimator,
                                     calib, camera, lidar_pts, mask=None)

Returns ``(N, 3)`` float64 in the LiDAR frame, or ``None`` when there are
not enough real LiDAR pairs to calibrate.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from src.core.types import CalibrationBundle
    from src.models.depth_estimator import DepthEstimator

logger = logging.getLogger(__name__)


# Need at least this many (LiDAR pixel, DA depth) pairs to fit a*d+b
_MIN_CALIB_PAIRS = 5

# Cap virtual point count per box (prevents 200k pts on a giant bbox)
_MAX_VIRTUAL_PTS = 4000


def generate_virtual_pts(
    image_rgb: np.ndarray,
    bbox: tuple[float, float, float, float],
    depth_estimator: "DepthEstimator",
    calib: "CalibrationBundle",
    camera: str,
    lidar_pts: np.ndarray,
    mask: np.ndarray | None = None,
    stride: int = 4,
) -> np.ndarray | None:
    """Generate virtual LiDAR-like points for *bbox* using DA2 + LiDAR scale.

    Parameters
    ----------
    image_rgb     : full RGB image (H, W, 3)  uint8
    bbox          : (x1, y1, x2, y2) in full-image pixel coords
    depth_estimator : DepthEstimator instance (already loaded)
    calib         : CalibrationBundle
    camera        : camera key
    lidar_pts     : (N, 3+) real LiDAR points in world frame
    mask          : optional HxW bool, restricts virtual pts to mask area
    stride        : pixel sampling stride (4 = every 4th pixel both axes)

    Returns
    -------
    (M, 3) float64 in LiDAR/world frame, or None if calibration failed.
    """
    if depth_estimator is None or image_rgb is None:
        return None

    h_img, w_img = image_rgb.shape[:2]
    x1, y1, x2, y2 = [int(round(v)) for v in bbox]
    x1 = max(0, x1); y1 = max(0, y1)
    x2 = min(w_img - 1, x2); y2 = min(h_img - 1, y2)
    if x2 - x1 < 8 or y2 - y1 < 8:
        return None

    # --- 1.  DA2 relative depth on the bbox crop ----------------------------
    crop = image_rgb[y1:y2 + 1, x1:x2 + 1]
    try:
        d_rel_crop = depth_estimator.estimate(crop)  # (h, w) float32
    except Exception:
        logger.exception("DA2 estimate failed on crop")
        return None
    if d_rel_crop is None or d_rel_crop.size == 0:
        return None
    # Resize back if estimator returned a different size
    if d_rel_crop.shape[:2] != (y2 - y1 + 1, x2 - x1 + 1):
        import cv2
        d_rel_crop = cv2.resize(
            d_rel_crop, (x2 - x1 + 1, y2 - y1 + 1),
            interpolation=cv2.INTER_LINEAR,
        )

    # --- 2.  Project real LiDAR pts into the bbox crop ----------------------
    intr = calib.intrinsics.get(camera)
    extr = calib.extrinsics.get(camera, np.eye(4))
    if intr is None:
        return None
    pts_h = np.hstack([lidar_pts[:, :3], np.ones((len(lidar_pts), 1))])
    cam_z = (extr @ pts_h.T)[2]
    try:
        pixels = calib.project_3d_to_image(lidar_pts[:, :3], camera)
    except Exception:
        return None
    in_bbox = (
        (cam_z > 0.1)
        & (pixels[:, 0] >= x1) & (pixels[:, 0] <= x2)
        & (pixels[:, 1] >= y1) & (pixels[:, 1] <= y2)
    )
    if mask is not None and mask.shape[:2] == (h_img, w_img):
        u_int = np.clip(pixels[:, 0].astype(np.int32), 0, w_img - 1)
        v_int = np.clip(pixels[:, 1].astype(np.int32), 0, h_img - 1)
        in_bbox &= mask[v_int, u_int]
    pair_idx = np.where(in_bbox)[0]
    if len(pair_idx) < _MIN_CALIB_PAIRS:
        logger.debug("DA-metric: only %d LiDAR pts in bbox, need >=%d",
                     len(pair_idx), _MIN_CALIB_PAIRS)
        return None

    # Sample DA depth at the LiDAR projection pixels (relative to crop)
    u_crop = pixels[pair_idx, 0] - x1
    v_crop = pixels[pair_idx, 1] - y1
    u_int = np.clip(u_crop.astype(np.int32), 0, d_rel_crop.shape[1] - 1)
    v_int = np.clip(v_crop.astype(np.int32), 0, d_rel_crop.shape[0] - 1)
    d_rel_at_lidar = d_rel_crop[v_int, u_int]
    d_metric_at_lidar = cam_z[pair_idx]

    # --- 3.  Robust linear fit  d_metric = a * d_rel + b --------------------
    # Use median-of-residuals trim once
    A = np.column_stack([d_rel_at_lidar, np.ones_like(d_rel_at_lidar)])
    try:
        sol, *_ = np.linalg.lstsq(A, d_metric_at_lidar, rcond=None)
        a, b = float(sol[0]), float(sol[1])
        # Trim outliers and re-fit
        resid = np.abs(A @ sol - d_metric_at_lidar)
        keep = resid < (np.median(resid) * 3.0 + 0.5)
        if keep.sum() >= _MIN_CALIB_PAIRS:
            sol, *_ = np.linalg.lstsq(A[keep], d_metric_at_lidar[keep], rcond=None)
            a, b = float(sol[0]), float(sol[1])
    except Exception:
        logger.exception("DA-metric calibration linear fit failed")
        return None

    if not np.isfinite(a) or not np.isfinite(b) or abs(a) < 1e-6:
        return None

    # --- 4.  Backproject every Nth pixel using d_metric ---------------------
    h_c, w_c = d_rel_crop.shape[:2]
    ys, xs = np.mgrid[0:h_c:stride, 0:w_c:stride]
    d_rel_sample = d_rel_crop[ys, xs]
    d_metric_sample = a * d_rel_sample + b
    # Filter: positive depth, within range
    valid = (d_metric_sample > 0.5) & (d_metric_sample < 100.0)
    if mask is not None and mask.shape[:2] == (h_img, w_img):
        v_full = (ys + y1).astype(np.int32)
        u_full = (xs + x1).astype(np.int32)
        valid &= mask[v_full, u_full]
    if not np.any(valid):
        return None

    u_full = (xs[valid] + x1).astype(np.float32)
    v_full = (ys[valid] + y1).astype(np.float32)
    z_cam = d_metric_sample[valid].astype(np.float32)

    # Pixel -> camera frame
    Xc = (u_full - intr.cx) * z_cam / intr.fx
    Yc = (v_full - intr.cy) * z_cam / intr.fy
    pts_cam = np.column_stack([Xc, Yc, z_cam])

    # Camera -> world (LiDAR) frame
    T_inv = np.linalg.inv(extr)
    pts_h2 = np.hstack([pts_cam, np.ones((pts_cam.shape[0], 1), dtype=np.float32)])
    pts_world = (T_inv @ pts_h2.T).T[:, :3]

    if len(pts_world) > _MAX_VIRTUAL_PTS:
        idx = np.random.default_rng(0).choice(
            len(pts_world), _MAX_VIRTUAL_PTS, replace=False)
        pts_world = pts_world[idx]

    return pts_world.astype(np.float64)
