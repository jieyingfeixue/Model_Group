"""Geometric construction of a 3D box from a 2D bbox + ground plane.

Goal: the near (camera-facing) face of the resulting 3D box, when projected
back to the image, lies on the user's 2D bbox.  This ignores the LiDAR
content inside the bbox — width / height are derived from bbox geometry,
length comes from class prior.

This guarantees alignment between the user's 2D selection and the visible
face of the 3D box, which is what the user actually wants when manually
annotating.
"""
from __future__ import annotations

import logging
import numpy as np

from src.core.constants import CLASS_SIZE_PRIORS
from src.core.types import CalibrationBundle, Label3D
from src.fusion.geometry import estimate_ground_z_at

logger = logging.getLogger(__name__)

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


def _pixel_ray_ldr(u: float, v: float, intr, R_mat: np.ndarray,
                   cam_orig: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return (origin, direction) of the camera ray for pixel (u,v) in LiDAR frame."""
    d_cam = np.array([(u - intr.cx) / intr.fx,
                      (v - intr.cy) / intr.fy,
                      1.0])
    d_ldr = R_mat.T @ d_cam
    n = np.linalg.norm(d_ldr)
    if n < 1e-9:
        d_ldr = np.array([1.0, 0.0, 0.0])
    else:
        d_ldr = d_ldr / n
    return cam_orig, d_ldr


def _ray_plane_intersect(o: np.ndarray, d: np.ndarray,
                         plane_pt: np.ndarray, plane_n: np.ndarray
                         ) -> np.ndarray | None:
    """Intersection of ray o+t*d (t>0) with plane (point + normal)."""
    denom = float(np.dot(d, plane_n))
    if abs(denom) < 1e-9:
        return None
    t = float(np.dot(plane_pt - o, plane_n)) / denom
    if t <= 0.05:
        return None
    return o + t * d


def fit_box_from_bbox_geometric(
    bbox: tuple[float, float, float, float],
    class_name: str,
    calib: CalibrationBundle,
    camera: str,
    ground_plane: np.ndarray | None,
    score: float = 1.0,
) -> Label3D | None:
    """Construct a 3D box whose near face projects EXACTLY onto the 2D bbox.

    Pinhole back-projection at constant cam-frame depth z*:
        1. z* = cam-frame depth where bbox-bottom-centre ray hits ground.
        2. Back-project all 4 bbox corners at depth z*  →  4 cam-frame points
           sharing the same z, so they project back to the EXACT bbox corners.
        3. Transform 4 corners to LiDAR frame  →  these are the near-face
           corners of the 3D box.
        4. length_axis = cam +z (in LiDAR) projected to ground; width_axis =
           up × length_axis; H, W from corner separations.
        5. Length from class prior; centre = near-face centre + L/2*length_axis.
    """
    intr = calib.intrinsics.get(camera)
    T = calib.extrinsics.get(camera)
    if intr is None or T is None or ground_plane is None:
        return None

    R_mat = T[:3, :3]
    T_inv = np.linalg.inv(T)

    x1, y1, x2, y2 = [float(v) for v in bbox]
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None

    a, b, c_gp, d_gp = ground_plane
    plane_n_ldr = np.array([a, b, c_gp])
    n_norm = float(np.linalg.norm(plane_n_ldr))
    if n_norm < 1e-9:
        return None
    plane_n_ldr_unit = plane_n_ldr / n_norm

    # Ground plane in CAM frame
    if abs(c_gp) > 1e-6:
        ground_pt_ldr = np.array([0.0, 0.0, -d_gp / c_gp])
    elif abs(b) > 1e-6:
        ground_pt_ldr = np.array([0.0, -d_gp / b, 0.0])
    else:
        ground_pt_ldr = np.array([-d_gp / a, 0.0, 0.0])
    ground_pt_cam = (T @ np.append(ground_pt_ldr, 1.0))[:3]
    plane_n_cam = R_mat @ plane_n_ldr_unit

    # ── 1. Find depth z* via bbox-bottom-centre ray ∩ ground (CAM frame) ──
    cx_pix = (x1 + x2) / 2.0

    def _ray_dir_cam(u: float, v: float) -> np.ndarray:
        return np.array([(u - intr.cx) / intr.fx,
                         (v - intr.cy) / intr.fy,
                         1.0])

    def _hit_ground_z(u: float, v: float) -> float | None:
        d_cam = _ray_dir_cam(u, v)
        denom = float(np.dot(d_cam, plane_n_cam))
        if abs(denom) < 1e-9:
            return None
        t = float(np.dot(ground_pt_cam, plane_n_cam)) / denom
        if t <= 0.05:
            return None
        return float(t * d_cam[2])  # cam-frame z at hit

    z_star = _hit_ground_z(cx_pix, y2)
    if z_star is None:
        z_star = _hit_ground_z(cx_pix, (y1 + y2) / 2.0)
    if z_star is None or z_star < 0.5:
        return None

    # ── 2. Back-project 4 bbox corners at constant cam-frame depth z* ────
    def _backproj(u: float, v: float) -> np.ndarray:
        x_c = (u - intr.cx) * z_star / intr.fx
        y_c = (v - intr.cy) * z_star / intr.fy
        return np.array([x_c, y_c, z_star])

    ul_cam = _backproj(x1, y1)   # upper-left
    ur_cam = _backproj(x2, y1)   # upper-right
    ll_cam = _backproj(x1, y2)   # lower-left
    lr_cam = _backproj(x2, y2)   # lower-right

    # ── 3. To LiDAR frame ─────────────────────────────────────────────────
    def _to_ldr(p_cam: np.ndarray) -> np.ndarray:
        return (T_inv @ np.append(p_cam, 1.0))[:3]

    ul = _to_ldr(ul_cam)
    ur = _to_ldr(ur_cam)
    ll = _to_ldr(ll_cam)
    lr = _to_ldr(lr_cam)

    # ── 4. Box axes ──────────────────────────────────────────────────────
    up = plane_n_ldr_unit.copy()
    if up[2] < 0:
        up = -up

    # length_axis = cam +z direction (in LiDAR), projected on ground plane
    cam_z_ldr = R_mat.T @ np.array([0.0, 0.0, 1.0])
    length_axis = cam_z_ldr - float(np.dot(cam_z_ldr, up)) * up
    la_norm = float(np.linalg.norm(length_axis))
    if la_norm < 1e-6:
        return None
    length_axis = length_axis / la_norm

    width_axis = np.cross(up, length_axis)
    wa_norm = float(np.linalg.norm(width_axis))
    if wa_norm < 1e-6:
        return None
    width_axis = width_axis / wa_norm

    yaw = float(np.arctan2(length_axis[1], length_axis[0]))

    # ── 5. W and H from the 4 near-face corners ──────────────────────────
    W_top = float(abs(np.dot(ur - ul, width_axis)))
    W_bot = float(abs(np.dot(lr - ll, width_axis)))
    W = (W_top + W_bot) / 2.0
    H_lt = float(abs(np.dot(ll - ul, up)))
    H_rt = float(abs(np.dot(lr - ur, up)))
    H = (H_lt + H_rt) / 2.0

    W = float(np.clip(W, 0.2, 30.0))
    H = float(np.clip(H, 0.2, 30.0))

    # ── 6. Length from prior; centre from near-face geometric centre ─────
    prior = _lookup_prior(class_name)
    L = float(prior.mean[0]) if prior is not None else 4.0

    near_face_centre = (ul + ur + ll + lr) / 4.0
    centre_world = near_face_centre + (L / 2.0) * length_axis

    return Label3D(
        class_name=class_name,
        center=centre_world,
        dimensions=np.array([L, W, H], dtype=np.float64),
        rotation=yaw,
        score=float(score),
        source="bbox_geometric",
    )


# ════════════════════════════════════════════════════════════════════
#  SAM + Depth driven fit (uses LiDAR / DA inside the SAM mask)
# ════════════════════════════════════════════════════════════════════

def _project_lidar_with_camz(lidar_pts: np.ndarray,
                             calib: CalibrationBundle,
                             camera: str) -> tuple[np.ndarray, np.ndarray]:
    """Return (pixels Nx2 float, cam_z N float) for all LiDAR pts."""
    T = calib.extrinsics.get(camera, np.eye(4))
    pts_h = np.hstack([lidar_pts[:, :3], np.ones((len(lidar_pts), 1))])
    cam_z = (T @ pts_h.T)[2]
    pixels = calib.project_3d_to_image(lidar_pts[:, :3], camera)
    return pixels, np.asarray(cam_z, dtype=np.float64)


def _height_above_ground(pts_ldr: np.ndarray,
                         ground_plane: np.ndarray) -> np.ndarray:
    """Signed distance of each LiDAR point above the ground plane (m).

    Plane is (a,b,c,d) with a*x+b*y+c*z+d = 0; positive side = +n direction.
    """
    a, b, c, d = ground_plane
    n = np.array([a, b, c], dtype=np.float64)
    nn = float(np.linalg.norm(n))
    if nn < 1e-9:
        return np.zeros(len(pts_ldr))
    n_unit = n / nn
    if n_unit[2] < 0:           # ensure +n points up
        n_unit = -n_unit
        d = -d / nn
    else:
        d = d / nn
    return pts_ldr[:, :3] @ n_unit + d


def fit_box_from_bbox_with_sam_depth(
    bbox: tuple[float, float, float, float],
    class_name: str,
    calib: CalibrationBundle,
    camera: str,
    img_rgb: np.ndarray,
    lidar_pts: np.ndarray | None,
    ground_plane: np.ndarray | None,
    segmentor=None,
    depth_estimator=None,
    score: float = 1.0,
    ground_clearance: float = 0.15,
) -> Label3D | None:
    """SAM + depth driven 3D box fit.

    Pipeline
    --------
    1. SAM segments the object inside ``bbox``  →  binary mask.
       (Falls back to the bbox-as-mask if SAM unavailable.)
    2. Project LiDAR points; keep those whose pixel falls inside the mask
       AND that are **not** ground (height_above_ground > 0.15 m).
    3. From these object points get cam-frame depths z_obj.
       If too few LiDAR pts, optionally use ``depth_estimator`` (DA).
    4. Determine the depth band of the object:
         z_near = 5th  percentile  of z_obj
         z_far  = 95th percentile  of z_obj
       And which face the bbox slice corresponds to:
         z_med = median(z_obj);  bbox = NEAR face if (z_med-z_near) <= (z_far-z_med)
         else bbox = FAR face.
    5. Back-project the 4 bbox corners at the corresponding constant
       cam-frame depth z_face  →  4 cam-frame points sharing z=z_face,
       which project back to the EXACT bbox corners.  These are the 4
       corners of the chosen face (near or far) of the 3D box.
    6. Length = (z_far - z_near) clamped against the class prior.
    7. Box centre = face_centre  ±  (L/2) * length_axis.

    On failure (no SAM mask, no depth, etc.) returns None — caller should
    fall back to ``fit_box_from_bbox_geometric``.
    """
    intr = calib.intrinsics.get(camera)
    T = calib.extrinsics.get(camera)
    if intr is None or T is None or img_rgb is None:
        return None

    H_img, W_img = img_rgb.shape[:2]
    R_mat = T[:3, :3]
    T_inv = np.linalg.inv(T)

    x1, y1, x2, y2 = [float(v) for v in bbox]
    if x2 - x1 < 4 or y2 - y1 < 4:
        return None

    # ── 1. SAM mask ─────────────────────────────────────────────────────
    mask: np.ndarray | None = None
    if segmentor is not None:
        try:
            mask = segmentor.segment(img_rgb, bbox=(x1, y1, x2, y2))
        except Exception as exc:
            logger.warning("SAM segment failed: %s", exc)
            mask = None
    if mask is None:
        mask = np.zeros((H_img, W_img), dtype=bool)
        ix1, iy1 = max(0, int(x1)), max(0, int(y1))
        ix2, iy2 = min(W_img, int(x2)), min(H_img, int(y2))
        mask[iy1:iy2, ix1:ix2] = True
    mask = mask.astype(bool)
    if not mask.any():
        return None

    # ── 2. Project LiDAR; keep mask ∩ above-ground pts ──────────────────
    z_obj: np.ndarray | None = None
    if lidar_pts is not None and len(lidar_pts) > 0:
        pixels, cam_z = _project_lidar_with_camz(lidar_pts, calib, camera)
        u = np.round(pixels[:, 0]).astype(int)
        v = np.round(pixels[:, 1]).astype(int)
        in_img = (u >= 0) & (u < W_img) & (v >= 0) & (v < H_img) & (cam_z > 0.5)
        idx_in_img = np.where(in_img)[0]
        if len(idx_in_img) > 0:
            in_mask = mask[v[idx_in_img], u[idx_in_img]]
            obj_idx = idx_in_img[in_mask]
            if len(obj_idx) > 0 and ground_plane is not None:
                heights = _height_above_ground(lidar_pts[obj_idx, :3], ground_plane)
                obj_idx = obj_idx[heights > ground_clearance]
            if len(obj_idx) >= 3:
                z_obj = cam_z[obj_idx]

    # ── 3. DA fallback when LiDAR insufficient ──────────────────────────
    if z_obj is None and depth_estimator is not None:
        try:
            # Use monocular depth directly (DA/DA3 path), then calibrate to
            # metric depth with LiDAR-in-mask pairs when available.
            depth_map = depth_estimator.estimate(img_rgb)
            if depth_map is not None and depth_map.shape[:2] == (H_img, W_img):
                depth_metric = depth_map.astype(np.float64)

                if lidar_pts is not None and len(lidar_pts) > 0:
                    pixels2, cam_z2 = _project_lidar_with_camz(lidar_pts, calib, camera)
                    u2 = np.round(pixels2[:, 0]).astype(int)
                    v2 = np.round(pixels2[:, 1]).astype(int)
                    in_img2 = (u2 >= 0) & (u2 < W_img) & (v2 >= 0) & (v2 < H_img) & (cam_z2 > 0.5)
                    idx2 = np.where(in_img2)[0]
                    if len(idx2) > 0:
                        idx2 = idx2[mask[v2[idx2], u2[idx2]]]
                    if len(idx2) >= 5:
                        d_rel = depth_metric[v2[idx2], u2[idx2]]
                        z_gt = cam_z2[idx2]
                        ok = np.isfinite(d_rel) & np.isfinite(z_gt) & (d_rel > 1e-6)
                        d_rel = d_rel[ok]
                        z_gt = z_gt[ok]
                        if len(d_rel) >= 5:
                            A = np.column_stack([d_rel, np.ones_like(d_rel)])
                            sol, *_ = np.linalg.lstsq(A, z_gt, rcond=None)
                            resid = np.abs(A @ sol - z_gt)
                            keep = resid < (np.median(resid) * 3.0 + 0.5)
                            if keep.sum() >= 5:
                                sol, *_ = np.linalg.lstsq(A[keep], z_gt[keep], rcond=None)
                            a_fit, b_fit = float(sol[0]), float(sol[1])
                            if np.isfinite(a_fit) and np.isfinite(b_fit) and abs(a_fit) > 1e-6:
                                depth_metric = a_fit * depth_metric + b_fit

                ys, xs = np.where(mask)
                if len(ys) > 0:
                    d_samp = depth_metric[ys, xs]
                    d_samp = d_samp[np.isfinite(d_samp)]
                    d_samp = d_samp[(d_samp > 0.5) & (d_samp < 200.0)]
                    if len(d_samp) >= 10:
                        z_obj = d_samp
        except Exception as exc:
            logger.warning("DA depth estimate failed: %s", exc)

    if z_obj is None or len(z_obj) < 3:
        return None  # caller falls back to geometric-only

    # ── 4. Depth band — 2D bbox = NEAR face (same as geometric version) ──
    # User requirement: the 2D bbox is the projected silhouette of the 3D
    # box.  For a yaw-only cuboid with length along the camera ray, the
    # NEAR face (closest to camera) is the largest and projects exactly to
    # the 2D bbox.  The far face projects SMALLER and lies INSIDE the
    # bbox, and the 4 depth edges (parallel to length_axis) pass through
    # the 4 bbox corners — this is exactly what the user described.
    z_near = float(np.percentile(z_obj, 5))
    z_far  = float(np.percentile(z_obj, 95))
    L_obs = max(z_far - z_near, 0.2)

    # ── 5. Back-project 4 bbox corners at z_near (NEAR face) ──────────
    def _backproj(u: float, v: float, z: float) -> np.ndarray:
        return np.array([(u - intr.cx) * z / intr.fx,
                         (v - intr.cy) * z / intr.fy,
                         z])

    ul_cam = _backproj(x1, y1, z_near)
    ur_cam = _backproj(x2, y1, z_near)
    ll_cam = _backproj(x1, y2, z_near)
    lr_cam = _backproj(x2, y2, z_near)

    def _to_ldr(p_cam: np.ndarray) -> np.ndarray:
        return (T_inv @ np.append(p_cam, 1.0))[:3]

    ul = _to_ldr(ul_cam); ur = _to_ldr(ur_cam)
    ll = _to_ldr(ll_cam); lr = _to_ldr(lr_cam)

    # ── 6. Box axes — length along cam +z (same as geometric version) ─
    a, b, c_gp, d_gp = ground_plane if ground_plane is not None else (0.0, 0.0, 1.0, 0.0)
    plane_n = np.array([a, b, c_gp], dtype=np.float64)
    nn = float(np.linalg.norm(plane_n))
    up = plane_n / nn if nn > 1e-9 else np.array([0.0, 0.0, 1.0])
    if up[2] < 0:
        up = -up

    cam_z_ldr = R_mat.T @ np.array([0.0, 0.0, 1.0])
    length_axis = cam_z_ldr - float(np.dot(cam_z_ldr, up)) * up
    la_norm = float(np.linalg.norm(length_axis))
    if la_norm < 1e-6:
        return None
    length_axis = length_axis / la_norm

    width_axis = np.cross(up, length_axis)
    wa_norm = float(np.linalg.norm(width_axis))
    if wa_norm < 1e-6:
        return None
    width_axis = width_axis / wa_norm

    yaw = float(np.arctan2(length_axis[1], length_axis[0]))

    # ── 7. W and H from the 4 NEAR-face corners (= 2D bbox dimensions) ─
    W_top = float(abs(np.dot(ur - ul, width_axis)))
    W_bot = float(abs(np.dot(lr - ll, width_axis)))
    W = float(np.clip((W_top + W_bot) / 2.0, 0.2, 30.0))
    H_lt = float(abs(np.dot(ll - ul, up)))
    H_rt = float(abs(np.dot(lr - ur, up)))
    H = float(np.clip((H_lt + H_rt) / 2.0, 0.2, 30.0))

    # ── 8. Length from depth extent, tightly clamped by class prior ────
    prior = _lookup_prior(class_name)
    prior_L = float(prior.mean[0]) if prior is not None else 4.0
    if L_obs < 0.5 * prior_L:
        # Only one face visible — depth band too thin, trust the prior.
        L = prior_L
    else:
        L = float(np.clip(L_obs, 0.7 * prior_L, 1.3 * prior_L))

    # ── 9. Centre = near_face_centre + (L/2)*length_axis ───────────────
    near_face_centre = (ul + ur + ll + lr) / 4.0
    centre_world = near_face_centre + (L / 2.0) * length_axis

    logger.info(
        "fit_box_sam_depth: z_near=%.2f z_far=%.2f L_obs=%.2f L=%.2f W=%.2f H=%.2f n_pts=%d",
        z_near, z_far, L_obs, L, W, H, len(z_obj),
    )


    return Label3D(
        class_name=class_name,
        center=centre_world,
        dimensions=np.array([L, W, H], dtype=np.float64),
        rotation=yaw,
        score=float(score),
        source="bbox_sam_depth",
    )
