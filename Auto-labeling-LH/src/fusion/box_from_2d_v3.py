"""Unified 2D-bbox -> 3D-box pipeline (Plan A).

Pipeline
--------
    user 2D bbox
        |
        v
    [optional]  SAM2 / MobileSAM  ->  pixel mask
        |
        v
    LiDAR points whose projection falls in mask (or bbox)
        +
    [optional]  DepthAnythingV2 metric-calibrated virtual points
        |
        v
    DBSCAN largest cluster (drops road / neighbour pts)
        |
        v
    L-shape BEV fit  ->  yaw, center_xy, L, W
        +
    Class prior expand_to_prior  (away from camera)
        +
    Height: percentile of cluster Z, snap to ground plane
        |
        v
    Label3D

Quality presets
---------------
    fast :  MobileSAM       + DA2 (small) + L-shape
    full :  SAM2-Hiera-L    + DA2 (small) + L-shape (5x slower on CPU)
    auto :  full if CUDA available, else fast
    none :  no SAM mask, no DA2 (fastest, lowest accuracy)

The presets are advisory: if the requested SAM backend fails to load we
silently downgrade.  The function never crashes - it always returns a
Label3D (or None when even the LiDAR-only fallback has too few points).
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import numpy as np

from src.core.constants import CLASS_SIZE_PRIORS
from src.core.types import Label3D
from src.fusion.geometry import estimate_ground_z_at
from src.fusion.lshape_fit import fit_lshape, expand_to_prior

if TYPE_CHECKING:
    from src.core.types import CalibrationBundle
    from src.models.segmentor import Segmentor
    from src.models.depth_estimator import DepthEstimator

logger = logging.getLogger(__name__)


_MIN_PTS = 5

# Class-name synonyms (case-insensitive) so user-typed "Car"/"sedan"/"vehicle"
# all resolve to the same prior.
_CLASS_SYN = {
    "car": "car", "sedan": "Sedan", "vehicle": "car", "vehicle_other": "car",
    "truck": "truck", "bus": "bus", "bus or truck": "Bus or Truck",
    "pedestrian": "pedestrian", "person": "pedestrian",
    "cyclist": "cyclist", "bicycle": "Bicycle", "motorcycle": "Motorcycle",
}


def _lookup_prior(class_name: str):
    cname = (class_name or "").strip()
    return (CLASS_SIZE_PRIORS.get(cname)
            or CLASS_SIZE_PRIORS.get(_CLASS_SYN.get(cname.lower(), cname))
            or CLASS_SIZE_PRIORS.get(cname.lower()))


def _largest_dbscan_cluster(pts: np.ndarray, eps: float = 0.6,
                            min_samples: int = 3) -> np.ndarray:
    """Largest DBSCAN cluster of (N, >=3) points.  Falls back to all-pts."""
    if len(pts) < min_samples:
        return pts
    try:
        from sklearn.cluster import DBSCAN
        labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(pts[:, :3])
        if labels.max() < 0:
            return pts
        unique, counts = np.unique(labels[labels >= 0], return_counts=True)
        best = unique[counts.argmax()]
        return pts[labels == best]
    except Exception:
        logger.exception("DBSCAN failed; using all pts")
        return pts


def fit_box_v3(
    image_rgb: np.ndarray | None,
    bbox: tuple[float, float, float, float],
    class_name: str,
    calib: "CalibrationBundle",
    camera: str,
    lidar_points: np.ndarray,
    *,
    quality: Literal["fast", "full", "auto", "none"] = "auto",
    segmentor: "Segmentor | None" = None,
    depth_estimator: "DepthEstimator | None" = None,
    ground_plane: np.ndarray | None = None,
    score: float = 1.0,
) -> tuple[Label3D | None, dict]:
    """Fit a 3D box from a 2D bbox.

    Returns ``(Label3D, info)`` where ``info`` is a small dict with
    diagnostic fields (used for logging / display):

        info = {
            "backend":       "sam2" | "mobile_sam" | "stub" | "none",
            "mask_pixels":   int,        # 0 if no SAM mask
            "n_lidar":       int,        # real LiDAR points used
            "n_virtual":     int,        # DA2 virtual pts added
            "yaw_method":    "lshape" | "fallback",
        }
    """
    info = {"backend": "none", "mask_pixels": 0, "n_lidar": 0,
            "n_virtual": 0, "yaw_method": "fallback"}

    if lidar_points is None or len(lidar_points) < _MIN_PTS:
        return None, info

    h_img = image_rgb.shape[0] if image_rgb is not None else 720
    w_img = image_rgb.shape[1] if image_rgb is not None else 1280
    x1, y1, x2, y2 = [float(v) for v in bbox]
    x1 = max(0.0, x1); y1 = max(0.0, y1)
    x2 = min(float(w_img - 1), x2); y2 = min(float(h_img - 1), y2)
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None, info

    # ── 1. SAM mask (optional) ─────────────────────────────────────────
    mask: np.ndarray | None = None
    if quality != "none" and segmentor is not None and image_rgb is not None:
        try:
            if getattr(segmentor, "enabled", False):
                mask = segmentor.segment(image_rgb, bbox=(x1, y1, x2, y2))
                if mask is not None:
                    info["backend"] = getattr(segmentor, "backend", "sam") or "sam"
                    info["mask_pixels"] = int(mask.sum())
        except Exception:
            logger.exception("SAM segment failed; falling back to bbox")
            mask = None

    # ── 2. Project LiDAR -> pixels, filter by mask/bbox ─────────────────
    intr = calib.intrinsics.get(camera)
    if intr is None:
        return None, info
    T = calib.extrinsics.get(camera, np.eye(4))
    pts_h = np.hstack([lidar_points[:, :3], np.ones((len(lidar_points), 1))])
    cam_z_all = (T @ pts_h.T)[2]
    try:
        pixels = calib.project_3d_to_image(lidar_points[:, :3], camera)
    except Exception:
        logger.exception("project_3d_to_image failed")
        return None, info

    in_box = (
        (cam_z_all > 0.1)
        & (pixels[:, 0] >= x1) & (pixels[:, 0] <= x2)
        & (pixels[:, 1] >= y1) & (pixels[:, 1] <= y2)
    )
    if mask is not None and mask.shape[:2] == (h_img, w_img):
        u_int = np.clip(pixels[:, 0].astype(np.int32), 0, w_img - 1)
        v_int = np.clip(pixels[:, 1].astype(np.int32), 0, h_img - 1)
        in_mask = mask[v_int, u_int]
        in_box_mask = in_box & in_mask
        if in_box_mask.sum() >= _MIN_PTS:
            in_box = in_box_mask  # use tighter mask filter
        # else: SAM mask was too tight; fall back to bbox

    pts_lidar = lidar_points[in_box, :3].astype(np.float64)
    info["n_lidar"] = int(len(pts_lidar))

    # ── 3. Remove near-ground points ────────────────────────────────────
    if ground_plane is not None and len(pts_lidar) > 0:
        a, b, c_gp, d_gp = ground_plane
        n_len = float(np.sqrt(a * a + b * b + c_gp * c_gp) + 1e-9)
        h_above = (a * pts_lidar[:, 0] + b * pts_lidar[:, 1]
                   + c_gp * pts_lidar[:, 2] + d_gp) / n_len
        non_ground = h_above > 0.25
        if non_ground.sum() >= _MIN_PTS:
            pts_lidar = pts_lidar[non_ground]

    # ── 3b. Bbox-centre anchor + radius filter ──────────────────────────
    # Critical: the user's bbox CENTRE pixel ray ∩ ground plane defines the
    # intended target location.  Filtering pts to those within a class-prior
    # radius of that anchor eliminates background bleed (walls, neighbour
    # vehicles) BEFORE DBSCAN — otherwise DBSCAN's "largest cluster" can lock
    # onto background and the resulting box drifts off the user's selection.
    anchor_xy: np.ndarray | None = None
    cam_world_xy: np.ndarray | None = None
    try:
        R_mat = T[:3, :3]
        t_vec = T[:3, 3]
        cam_orig = -(R_mat.T @ t_vec)
        cam_world_xy = cam_orig[:2].copy()
        cx_pix = (x1 + x2) / 2.0
        cy_pix = (y1 + y2) / 2.0
        d_cam = np.array([(cx_pix - intr.cx) / intr.fx,
                          (cy_pix - intr.cy) / intr.fy,
                          1.0])
        d_ldr = R_mat.T @ d_cam
        dn = float(np.linalg.norm(d_ldr))
        if dn > 1e-8 and ground_plane is not None:
            d_ldr = d_ldr / dn
            a, b, c_gp, d_gp = ground_plane
            denom = a * d_ldr[0] + b * d_ldr[1] + c_gp * d_ldr[2]
            if abs(denom) > 1e-6:
                t_param = -(a * cam_orig[0] + b * cam_orig[1]
                            + c_gp * cam_orig[2] + d_gp) / denom
                if t_param > 0.5:
                    anchor_xy = (cam_orig + t_param * d_ldr)[:2]
    except Exception:
        logger.exception("anchor computation failed")

    prior_for_radius = _lookup_prior(class_name)
    if prior_for_radius is not None:
        anchor_radius = float(max(prior_for_radius.mean[0],
                                  prior_for_radius.mean[1])) * 1.2
    else:
        anchor_radius = 3.0

    if anchor_xy is not None and len(pts_lidar) >= _MIN_PTS:
        d2 = np.hypot(pts_lidar[:, 0] - anchor_xy[0],
                      pts_lidar[:, 1] - anchor_xy[1])
        near = d2 <= anchor_radius
        if near.sum() >= _MIN_PTS:
            pts_lidar = pts_lidar[near]
        else:
            wide = d2 <= anchor_radius * 1.6
            if wide.sum() >= _MIN_PTS:
                pts_lidar = pts_lidar[wide]
        info["n_lidar"] = int(len(pts_lidar))

    # ── 4. DepthAnything virtual points (optional) ──────────────────────
    pts_virtual: np.ndarray | None = None
    if (quality != "none" and depth_estimator is not None
            and image_rgb is not None):
        try:
            from src.fusion.depth_anything_metric import generate_virtual_pts
            pts_virtual = generate_virtual_pts(
                image_rgb, (x1, y1, x2, y2), depth_estimator,
                calib, camera, lidar_points, mask=mask, stride=4,
            )
            if pts_virtual is not None:
                info["n_virtual"] = int(len(pts_virtual))
        except Exception:
            logger.exception("DA virtual points failed")
            pts_virtual = None

    # Combine: LiDAR (high weight) + DA virtual (lower weight, downsample)
    if pts_virtual is not None and len(pts_virtual) > 0:
        # Down-weight virtual pts by under-sampling 1/3 of them so they
        # don't drown out real LiDAR in DBSCAN/L-shape.
        if len(pts_virtual) > max(50, len(pts_lidar) * 3):
            idx = np.random.default_rng(0).choice(
                len(pts_virtual),
                max(50, len(pts_lidar) * 3),
                replace=False,
            )
            pts_virtual = pts_virtual[idx]
        # Also remove near-ground virtual pts
        if ground_plane is not None and len(pts_virtual) > 0:
            a, b, c_gp, d_gp = ground_plane
            n_len = float(np.sqrt(a * a + b * b + c_gp * c_gp) + 1e-9)
            h_above_v = (a * pts_virtual[:, 0] + b * pts_virtual[:, 1]
                         + c_gp * pts_virtual[:, 2] + d_gp) / n_len
            pts_virtual = pts_virtual[h_above_v > 0.15]
        # Also restrict virtual pts to anchor radius
        if anchor_xy is not None and len(pts_virtual) > 0:
            d2v = np.hypot(pts_virtual[:, 0] - anchor_xy[0],
                           pts_virtual[:, 1] - anchor_xy[1])
            pts_virtual = pts_virtual[d2v <= anchor_radius * 1.2]
        pts_combined = np.vstack([pts_lidar, pts_virtual])
    else:
        pts_combined = pts_lidar

    if len(pts_combined) < _MIN_PTS:
        return None, info

    # ── 5. DBSCAN, keep largest cluster ─────────────────────────────────
    pts_cluster = _largest_dbscan_cluster(pts_combined, eps=0.6, min_samples=3)
    if len(pts_cluster) < _MIN_PTS:
        pts_cluster = pts_combined

    # ── 6. L-shape BEV fit ──────────────────────────────────────────────
    yaw_hint = None
    try:
        from src.fusion.geometry import compute_pca_yaw
        yaw_hint = compute_pca_yaw(pts_cluster[:, :2])
    except Exception:
        yaw_hint = None
    yaw, center_xy, L_obs, W_obs = fit_lshape(
        pts_cluster[:, :2], yaw_hint=yaw_hint, hint_window_deg=45.0,
    )
    info["yaw_method"] = "lshape"

    # ── 6b. Anchor centre validation ────────────────────────────────────
    # If L-shape centre drifted >0.6× anchor_radius from the user's clicked
    # anchor (because cluster was lopsided or DBSCAN bridged), pull it back
    # toward the anchor.  We move along the camera view direction so that
    # the BBOX projection alignment is preserved.
    if anchor_xy is not None:
        drift = np.hypot(center_xy[0] - anchor_xy[0],
                         center_xy[1] - anchor_xy[1])
        if drift > anchor_radius * 0.6:
            logger.info("L-shape centre drifted %.2fm from anchor; pulling back",
                        float(drift))
            center_xy = np.array(anchor_xy, dtype=np.float64)

    # ── 6c. Yaw view-direction tie-break ────────────────────────────────
    # Most vehicles are NOT facing the camera; their long axis is roughly
    # PERPENDICULAR to the camera-to-object view direction.  When the visible
    # cluster is small (single side surface), L-shape often picks an axis
    # parallel to the view direction → wrong yaw by 90°.
    # Fix: compute angle between yaw axis and view direction; if too aligned
    # (<25°) AND cluster is thin, rotate yaw by 90°.
    if cam_world_xy is not None:
        view_xy = np.array(center_xy) - cam_world_xy
        v_len = float(np.linalg.norm(view_xy))
        if v_len > 1e-6:
            view_unit = view_xy / v_len
            yaw_unit = np.array([np.cos(yaw), np.sin(yaw)])
            # Angle between yaw axis and view direction (mod 180°)
            cos_a = abs(float(np.dot(yaw_unit, view_unit)))
            cos_a = min(1.0, max(-1.0, cos_a))
            angle_to_view_deg = float(np.degrees(np.arccos(cos_a)))
            # If yaw nearly parallel to view AND the L-shape returned a
            # thin "length" (≤ 0.5 of prior_length), the principal axis is
            # almost certainly the visible WIDTH face → rotate yaw by 90°.
            prior = _lookup_prior(class_name)
            if prior is not None and angle_to_view_deg < 25.0:
                if L_obs <= float(prior.mean[0]) * 0.5:
                    yaw = float(yaw + np.pi / 2.0)
                    L_obs, W_obs = W_obs, L_obs
                    info["yaw_method"] = "lshape+view_flip"

    # ── 7. Class prior expansion (away from camera) ─────────────────────
    prior = _lookup_prior(class_name)
    if prior is not None:
        cam_world = (np.linalg.inv(T) @ np.array([0.0, 0.0, 0.0, 1.0]))[:3]
        center_xy, L_dim, W_dim = expand_to_prior(
            yaw, center_xy, L_obs, W_obs,
            float(prior.mean[0]), float(prior.mean[1]),
            cam_xy=cam_world[:2],
        )
        H_dim = float(prior.mean[2])
    else:
        L_dim, W_dim = max(L_obs, 0.3), max(W_obs, 0.3)
        # Height from cluster percentile
        z_lo = float(np.percentile(pts_cluster[:, 2], 5))
        z_hi = float(np.percentile(pts_cluster[:, 2], 95))
        H_dim = max(z_hi - z_lo, 0.3)
        L_dim = min(L_dim, 15.0); W_dim = min(W_dim, 15.0); H_dim = min(H_dim, 6.0)

    # ── 8. Z snap to ground ─────────────────────────────────────────────
    if ground_plane is not None:
        gz = estimate_ground_z_at(center_xy, ground_plane)
        cz = float(gz) + H_dim / 2.0
    else:
        cz = float(pts_cluster[:, 2].mean())

    return Label3D(
        class_name=class_name,
        center=np.array([center_xy[0], center_xy[1], cz], dtype=np.float64),
        dimensions=np.array([L_dim, W_dim, H_dim], dtype=np.float64),
        rotation=float(yaw),
        score=float(score),
        source=f"v3:{info['backend']}",
    ), info
