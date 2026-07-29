"""Geometry utilities for point cloud processing."""

from __future__ import annotations

import numpy as np

from src.core.types import Label3D


def estimate_ground_plane(points: np.ndarray, height_percentile: float = 10.0) -> np.ndarray:
    """Estimate ground plane as [a, b, c, d] with RANSAC-like approach.

    Returns plane coefficients such that ax + by + cz + d = 0.
    Falls back to z = z_min if too few points.
    """
    if points is None or len(points) < 10:
        return np.array([0.0, 0.0, 1.0, 0.0])

    z_vals = points[:, 2]
    threshold = np.percentile(z_vals, height_percentile)
    ground_mask = z_vals < threshold
    ground_pts = points[ground_mask]

    if len(ground_pts) < 3:
        return np.array([0.0, 0.0, 1.0, -float(np.median(z_vals))])

    # Simple RANSAC for plane fitting
    best_plane = np.array([0.0, 0.0, 1.0, -float(np.median(z_vals))])
    best_inliers = 0
    rng = np.random.RandomState(42)

    for _ in range(100):
        idx = rng.choice(len(ground_pts), 3, replace=False)
        p0, p1, p2 = ground_pts[idx[0], :3], ground_pts[idx[1], :3], ground_pts[idx[2], :3]
        normal = np.cross(p1 - p0, p2 - p0)
        norm_len = np.linalg.norm(normal)
        if norm_len < 1e-8:
            continue
        normal /= norm_len
        d = -np.dot(normal, p0)
        dists = np.abs(ground_pts[:, :3] @ normal + d)
        inliers = np.sum(dists < 0.15)
        if inliers > best_inliers:
            best_inliers = inliers
            best_plane = np.array([normal[0], normal[1], normal[2], d])

    return best_plane


def estimate_ground_z_at(xy: np.ndarray, plane: np.ndarray) -> float:
    """Estimate ground z at (x, y) given plane [a, b, c, d]."""
    a, b, c, d = plane
    if abs(c) < 1e-8:
        return 0.0
    return -(a * xy[0] + b * xy[1] + d) / c


def count_points_in_box(points: np.ndarray, box: Label3D) -> int:
    """Count the number of points inside a 3D box."""
    if points is None or len(points) == 0:
        return 0
    pts = extract_points_in_box(points, box)
    return len(pts)


def extract_points_in_box(
    points: np.ndarray, box: Label3D, expand: float = 1.0
) -> np.ndarray:
    """Extract points within the oriented 3D bounding box."""
    if points is None or len(points) == 0:
        return np.empty((0, points.shape[1] if points is not None else 4))

    # Translate to box center
    pts_centered = points[:, :3] - box.center

    # Rotate to box frame
    c, s = np.cos(-box.rotation), np.sin(-box.rotation)
    rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
    pts_local = pts_centered @ rot.T

    half_dims = box.dimensions * expand / 2.0
    mask = (
        (np.abs(pts_local[:, 0]) <= half_dims[0])
        & (np.abs(pts_local[:, 1]) <= half_dims[1])
        & (np.abs(pts_local[:, 2]) <= half_dims[2])
    )
    return points[mask]


def compute_bev_iou(a: Label3D, b: Label3D) -> float:
    """Approximate BEV IoU using axis-aligned boxes after rotation."""
    # Simplified: use corners projected to XY
    try:
        from shapely.geometry import Polygon
        ca = a.corners()[:4, :2]
        cb = b.corners()[:4, :2]
        pa = Polygon(ca)
        pb = Polygon(cb)
        if not pa.is_valid or not pb.is_valid:
            return 0.0
        inter = pa.intersection(pb).area
        union = pa.area + pb.area - inter
        return inter / max(union, 1e-8)
    except ImportError:
        # Fallback: axis-aligned BEV
        return _aa_bev_iou(a, b)


def _aa_bev_iou(a: Label3D, b: Label3D) -> float:
    """Axis-aligned BEV IoU fallback."""
    al, aw = a.dimensions[0] / 2, a.dimensions[1] / 2
    bl, bw = b.dimensions[0] / 2, b.dimensions[1] / 2

    x_overlap = max(0, min(a.center[0] + al, b.center[0] + bl) - max(a.center[0] - al, b.center[0] - bl))
    y_overlap = max(0, min(a.center[1] + aw, b.center[1] + bw) - max(a.center[1] - aw, b.center[1] - bw))
    inter = x_overlap * y_overlap
    area_a = a.dimensions[0] * a.dimensions[1]
    area_b = b.dimensions[0] * b.dimensions[1]
    return inter / max(area_a + area_b - inter, 1e-8)


def compute_pca_yaw(pts_2d: np.ndarray) -> float:
    """Compute principal axis direction from 2D points → yaw in radians."""
    if len(pts_2d) < 3:
        return 0.0
    centered = pts_2d - pts_2d.mean(axis=0)
    cov = np.cov(centered.T)
    eigvals, eigvecs = np.linalg.eigh(cov)
    main_axis = eigvecs[:, np.argmax(eigvals)]
    return float(np.arctan2(main_axis[1], main_axis[0]))


def angle_diff(a: float, b: float) -> float:
    """Absolute angular difference in [0, π]."""
    d = (a - b) % (2 * np.pi)
    if d > np.pi:
        d = 2 * np.pi - d
    return d
