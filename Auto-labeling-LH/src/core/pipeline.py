"""One-click AutoPipeline orchestrating all stages."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from .types import FrameData, FinalDecision, Label3D, SessionState

logger = logging.getLogger(__name__)


class AutoPipeline:
    """
    Full auto-annotation pipeline triggered by Space key.
    Stages: detect → project → lidar_fit → radar_map → agent
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self._detector = None
        self._depth = None
        self._projector = None
        self._lidar_fitter = None
        self._radar_projector = None
        self._rule_engine = None
        self._llm_agent = None
        self._vision_agent = None
        self._merger = None
        # cam_key → "left"|"right": crop stereo pair before detection
        self.stereo_crop: dict[str, str] = {}

    def ensure_models(self) -> None:
        """Lazily initialise model wrappers on first use."""
        if self._detector is not None:
            return

        from src.models.model_manager import ModelManager
        from src.fusion.image_to_3d import ImageTo3DProjector
        from src.fusion.lidar_fitting import LiDARFitter
        from src.fusion.radar_projection import RadarProjector
        from src.agent.rule_engine import RuleEngine
        from src.agent.llm_agent import LLMAgent
        from src.agent.vision_agent import VisionAgent
        from src.agent.decision_merger import DecisionMerger

        mm = ModelManager(self.config)
        self._detector = mm.get_detector()
        self._depth = mm.get_depth_estimator()
        self._projector = ImageTo3DProjector()
        self._lidar_fitter = LiDARFitter()
        self._radar_projector = RadarProjector()
        self._rule_engine = RuleEngine(self.config.get("agent", {}).get("rule_engine", {}))
        agent_cfg = self.config.get("agent", {})
        if agent_cfg.get("enabled"):
            self._llm_agent = LLMAgent(agent_cfg.get("llm_agent", {}))
            self._vision_agent = VisionAgent(agent_cfg.get("vision_agent", {}))
        self._merger = DecisionMerger(agent_cfg.get("decision", {}))

    async def run(
        self,
        frame: FrameData,
        progress: Callable[[str, int], None] | None = None,
    ) -> SessionState:
        """Execute the full pipeline and return a populated SessionState."""
        self.ensure_models()

        def _p(stage: str, pct: int) -> None:
            if progress:
                progress(stage, pct)

        state = SessionState(seq_id=frame.seq_id, frame_id=frame.frame_id)

        # 1 ── detect (all cameras with intrinsics) ---------------------------
        _p("detect", 0)
        # Phase 1: Detect on every camera that has calibration intrinsics.
        # This dramatically increases recall in all directions vs. single-camera.
        detections_per_cam: dict = {}
        primary_cam = _pick_camera(frame)
        if self._detector and frame.calibration:
            cam_list = [c for c in frame.images if c in (frame.calibration.intrinsics or {})]
            if not cam_list and primary_cam:
                cam_list = [primary_cam]  # fallback: at least primary
            total = max(1, len(cam_list))
            for cam_i, cam_name in enumerate(cam_list):
                try:
                    detect_img = _apply_stereo_crop(frame.images[cam_name],
                                                    self.stereo_crop.get(cam_name))
                    dets = self._detector.detect(detect_img)
                    detections_per_cam[cam_name] = dets
                    _p("detect", int(cam_i / total * 100))
                except Exception as exc:
                    logger.warning("Detection failed for camera %s: %s", cam_name, exc)
                    detections_per_cam[cam_name] = []
        elif self._detector and primary_cam:
            detect_img = _apply_stereo_crop(frame.images[primary_cam],
                                            self.stereo_crop.get(primary_cam))
            dets = self._detector.detect(detect_img)
            detections_per_cam[primary_cam] = dets
        # Legacy flat list (primary cam detections for backward compat)
        detections = detections_per_cam.get(primary_cam, [])
        state.detections_2d = detections
        state.detections_2d_per_cam = detections_per_cam
        _p("detect", 100)

        # 2 ── project detections → 3D via LiDAR frustum ----------------------
        _p("project", 0)
        boxes: list[Label3D] = []
        if frame.calibration:
            lidar_key_depth = _pick_lidar(frame)
            lidar_pts = frame.pointclouds.get(lidar_key_depth) if lidar_key_depth else None

            # Ground plane (shared across all cameras)
            ground: np.ndarray | None = None
            if lidar_pts is not None:
                from src.fusion.geometry import estimate_ground_plane
                ground = estimate_ground_plane(lidar_pts)
                state.ground_plane = ground

            # Project each camera's detections; NMS deduplicate in 3D
            all_cam_boxes: list[Label3D] = []
            cam_list = list(detections_per_cam.keys())
            total_cams = max(1, len(cam_list))
            for cam_i, cam_name in enumerate(cam_list):
                cam_dets = detections_per_cam.get(cam_name, [])
                if not cam_dets:
                    continue
                if cam_name not in (frame.calibration.intrinsics or {}):
                    continue  # no intrinsics → cannot project
                if frame.calibration.extrinsics.get(cam_name) is None:
                    continue  # no extrinsics → skip (non-front cameras w/o calib)
                detect_img_for_depth = _apply_stereo_crop(frame.images.get(cam_name),
                                                          self.stereo_crop.get(cam_name))
                if detect_img_for_depth is None:
                    continue

                # Depth map for this camera
                depth_map: np.ndarray | None = None
                if self._depth:
                    if lidar_pts is not None:
                        depth_map = self._depth.estimate_from_lidar(
                            detect_img_for_depth, lidar_pts,
                            frame.calibration, cam_name,
                        )
                    else:
                        depth_map = self._depth.estimate(detect_img_for_depth)
                if depth_map is None:
                    import numpy as _np
                    depth_map = _np.zeros(detect_img_for_depth.shape[:2], dtype=_np.float32)
                if cam_i == 0:  # only store primary-cam depth_map for compat
                    state.depth_map = depth_map

                for det in cam_dets:
                    box = self._projector.project(
                        det, depth_map, frame.calibration, cam_name,
                        lidar_points=lidar_pts, ground_plane=ground,
                    )
                    if box is not None:
                        all_cam_boxes.append(box)
                _p("project", int((cam_i + 1) / total_cams * 100))

            # 3D NMS: remove duplicate boxes from different cameras
            boxes = _nms_3d(all_cam_boxes, iou_threshold=0.4)
        _p("project", 100)

        # 2b ── LiDAR clustering fallback (ONLY when no camera detections at all) ──
        # If camera produced detections but frustum/depth projection failed, we still
        # trust the camera — do NOT mix in unrelated LiDAR cluster boxes.
        if not boxes and not detections:
            lidar_key_fb = _pick_lidar(frame)
            if lidar_key_fb:
                logger.info("No camera detections — running LiDAR clustering fallback")
                _p("lidar_cluster", 0)
                try:
                    boxes = _lidar_cluster_boxes(frame.pointclouds[lidar_key_fb])
                    logger.info("LiDAR clustering found %d candidate boxes", len(boxes))
                except Exception as exc:
                    logger.warning("LiDAR clustering failed: %s", exc)
                _p("lidar_cluster", 100)

        # 3 ── LiDAR fitting (refine boxes that came from frustum or fallback) -
        _p("lidar_fit", 0)
        lidar_key = _pick_lidar(frame)
        if lidar_key and self._lidar_fitter:
            pts = frame.pointclouds[lidar_key]
            # Reuse ground plane computed above; estimate if not available
            if state.ground_plane is None:
                from src.fusion.geometry import estimate_ground_plane
                state.ground_plane = estimate_ground_plane(pts)
            for i, box in enumerate(boxes):
                # Frustum boxes are already fitted; only re-fit if from fallback/depth
                if getattr(box, "source", "") not in ("frustum", "refined"):
                    boxes[i] = self._lidar_fitter.fit(box, pts, state.ground_plane)
        _p("lidar_fit", 100)

        # 4 ── Radar mapping -------------------------------------------------
        _p("radar_map", 0)
        radar_key = _pick_radar(frame)
        if radar_key and self._radar_projector:
            self._radar_projector.map_boxes(boxes, frame.radar_tensors[radar_key])
        _p("radar_map", 100)

        # 5 ── Agent review --------------------------------------------------
        _p("agent", 0)
        decisions: list[FinalDecision] = []
        from src.agent.tool_executor import FrameContext
        ctx = FrameContext(
            seq_id=frame.seq_id,
            frame_id=frame.frame_id,
            boxes=boxes,
            lidar_points=frame.pointclouds.get(lidar_key, None) if lidar_key else None,
            radar_tensor=frame.radar_tensors.get(radar_key, None) if radar_key else None,
            ground_plane=state.ground_plane,
        )
        rule_results = self._rule_engine.check_all_boxes(ctx) if self._rule_engine else []
        llm_actions = []
        vision_results = []
        if self._llm_agent:
            try:
                llm_actions = await self._llm_agent.review_frame(ctx, rule_results)
            except Exception as exc:
                logger.warning("LLM agent failed: %s", exc)
        if self._vision_agent and primary_cam:
            try:
                vision_results = await self._vision_agent.verify_boxes_on_image(
                    frame.images[primary_cam], boxes, frame.calibration, primary_cam
                )
            except Exception as exc:
                logger.warning("Vision agent failed: %s", exc)
        decisions = self._merger.merge(rule_results, llm_actions, vision_results)

        # Apply auto decisions
        for d in decisions:
            if d.execution_mode == "auto":
                _apply_decision(boxes, d)
        _p("agent", 100)

        state.boxes = boxes
        state.stage = "reviewed"
        return state


def _apply_stereo_crop(image, side: str | None):
    """Return left or right half of a stereo image. Returns original if side is None.

    No-op when the image is already at single-frame width (<= 1500px),
    since the K-Radar adapter pre-crops + undistorts via
    ``_undistort_camera_images`` for strict consistency with K-Radar's
    official ``show_projected_point_cloud`` flow.
    """
    if side is None or image is None:
        return image
    h, w = image.shape[:2]
    if w <= 1500:
        return image
    half = w // 2
    if side == "left":
        return image[:, :half, :]
    if side == "right":
        return image[:, half:, :]
    return image


def _pick_camera(frame: FrameData) -> str | None:
    for key in ("cam_front", "camera_front", "image"):
        if key in frame.images:
            return key
    return next(iter(frame.images), None)


def _nms_3d(boxes: "list[Label3D]", iou_threshold: float = 0.4) -> "list[Label3D]":
    """Simple 3D NMS: suppress duplicates from multi-camera projection.

    Uses axis-aligned bounding box (AABB) IoU in the XY plane as a proxy
    for 3D overlap.  Keeps the highest-score box when two overlap.
    """
    if not boxes:
        return boxes
    import numpy as np
    # Sort by score descending
    sorted_boxes = sorted(boxes, key=lambda b: getattr(b, "score", 0.0), reverse=True)
    keep: list = []
    suppressed = [False] * len(sorted_boxes)
    for i, bi in enumerate(sorted_boxes):
        if suppressed[i]:
            continue
        keep.append(bi)
        ci = bi.center[:2]
        di = bi.dimensions[:2] / 2.0  # l/2, w/2
        for j in range(i + 1, len(sorted_boxes)):
            if suppressed[j]:
                continue
            bj = sorted_boxes[j]
            cj = bj.center[:2]
            dj = bj.dimensions[:2] / 2.0
            # AABB overlap in XY
            inter_l = np.maximum(0, np.minimum(ci + di, cj + dj) - np.maximum(ci - di, cj - dj))
            inter_area = inter_l[0] * inter_l[1]
            area_i = (di[0] * 2) * (di[1] * 2)
            area_j = (dj[0] * 2) * (dj[1] * 2)
            union_area = area_i + area_j - inter_area
            iou = inter_area / (union_area + 1e-8)
            if iou > iou_threshold:
                suppressed[j] = True
    return keep


def _pick_lidar(frame: FrameData) -> str | None:
    for key in ("os2-64", "os1-128", "lidar", "lidar_at360", "velodyne"):
        if key in frame.pointclouds:
            return key
    # LH keeps mmWave detections in ``pointclouds`` for UI compatibility.
    # Do not silently send those radar points through LiDAR-only algorithms.
    for key in frame.pointclouds:
        normalized = key.lower()
        if "radar" in normalized or "mmwave" in normalized:
            continue
        if any(token in normalized for token in ("lidar", "velo", "ouster", "at360")):
            return key
    return None


def _pick_radar(frame: FrameData) -> str | None:
    for key in ("radar_zyx_cube", "radar_4d", "radar"):
        if key in frame.radar_tensors:
            return key
    return next(iter(frame.radar_tensors), None)


def _apply_decision(boxes: list[Label3D], d: FinalDecision) -> None:
    import numpy as np
    if d.action == "delete":
        boxes[:] = [b for b in boxes if b.object_id != d.box_id]
    elif d.action == "adjust":
        for b in boxes:
            if b.object_id == d.box_id:
                if "center" in d.changes:
                    b.center = np.array(d.changes["center"], dtype=float)
                if "dimensions" in d.changes:
                    b.dimensions = np.array(d.changes["dimensions"], dtype=float)
                if "rotation" in d.changes:
                    b.rotation = float(d.changes["rotation"])


def _lidar_cluster_boxes(
    points: "np.ndarray",
    *,
    voxel_size: float = 0.15,
    eps: float = 0.55,
    min_points: int = 20,           # raised: fewer noise clusters
    max_range: float = 50.0,        # tighter range: far points are noisy
    min_z: float = -2.5,
    max_z: float = 4.0,
    dim_min: float = 0.4,
    dim_max: tuple = (10.0, 6.0, 4.5),
    max_boxes: int = 25,            # hard cap on output count
) -> "list[Label3D]":
    """Ground-removed DBSCAN clustering on LiDAR points → rough 3D boxes.

    Used as a fallback when no 2D detector is available.  Requires open3d
    (already in the venv).
    """
    import numpy as np
    import open3d as o3d
    from src.core.types import Label3D
    from src.fusion.geometry import estimate_ground_plane, compute_pca_yaw

    # ── 1. crop to ROI ────────────────────────────────────────────────────
    pts = points[:, :3].astype(np.float32)
    dists = np.linalg.norm(pts[:, :2], axis=1)
    mask = (dists < max_range) & (pts[:, 2] > min_z) & (pts[:, 2] < max_z)
    pts = pts[mask]
    if len(pts) < min_points * 3:
        return []

    # ── 2. ground removal via RANSAC plane ────────────────────────────────
    pcd = o3d.geometry.PointCloud()
    pcd.points = o3d.utility.Vector3dVector(pts)
    ground_z = -1.5   # default
    try:
        plane_model, inliers = pcd.segment_plane(
            distance_threshold=0.20, ransac_n=3, num_iterations=800
        )
        if len(inliers) > 0:
            ground_pts = pts[np.array(inliers)]
            ground_z = float(np.median(ground_pts[:, 2]))
        non_ground = np.setdiff1d(np.arange(len(pts)), inliers)
        if len(non_ground) < min_points:
            return []
        pts = pts[non_ground]
    except Exception:
        # Fall back to simple height filter
        pts = pts[pts[:, 2] > (ground_z + 0.15)]

    # Remove points too close to the LiDAR (sensor noise)
    dists2 = np.linalg.norm(pts[:, :2], axis=1)
    pts = pts[dists2 > 1.5]

    # ── 3. voxel down-sample for speed ────────────────────────────────────
    pcd2 = o3d.geometry.PointCloud()
    pcd2.points = o3d.utility.Vector3dVector(pts)
    pcd2 = pcd2.voxel_down_sample(voxel_size)
    pts_ds = np.asarray(pcd2.points)

    if len(pts_ds) < min_points:
        return []

    # ── 4. DBSCAN clustering ──────────────────────────────────────────────
    labels = np.array(pcd2.cluster_dbscan(eps=eps, min_points=min_points))
    n_clusters = labels.max() + 1 if labels.max() >= 0 else 0
    if n_clusters == 0:
        return []

    # ── 5. build bounding boxes for each cluster ──────────────────────────
    boxes: list[Label3D] = []
    for cluster_id in range(n_clusters):
        cluster_pts = pts_ds[labels == cluster_id]
        n_pts = len(cluster_pts)
        if n_pts < min_points:
            continue

        centroid = cluster_pts.mean(axis=0)
        yaw = compute_pca_yaw(cluster_pts[:, :2])

        # Rotate into local frame to get tight dimensions
        c, s = np.cos(-yaw), np.sin(-yaw)
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        local = (cluster_pts - centroid) @ R.T
        mins, maxs = local.min(axis=0), local.max(axis=0)
        dims = np.maximum(maxs - mins, dim_min)

        # ── Strict false-positive filters ───────────────────────────
        # 1. Overall size limits
        if dims[0] > dim_max[0] or dims[1] > dim_max[1] or dims[2] > dim_max[2]:
            continue
        # 2. Minimum height: objects shorter than 0.4 m are ground remnants
        if dims[2] < 0.4:
            continue
        # 3. Minimum footprint: avoid pole-like noise (very thin in both XY)
        if min(dims[0], dims[1]) < 0.35:
            continue
        # 4. Aspect ratio: a real object has footprint ratio < 8
        foot_ratio = max(dims[0], dims[1]) / max(min(dims[0], dims[1]), 0.01)
        if foot_ratio > 8.0:
            continue
        # 5. Point density: require reasonable point density per m³
        volume = dims[0] * dims[1] * dims[2]
        density = n_pts / max(volume, 0.01)
        if density < 1.5:          # too sparse → likely wall/road edge artefact
            continue
        # 6. Height-above-ground sanity: centroid should NOT be below ground
        if centroid[2] < ground_z - 0.3:
            continue

        center = centroid.copy()
        center[2] = ground_z + dims[2] / 2.0  # snap bottom to ground

        # Guess class label by size
        l, w, h = dims[0], dims[1], dims[2]
        max_foot = max(l, w)
        if h > 1.3 and max_foot > 3.0:
            class_name = "car"
        elif h > 1.6 and max_foot > 5.0:
            class_name = "truck"
        elif 0.8 < h <= 2.2 and max_foot < 1.2:
            class_name = "pedestrian"
        elif 0.8 < h <= 2.0 and 1.0 < max_foot <= 2.5:
            class_name = "cyclist"
        else:
            class_name = "unknown"

        # 7. Skip "unknown" small clusters that are likely noise
        if class_name == "unknown" and n_pts < min_points * 2:
            continue

        box = Label3D(
            class_name=class_name,
            center=center,
            dimensions=dims,
            rotation=float(yaw),
            score=0.5,
            source="lidar_cluster",
        )
        boxes.append(box)

        if len(boxes) >= max_boxes:
            break   # safety cap

    return boxes
