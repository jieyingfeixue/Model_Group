"""Project 2D detections to 3D using LiDAR frustum association."""

from __future__ import annotations

import logging

import numpy as np

from src.core.types import CalibrationBundle, Detection2D, Label3D
from src.core.constants import CLASS_SIZE_PRIORS
from src.fusion.geometry import compute_pca_yaw, estimate_ground_z_at

logger = logging.getLogger(__name__)

# Minimum LiDAR points inside frustum to attempt a fit
_MIN_PTS = 5
# z-range filter: keep points roughly at ego-height ± margin (metres above ground)
_Z_MIN = -3.0
_Z_MAX = 8.0


class ImageTo3DProjector:
    """Back-project a 2D camera detection to a 3D box via LiDAR frustum.

    Pipeline
    --------
    1. Project all LiDAR points into the camera image plane (using calib).
    2. Keep points whose projected pixel falls inside the 2D detection bbox.
    3. Optionally filter by height (remove ground / sky points).
    4. Fit a 3D oriented bounding box to those LiDAR points.
    5. Fall back to depth-map back-projection when no LiDAR is available.
    """

    def project(
        self,
        det: Detection2D,
        depth_map: np.ndarray,          # kept for API compatibility / fallback
        calib: CalibrationBundle,
        camera: str,
        lidar_points: np.ndarray | None = None,
        ground_plane: np.ndarray | None = None,
    ) -> Label3D | None:
        # ── Frustum path (preferred) ───────────────────────────────────────
        if lidar_points is not None and len(lidar_points) >= _MIN_PTS:
            box = self._frustum_project(det, calib, camera, lidar_points, ground_plane)
            if box is not None:
                return box
            logger.debug("Frustum fallback to depth-map for det %s (no pts in frustum)", det.class_name)

        # ── Depth-map fallback ─────────────────────────────────────────────
        return self._depth_project(det, depth_map, calib, camera)

    # ── frustum ──────────────────────────────────────────────────────────

    def _frustum_project(
        self,
        det: Detection2D,
        calib: CalibrationBundle,
        camera: str,
        lidar_points: np.ndarray,
        ground_plane: np.ndarray | None,
    ) -> Label3D | None:
        x1, y1, x2, y2 = det.bbox

        # 1. Project lidar pts → image pixels
        try:
            pixels = calib.project_3d_to_image(lidar_points[:, :3], camera)  # (N, 2)
        except Exception as exc:
            logger.warning("LiDAR→image projection failed: %s", exc)
            return None

        # 2. Only keep points in front of camera (positive z in camera frame)
        T = calib.extrinsics.get(camera, np.eye(4))
        pts_h = np.hstack([lidar_points[:, :3], np.ones((len(lidar_points), 1))])
        cam_z_all = (T @ pts_h.T)[2]   # z in camera frame

        in_frustum = (
            (cam_z_all > 0.1) &
            (pixels[:, 0] >= x1) & (pixels[:, 0] <= x2) &
            (pixels[:, 1] >= y1) & (pixels[:, 1] <= y2) &
            (lidar_points[:, 2] >= _Z_MIN) & (lidar_points[:, 2] <= _Z_MAX)
        )
        pts = lidar_points[in_frustum, :3]
        cam_z_frust = cam_z_all[in_frustum]

        if len(pts) < _MIN_PTS:
            # ── Ground-ray fallback ────────────────────────────────────────
            # Project the bbox-centre pixel as a camera ray and intersect with
            # the ground plane to get an approximate 3D position.  This works
            # even when the LiDAR has no points in the rear / side frustums.
            return self._ground_ray_project(det, calib, camera, ground_plane)

        # 2b. Remove near-ground points so road surface doesn't dominate the
        #     centroid.  We use a simple absolute Z threshold: in K-Radar the
        #     LiDAR is ~2 m above the road, so road returns sit at Z ≈ −2 m.
        #     Keeping Z > −1.3 m retains points ≥ ~0.7 m above ground.
        # Prefer ground-plane height if available (more accurate).
        if ground_plane is not None:
            a, b, c_gp, d_gp = ground_plane
            n_len = np.sqrt(a ** 2 + b ** 2 + c_gp ** 2) + 1e-9
            height_above_ground = (a * pts[:, 0] + b * pts[:, 1]
                                   + c_gp * pts[:, 2] + d_gp) / n_len
            non_ground = height_above_ground > 0.25
        else:
            non_ground = pts[:, 2] > -1.3   # absolute Z filter
        pts_ng = pts[non_ground]
        cam_z_ng = cam_z_frust[non_ground]
        if len(pts_ng) >= _MIN_PTS:
            pts = pts_ng
            cam_z_frust = cam_z_ng

        # 3. Foreground extraction via DEPTH HISTOGRAM.
        #    Inside the bbox, points typically span multiple depth layers:
        #      • the user's target object (closest dense layer)
        #      • background buildings / further vehicles (deeper layers)
        #    The first dense bin along camera-Z is almost always the target.
        #    This is far more robust than seed+flood-fill (which bridges to
        #    neighbours) or pure centroid (biased by background outliers).
        try:
            depths = cam_z_frust
            z_min, z_max = float(depths.min()), float(depths.max())
            # 1 m bins; cap at 80 m for far-range stability
            z_max = min(z_max, 80.0)
            n_bins = max(1, int(np.ceil(z_max - z_min)))
            hist, edges = np.histogram(depths, bins=n_bins,
                                       range=(z_min, z_max + 1e-3))
            # First bin meeting threshold = foreground depth peak.
            # Threshold = max(3 pts, 12 % of frustum pts).
            thr = max(3, int(0.12 * len(depths)))
            peak_bin = -1
            for i, c in enumerate(hist):
                if c >= thr:
                    peak_bin = i
                    break
            if peak_bin < 0:
                peak_bin = int(np.argmax(hist))
            peak_depth = (edges[peak_bin] + edges[peak_bin + 1]) / 2.0

            # Depth tolerance: half of class-prior length, min 2 m, max 6 m.
            prior_tmp = CLASS_SIZE_PRIORS.get(det.class_name)
            depth_tol = (max(2.0, float(prior_tmp.mean[0]) / 2.0)
                         if prior_tmp is not None else 3.0)
            depth_tol = min(depth_tol, 6.0)
            in_fg_depth = ((depths >= peak_depth - depth_tol)
                           & (depths <= peak_depth + depth_tol))
            if in_fg_depth.sum() >= _MIN_PTS:
                pts = pts[in_fg_depth]
                cam_z_frust = cam_z_frust[in_fg_depth]
        except Exception:
            logger.exception("depth-histogram filter failed; using all frustum pts")

        # 3b. Lateral filter: drop pts far from the median XY location.
        #     This kills sparse outliers (a single tree branch off to one side)
        #     while preserving the body of the target object.
        try:
            med_x = float(np.median(pts[:, 0]))
            med_y = float(np.median(pts[:, 1]))
            prior_tmp = CLASS_SIZE_PRIORS.get(det.class_name)
            if prior_tmp is not None:
                lat_tol = max(float(prior_tmp.mean[0]),
                              float(prior_tmp.mean[1])) * 1.2
            else:
                lat_tol = 4.0
            lat_tol = max(lat_tol, 1.5)
            lateral = ((np.abs(pts[:, 0] - med_x) <= lat_tol)
                       & (np.abs(pts[:, 1] - med_y) <= lat_tol))
            if lateral.sum() >= _MIN_PTS:
                pts = pts[lateral]
                cam_z_frust = cam_z_frust[lateral]
        except Exception:
            pass

        if len(pts) < _MIN_PTS:
            return self._ground_ray_project(det, calib, camera, ground_plane)

# REPLACE_MARKER_FOR_FIT_BLOCK
        centroid = pts.mean(axis=0)
        pca_yaw = compute_pca_yaw(pts[:, :2])

        # Class prior lookup with case/synonym fallback
        _SYN = {"car":"car","sedan":"Sedan","vehicle":"car","vehicle_other":"car",
                "truck":"truck","bus":"bus","bus or truck":"Bus or Truck",
                "pedestrian":"pedestrian","person":"pedestrian",
                "cyclist":"cyclist","bicycle":"Bicycle","motorcycle":"Motorcycle"}
        cname = (det.class_name or "").strip()
        prior = (CLASS_SIZE_PRIORS.get(cname)
                 or CLASS_SIZE_PRIORS.get(_SYN.get(cname.lower(), cname))
                 or CLASS_SIZE_PRIORS.get(cname.lower()))

        if prior is not None:
            dims = prior.mean.copy().astype(np.float64)
        else:
            cc0, ss0 = np.cos(-pca_yaw), np.sin(-pca_yaw)
            rot = np.array([[cc0, -ss0, 0], [ss0, cc0, 0], [0, 0, 1]])
            local = (pts - centroid) @ rot.T
            mins, maxs = local.min(axis=0), local.max(axis=0)
            dims = np.maximum(maxs - mins, 0.3)
            dims = np.minimum(dims, 15.0)

        # Surface-to-center compensation: LiDAR sees only the visible surface,
        # so the cluster centroid sits on it (NOT the box centre).  Push the
        # centre away from the camera along the camera-to-cluster view dir
        # by the appropriate half-extent.
        center = centroid.copy()
        try:
            T_inv = np.linalg.inv(T)
            cam_world = (T_inv @ np.array([0.0, 0.0, 0.0, 1.0]))[:3]
            view_dir = centroid[:2] - cam_world[:2]
            dist_xy = float(np.linalg.norm(view_dir))
            if dist_xy >= 1e-6 and prior is not None:
                view_dir = view_dir / dist_xy
                lateral_dir = np.array([-view_dir[1], view_dir[0]])
                rel = pts[:, :2] - centroid[:2]
                depth_proj = rel @ view_dir
                lateral_proj = rel @ lateral_dir
                depth_min = float(depth_proj.min())
                lateral_extent = float(lateral_proj.max() - lateral_proj.min())
                L = float(dims[0]); W = float(dims[1])
                # lateral spread bigger than (L+W)/2 -> seeing long side -> depth=W
                # otherwise seeing front/back -> depth=L
                depth_half = W / 2.0 if lateral_extent > (L + W) / 2.0 else L / 2.0
                offset_signed = depth_min + depth_half
                offset_signed = float(np.clip(offset_signed, -max(L, W), max(L, W)))
                center[:2] = centroid[:2] + offset_signed * view_dir
        except Exception:
            logger.exception("surface->centre compensation failed")

        if ground_plane is not None:
            gz = estimate_ground_z_at(center[:2], ground_plane)
            center[2] = gz + dims[2] / 2.0

        return Label3D(
            class_name=det.class_name,
            center=center,
            dimensions=dims,
            rotation=pca_yaw,
            score=det.score,
            source="frustum",
        )


    # ── depth-map fallback ────────────────────────────────────────────────

    def _depth_project(
        self,
        det: Detection2D,
        depth_map: np.ndarray,
        calib: CalibrationBundle,
        camera: str,
    ) -> Label3D | None:
        """Dense depth backproject + PCA fit (mirrors lyw's fit_box_from_points)."""
        intrinsics = calib.intrinsics.get(camera)
        if intrinsics is None:
            return None

        x1, y1, x2, y2 = [int(v) for v in det.bbox]
        h_img, w_img = depth_map.shape[:2]
        x1 = max(0, min(x1, w_img - 1))
        x2 = max(0, min(x2, w_img - 1))
        y1 = max(0, min(y1, h_img - 1))
        y2 = max(0, min(y2, h_img - 1))

        if x2 <= x1 or y2 <= y1:
            return None

        # ── Dense backproject ROI pixels to camera-space 3D points ────────
        stride = 2
        ys = np.arange(y1, y2, stride)
        xs = np.arange(x1, x2, stride)
        xv, yv = np.meshgrid(xs, ys)
        zv = depth_map[y1:y2:stride, x1:x2:stride].astype(np.float32)
        valid_mask = zv > 0.1
        if not np.any(valid_mask):
            return None

        z = zv[valid_mask]
        x_px = xv[valid_mask].astype(np.float32)
        y_px = yv[valid_mask].astype(np.float32)

        # Backproject to camera frame
        Xc = (x_px - intrinsics.cx) * z / intrinsics.fx
        Yc = (y_px - intrinsics.cy) * z / intrinsics.fy
        pts_cam = np.stack([Xc, Yc, z], axis=1)  # (N, 3)

        # ── Transform to world frame ───────────────────────────────────────
        T = calib.extrinsics.get(camera, np.eye(4))
        T_inv = np.linalg.inv(T)
        pts_h = np.hstack([pts_cam, np.ones((pts_cam.shape[0], 1), dtype=np.float32)])
        pts_world = (T_inv @ pts_h.T).T[:, :3]

        # Remove height outliers (keep within 1.5 IQR)
        z_w = pts_world[:, 2]
        q25, q75 = float(np.percentile(z_w, 25)), float(np.percentile(z_w, 75))
        iqr = max(q75 - q25, 0.2)
        height_mask = (z_w >= q25 - 1.5 * iqr) & (z_w <= q75 + 1.5 * iqr)
        pts_world = pts_world[height_mask]

        if pts_world.shape[0] < _MIN_PTS:
            # Fall back to single-point estimate
            median_z = float(np.median(z))
            cx_px = (x1 + x2) / 2.0
            cy_px = (y1 + y2) / 2.0
            Xc0 = (cx_px - intrinsics.cx) * median_z / intrinsics.fx
            Yc0 = (cy_px - intrinsics.cy) * median_z / intrinsics.fy
            cam_pt = np.array([Xc0, Yc0, median_z, 1.0])
            world_pt = (T_inv @ cam_pt)[:3]
            prior = CLASS_SIZE_PRIORS.get(det.class_name)
            dims = prior.mean.copy() if prior is not None else np.array([4.0, 1.8, 1.5])
            return Label3D(
                class_name=det.class_name, center=world_pt,
                dimensions=dims, score=det.score, source="auto",
            )

        # ── PCA fit in BEV (XY plane) ────────────────────────────────────
        centroid = pts_world.mean(axis=0)
        pca_yaw = compute_pca_yaw(pts_world[:, :2])
        c, s = np.cos(-pca_yaw), np.sin(-pca_yaw)
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        local = (pts_world - centroid) @ rot.T
        mins, maxs = local.min(axis=0), local.max(axis=0)
        dims_raw = np.maximum(maxs - mins, 0.3)

        # Blend observed dims with class prior
        prior = CLASS_SIZE_PRIORS.get(det.class_name)
        if prior is not None:
            n = pts_world.shape[0]
            alpha = float(np.clip(n / 60.0, 0.2, 0.8))
            dims = alpha * dims_raw + (1.0 - alpha) * prior.mean
            dims = np.clip(dims, prior.mean * 0.4, prior.mean * 2.5)
        else:
            dims = dims_raw

        center = centroid.copy()
        # Snap bottom to observed ground
        y_bottom = float(np.percentile(pts_world[:, 2], 90))
        center[2] = y_bottom - dims[2] / 2.0

        return Label3D(
            class_name=det.class_name,
            center=center,
            dimensions=dims,
            rotation=pca_yaw,
            score=det.score,
            source="auto",
        )

    # ── ground-ray fallback ───────────────────────────────────────────────

    def _ground_ray_project(
        self,
        det: Detection2D,
        calib: CalibrationBundle,
        camera: str,
        ground_plane: np.ndarray | None,
    ) -> Label3D | None:
        """Intersect the detection bbox-centre camera ray with the ground plane.

        Used when no LiDAR points fall inside the frustum (e.g. rear / side
        cameras with sparse rear LiDAR coverage).  Returns a box whose XY
        position is estimated from the ground intersection and whose dimensions
        come from class size priors.  Score is halved to signal lower confidence.
        """
        if ground_plane is None:
            return None
        intr = calib.intrinsics.get(camera)
        if intr is None:
            return None
        T = calib.extrinsics.get(camera, np.eye(4))
        R_mat = T[:3, :3]   # LiDAR → camera rotation
        t_vec = T[:3, 3]    # translation

        # Camera optical centre in LiDAR frame:  T_inv @ [0,0,0,1] = −R^T t
        cam_orig = -(R_mat.T @ t_vec)

        # Pixel ray direction in camera frame (bbox centre)
        x1, y1, x2, y2 = det.bbox
        cx_pix = (x1 + x2) / 2.0
        cy_pix = (y1 + y2) / 2.0
        d_cam = np.array([(cx_pix - intr.cx) / intr.fx,
                          (cy_pix - intr.cy) / intr.fy,
                          1.0])
        # Transform ray direction to LiDAR frame:  R^T @ d_cam
        d_ldr = R_mat.T @ d_cam
        dn = np.linalg.norm(d_ldr)
        if dn < 1e-8:
            return None
        d_ldr /= dn

        # Intersect with ground plane: ax+by+cz+d=0
        a, b, c, d_plane = ground_plane
        denom = a * d_ldr[0] + b * d_ldr[1] + c * d_ldr[2]
        if abs(denom) < 1e-6:
            return None
        t_param = -(a * cam_orig[0] + b * cam_orig[1] + c * cam_orig[2] + d_plane) / denom
        if t_param < 0.5:   # ground intersection must be in front of camera
            return None

        ground_hit = cam_orig + t_param * d_ldr

        prior = CLASS_SIZE_PRIORS.get(det.class_name)
        dims = prior.mean.copy() if prior is not None else np.array([4.0, 1.8, 1.5])

        gz = estimate_ground_z_at(ground_hit[:2], ground_plane)
        center = ground_hit.copy()
        center[2] = gz + dims[2] / 2.0

        return Label3D(
            class_name=det.class_name,
            center=center,
            dimensions=dims,
            rotation=0.0,
            score=det.score * 0.6,   # lower confidence for ray-only estimate
            source="ground_ray",
        )

    # ── Manual user-bbox path ─────────────────────────────────────────────

    def project_user_bbox(
        self,
        det: Detection2D,
        calib: CalibrationBundle,
        camera: str,
        lidar_points: np.ndarray,
        ground_plane: np.ndarray | None,
    ) -> Label3D | None:
        """Project a USER-drawn 2D bbox to 3D, anchored to the bbox-centre ray.

        Differences vs ``_frustum_project`` (designed for auto-detections):

        * Position anchor = intersection of the bbox-centre camera ray with
          the ground plane.  The 3D box ground-centre is forced to lie within
          a class-prior radius of that anchor → the resulting box ALWAYS
          appears under the user's selection.
        * LiDAR points beyond ``prior.mean[0] * 1.2`` of the anchor are
          discarded BEFORE clustering — eliminates background bleed.
        * Yaw uses PCA + view-direction tie-break:
            - if the principal-axis spread is < 1.3× secondary spread, the
              object is viewed end-on → yaw = perpendicular to camera ray
            - otherwise → yaw = PCA principal axis
        * Size = class prior (no PCA-derived stretching, since visible
          surface is one-sided).
        """
        if lidar_points is None or len(lidar_points) < _MIN_PTS:
            return self._ground_ray_project(det, calib, camera, ground_plane)

        x1, y1, x2, y2 = det.bbox
        cx_pix = (x1 + x2) / 2.0
        cy_pix = (y1 + y2) / 2.0

        # ── 1. Anchor: bbox-centre ray ∩ ground plane ─────────────────────
        intr = calib.intrinsics.get(camera)
        T = calib.extrinsics.get(camera)
        if intr is None or T is None:
            return None
        R_mat = T[:3, :3]
        t_vec = T[:3, 3]
        cam_orig = -(R_mat.T @ t_vec)        # camera optical centre in LiDAR frame

        d_cam = np.array([(cx_pix - intr.cx) / intr.fx,
                          (cy_pix - intr.cy) / intr.fy,
                          1.0])
        d_ldr = R_mat.T @ d_cam
        dn = np.linalg.norm(d_ldr)
        if dn < 1e-8:
            return None
        d_ldr /= dn

        anchor_xy = None
        if ground_plane is not None:
            a, b, c_gp, d_plane = ground_plane
            denom = a * d_ldr[0] + b * d_ldr[1] + c_gp * d_ldr[2]
            if abs(denom) > 1e-6:
                t_param = -(a * cam_orig[0] + b * cam_orig[1]
                            + c_gp * cam_orig[2] + d_plane) / denom
                if t_param > 0.5:
                    anchor_xy = (cam_orig + t_param * d_ldr)[:2]

        # ── 2. Class prior lookup with synonym fallback ───────────────────
        _SYN = {"car": "car", "sedan": "Sedan", "vehicle": "car",
                "vehicle_other": "car", "truck": "truck", "bus": "bus",
                "bus or truck": "Bus or Truck", "pedestrian": "pedestrian",
                "person": "pedestrian", "cyclist": "cyclist",
                "bicycle": "Bicycle", "motorcycle": "Motorcycle"}
        cname = (det.class_name or "").strip()
        prior = (CLASS_SIZE_PRIORS.get(cname)
                 or CLASS_SIZE_PRIORS.get(_SYN.get(cname.lower(), cname))
                 or CLASS_SIZE_PRIORS.get(cname.lower()))

        if prior is not None:
            dims = prior.mean.copy().astype(np.float64)
            radius = float(max(dims[0], dims[1])) * 1.2
        else:
            dims = np.array([2.0, 2.0, 2.0])
            radius = 3.0

        # ── 3. Frustum + ground filter ────────────────────────────────────
        try:
            pixels = calib.project_3d_to_image(lidar_points[:, :3], camera)
        except Exception as exc:
            logger.warning("LiDAR→image projection failed: %s", exc)
            return None
        pts_h = np.hstack([lidar_points[:, :3], np.ones((len(lidar_points), 1))])
        cam_z_all = (T @ pts_h.T)[2]

        in_frustum = (
            (cam_z_all > 0.1)
            & (pixels[:, 0] >= x1) & (pixels[:, 0] <= x2)
            & (pixels[:, 1] >= y1) & (pixels[:, 1] <= y2)
            & (lidar_points[:, 2] >= _Z_MIN) & (lidar_points[:, 2] <= _Z_MAX)
        )
        pts_f = lidar_points[in_frustum, :3]
        if ground_plane is not None and len(pts_f) > 0:
            a, b, c_gp, d_gp = ground_plane
            n_len = np.sqrt(a * a + b * b + c_gp * c_gp) + 1e-9
            h_above = (a * pts_f[:, 0] + b * pts_f[:, 1]
                       + c_gp * pts_f[:, 2] + d_gp) / n_len
            non_ground = h_above > 0.25
            if non_ground.sum() >= _MIN_PTS:
                pts_f = pts_f[non_ground]

        if len(pts_f) < _MIN_PTS:
            return self._ground_ray_project(det, calib, camera, ground_plane)

        # ── 4. Restrict to anchor radius (XY) ─────────────────────────────
        if anchor_xy is not None:
            d2 = np.hypot(pts_f[:, 0] - anchor_xy[0],
                          pts_f[:, 1] - anchor_xy[1])
            near = d2 <= radius
            if near.sum() >= _MIN_PTS:
                pts_obj = pts_f[near]
            else:
                # widen once
                near2 = d2 <= radius * 1.6
                pts_obj = pts_f[near2] if near2.sum() >= _MIN_PTS else pts_f
        else:
            pts_obj = pts_f
            anchor_xy = pts_obj[:, :2].mean(axis=0)

        if len(pts_obj) < _MIN_PTS:
            return self._ground_ray_project(det, calib, camera, ground_plane)

        # ── 5. Yaw: PCA + view-direction tie-break ────────────────────────
        view_xy = anchor_xy - cam_orig[:2]
        v_norm = float(np.linalg.norm(view_xy))
        if v_norm < 1e-6:
            view_xy = np.array([1.0, 0.0])
        else:
            view_xy = view_xy / v_norm

        centered = pts_obj[:, :2] - pts_obj[:, :2].mean(axis=0)
        cov = np.cov(centered.T) if len(centered) > 2 else np.eye(2)
        eigvals, eigvecs = np.linalg.eigh(cov)
        order = np.argsort(eigvals)[::-1]
        eigvals = eigvals[order]
        eigvecs = eigvecs[:, order]
        major_axis = eigvecs[:, 0]
        minor_axis = eigvecs[:, 1]

        ratio = float(eigvals[0] / max(eigvals[1], 1e-9))
        if ratio < 1.3:
            # Object viewed end-on → length axis ⟂ view direction
            yaw_axis = np.array([-view_xy[1], view_xy[0]])
        else:
            yaw_axis = major_axis
        yaw = float(np.arctan2(yaw_axis[1], yaw_axis[0]))

        # ── 6. Center: ground anchor + half-height up ─────────────────────
        center = np.array([anchor_xy[0], anchor_xy[1], 0.0])
        if ground_plane is not None:
            gz = estimate_ground_z_at(anchor_xy, ground_plane)
            center[2] = gz + dims[2] / 2.0
        else:
            center[2] = float(pts_obj[:, 2].min()) + dims[2] / 2.0

        # ── 7. Surface→centre compensation along view direction ───────────
        # The visible surface sits at the cluster's NEAR edge along the view
        # ray; push the box centre away from the camera by half the depth
        # extent so the box covers the un-seen back of the object.
        try:
            rel = pts_obj[:, :2] - anchor_xy
            depth_proj = rel @ view_xy           # signed depth along view
            depth_min = float(np.min(depth_proj))
            depth_max = float(np.max(depth_proj))
            seen_depth = depth_max - depth_min
            # If we see only a thin slice, the box centre lies BEHIND the cluster
            # near edge by half of the relevant prior dim.
            L, W = float(dims[0]), float(dims[1])
            # use width when viewing long side (more lateral spread), else length
            lateral_dir = np.array([-view_xy[1], view_xy[0]])
            lat_proj = rel @ lateral_dir
            lat_extent = float(lat_proj.max() - lat_proj.min())
            depth_half = W / 2.0 if lat_extent > (L + W) / 2.0 else L / 2.0
            target_centre_depth = depth_min + depth_half
            # Only shift when seen_depth is much smaller than expected box depth
            if seen_depth < depth_half * 1.5:
                center[:2] = anchor_xy + target_centre_depth * view_xy
        except Exception:
            pass

        return Label3D(
            class_name=det.class_name,
            center=center,
            dimensions=dims,
            rotation=yaw,
            score=det.score,
            source="user_bbox",
        )

