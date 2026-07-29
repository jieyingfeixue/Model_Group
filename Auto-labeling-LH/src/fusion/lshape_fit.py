"""L-shape rectangle fitting on a BEV (bird's-eye-view) point cluster.

Implements the search-based L-shape fitter from Zhang et al., 2017
"Efficient L-Shape Fitting for Vehicle Detection Using Laser Scanners".
Robust against partial-surface LiDAR returns where PCA fails - for a car
seen only from one side, PCA's principal axis is *along the side*, so the
yaw is correct only by accident.  L-shape instead searches a yaw angle theta
that maximises a "closeness" criterion of the rotated bounding box: the
sum of distances from every point to its nearest box edge.

Public API
----------
    yaw, center_xy, length, width = fit_lshape(pts_xy)
    new_center, new_L, new_W = expand_to_prior(yaw, center, L, W,
                                               prior_L, prior_W, cam_xy)

Pure NumPy (no sklearn / no scipy required for the core).
"""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np


_ANGLE_STEP = math.radians(1.0)


def _closeness_score(c1: np.ndarray, c2: np.ndarray) -> float:
    c1_min, c1_max = float(c1.min()), float(c1.max())
    c2_min, c2_max = float(c2.min()), float(c2.max())
    d1 = np.minimum(c1 - c1_min, c1_max - c1)
    d2 = np.minimum(c2 - c2_min, c2_max - c2)
    d  = np.minimum(d1, d2)
    return float(np.sum(1.0 / (d + 1e-3)))


def fit_lshape(
    pts_xy: np.ndarray,
    yaw_hint: float | None = None,
    hint_window_deg: float = 60.0,
) -> Tuple[float, np.ndarray, float, float]:
    """Fit an oriented BEV rectangle to *pts_xy* (Nx2).

    Returns yaw (rad in [-pi/2, pi/2]), center (2,), length, width.
    length is always >= width and yaw points along the longer side.
    """
    pts = np.asarray(pts_xy, dtype=np.float64)
    if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 3:
        if pts.size == 0:
            return 0.0, np.zeros(2), 0.3, 0.3
        c = pts.mean(axis=0)
        mn, mx = pts.min(axis=0), pts.max(axis=0)
        L = max(float(mx[0] - mn[0]), 0.3)
        W = max(float(mx[1] - mn[1]), 0.3)
        if W > L:
            L, W = W, L
            return math.pi / 2.0, c, L, W
        return 0.0, c, L, W

    if yaw_hint is None:
        angles = np.arange(-math.pi / 2.0, math.pi / 2.0, _ANGLE_STEP)
    else:
        hw = math.radians(hint_window_deg)
        angles = np.arange(yaw_hint - hw, yaw_hint + hw, _ANGLE_STEP)

    pts_c = pts - pts.mean(axis=0)

    best_score = -np.inf
    best_yaw = 0.0
    best_c1 = best_c2 = None  # type: ignore
    for theta in angles:
        c, s = math.cos(theta), math.sin(theta)
        c1 =  c * pts_c[:, 0] + s * pts_c[:, 1]
        c2 = -s * pts_c[:, 0] + c * pts_c[:, 1]
        score = _closeness_score(c1, c2)
        if score > best_score:
            best_score = score
            best_yaw = float(theta)
            best_c1, best_c2 = c1, c2

    c1_min, c1_max = float(best_c1.min()), float(best_c1.max())  # type: ignore
    c2_min, c2_max = float(best_c2.min()), float(best_c2.max())  # type: ignore
    L = max(c1_max - c1_min, 0.3)
    W = max(c2_max - c2_min, 0.3)

    cx_local = (c1_min + c1_max) / 2.0
    cy_local = (c2_min + c2_max) / 2.0

    c, s = math.cos(best_yaw), math.sin(best_yaw)
    cx_world =  c * cx_local - s * cy_local + pts.mean(axis=0)[0]
    cy_world =  s * cx_local + c * cy_local + pts.mean(axis=0)[1]

    if W > L:
        L, W = W, L
        best_yaw += math.pi / 2.0
        if best_yaw > math.pi / 2.0:
            best_yaw -= math.pi
        elif best_yaw < -math.pi / 2.0:
            best_yaw += math.pi

    return best_yaw, np.array([cx_world, cy_world]), float(L), float(W)


def expand_to_prior(
    yaw: float,
    center: np.ndarray,
    L: float,
    W: float,
    prior_length: float,
    prior_width: float,
    cam_xy: np.ndarray,
    length_tol: tuple[float, float] = (0.7, 1.3),
    width_tol: tuple[float, float] = (0.7, 1.3),
) -> Tuple[np.ndarray, float, float]:
    """Clamp L/W to ``prior * tol`` and shift centre AWAY from the camera.

    LiDAR sees only the camera-facing surface.  The L-shape AABB is the
    bound of that surface, so when we expand the box to the prior size
    we should grow only on the FAR side, keeping the visible surface on
    the near face.

    Parameters
    ----------
    yaw, center, L, W : output of fit_lshape on the visible cluster
    prior_length, prior_width : class prior (mean) in metres
    cam_xy : (2,) camera optical-centre BEV position
    """
    L_clamped = float(np.clip(L, prior_length * length_tol[0], prior_length * length_tol[1]))
    W_clamped = float(np.clip(W, prior_width  * width_tol[0],  prior_width  * width_tol[1]))

    c, s = math.cos(yaw), math.sin(yaw)
    cam_to_box = center - cam_xy
    cam_to_box_local = np.array([ c * cam_to_box[0] + s * cam_to_box[1],
                                 -s * cam_to_box[0] + c * cam_to_box[1]])
    grow_L = (L_clamped - L) / 2.0
    grow_W = (W_clamped - W) / 2.0
    sign_L =  1.0 if cam_to_box_local[0] >= 0 else -1.0
    sign_W =  1.0 if cam_to_box_local[1] >= 0 else -1.0
    shift_local = np.array([sign_L * grow_L, sign_W * grow_W])
    shift_world = np.array([ c * shift_local[0] - s * shift_local[1],
                             s * shift_local[0] + c * shift_local[1]])

    return center + shift_world, L_clamped, W_clamped
