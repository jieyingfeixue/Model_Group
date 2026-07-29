"""Core data types used throughout the application."""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np


# ---------------------------------------------------------------------------
# 3D annotation
# ---------------------------------------------------------------------------

@dataclass
class Label3D:
    """Universal 3D bounding box annotation."""

    object_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    class_name: str = ""
    center: np.ndarray = field(default_factory=lambda: np.zeros(3))
    dimensions: np.ndarray = field(default_factory=lambda: np.ones(3))
    rotation: float = 0.0  # yaw in radians
    score: float = 1.0
    source: str = "manual"  # manual | auto | refined
    track_id: int = -1
    visibility: dict[str, bool] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)

    def copy(self) -> "Label3D":
        return Label3D(
            object_id=self.object_id,
            class_name=self.class_name,
            center=self.center.copy(),
            dimensions=self.dimensions.copy(),
            rotation=self.rotation,
            score=self.score,
            source=self.source,
            track_id=self.track_id,
            visibility=dict(self.visibility),
            attributes=dict(self.attributes),
        )

    def corners(self) -> np.ndarray:
        """Return the 8 corners of the bounding box (8×3)."""
        l, w, h = self.dimensions
        # Corners in local frame (center at origin, no rotation)
        x = np.array([l, l, -l, -l, l, l, -l, -l]) / 2
        y = np.array([w, -w, -w, w, w, -w, -w, w]) / 2
        z = np.array([h, h, h, h, -h, -h, -h, -h]) / 2
        local = np.stack([x, y, z], axis=-1)  # (8, 3)
        # Apply yaw rotation around Z axis
        c, s = np.cos(self.rotation), np.sin(self.rotation)
        rot = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        rotated = local @ rot.T
        return rotated + self.center


# ---------------------------------------------------------------------------
# 2D detection
# ---------------------------------------------------------------------------

@dataclass
class Detection2D:
    """2D image-space detection result."""

    bbox: tuple[float, float, float, float]  # x1, y1, x2, y2
    class_name: str = ""
    score: float = 0.0
    mask: np.ndarray | None = None


# ---------------------------------------------------------------------------
# Frame data bundle
# ---------------------------------------------------------------------------

@dataclass
class FrameData:
    """All sensor data for a single frame."""

    seq_id: str = ""
    frame_id: str = ""
    images: dict[str, np.ndarray] = field(default_factory=dict)
    pointclouds: dict[str, np.ndarray] = field(default_factory=dict)
    radar_tensors: dict[str, np.ndarray] = field(default_factory=dict)
    calibration: "CalibrationBundle | None" = None
    labels: list[Label3D] | None = None
    timestamp: float = 0.0
    meta: dict = field(default_factory=dict)  # GPS, ENU radar, etc.


# ---------------------------------------------------------------------------
# Calibration
# ---------------------------------------------------------------------------

@dataclass
class CameraIntrinsics:
    fx: float = 1.0
    fy: float = 1.0
    cx: float = 0.0
    cy: float = 0.0
    distortion: np.ndarray = field(default_factory=lambda: np.zeros(5))

    @property
    def matrix(self) -> np.ndarray:
        return np.array([
            [self.fx, 0, self.cx],
            [0, self.fy, self.cy],
            [0, 0, 1],
        ])


@dataclass
class CalibrationBundle:
    """Holds all sensor-to-sensor transforms."""

    intrinsics: dict[str, CameraIntrinsics] = field(default_factory=dict)
    extrinsics: dict[str, np.ndarray] = field(default_factory=dict)  # sensor → 4×4

    def get_transform(self, src: str, dst: str) -> np.ndarray:
        """Get 4×4 transform from *src* frame to *dst* frame."""
        if src == dst:
            return np.eye(4)
        T_src = self.extrinsics.get(src, np.eye(4))
        T_dst = self.extrinsics.get(dst, np.eye(4))
        return np.linalg.inv(T_dst) @ T_src

    def project_3d_to_image(self, pts: np.ndarray, camera: str) -> np.ndarray:
        """Project Nx3 world points to Nx2 image pixels.

        Applies lens distortion (OpenCV [k1,k2,p1,p2,k3] convention) when the
        camera intrinsics include a non-zero distortion vector.  Without this
        correction, edge pixels can be off by 10-30 px on K-Radar's wide-FoV
        cam-front (verified empirically: max 36 px at u≈1100).
        """
        T = self.extrinsics.get(camera, np.eye(4))
        intr = self.intrinsics[camera]
        K = intr.matrix
        dist = np.asarray(intr.distortion, dtype=np.float64).ravel()
        pts_h = np.hstack([pts, np.ones((len(pts), 1))])
        cam_pts = (T @ pts_h.T).T[:, :3]
        if dist.size >= 4 and np.any(np.abs(dist) > 1e-9):
            import cv2
            rvec = np.zeros(3, dtype=np.float64)
            tvec = np.zeros(3, dtype=np.float64)
            uv, _ = cv2.projectPoints(
                cam_pts.reshape(-1, 1, 3).astype(np.float64),
                rvec, tvec, K.astype(np.float64), dist,
            )
            return uv.reshape(-1, 2)
        proj = (K @ cam_pts.T).T
        proj[:, :2] /= proj[:, 2:3] + 1e-8
        return proj[:, :2]


# ---------------------------------------------------------------------------
# Radar ROI
# ---------------------------------------------------------------------------

@dataclass
class RadarROI:
    indices: tuple[np.ndarray, np.ndarray] = field(default_factory=lambda: (np.array([]), np.array([])))
    tensor: np.ndarray = field(default_factory=lambda: np.array([]))
    stats: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

@dataclass
class SessionState:
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    profile_name: str = ""
    seq_id: str = ""
    frame_id: str = ""
    boxes: list[Label3D] = field(default_factory=list)
    detections_2d: list[Detection2D] | None = None
    # Per-camera 2D detections (Phase 1 multi-camera detection)
    detections_2d_per_cam: dict[str, list[Detection2D]] = field(default_factory=dict)
    depth_map: np.ndarray | None = None
    ground_plane: np.ndarray | None = None
    stage: str = "init"  # init | detected | projected | lidar_fitted | radar_mapped | reviewed | exported
    # Phase 4: Operation-based undo history
    operations: deque = field(default_factory=lambda: deque(maxlen=200))

    def get_box(self, box_id: str) -> Label3D | None:
        for b in self.boxes:
            if b.object_id == box_id:
                return b
        return None


# ---------------------------------------------------------------------------
# Operation (Phase 4: unified undo history)
# ---------------------------------------------------------------------------

import time as _time

@dataclass
class Operation:
    """A reversible operation recorded for the unified undo/redo stack.

    ``before`` and ``after`` hold deep-copied box lists so the operation
    can be applied forward (redo) or backwards (undo) without recomputation.
    """
    kind: str = ""       # create | delete | modify | auto_annotate | calibrate
    frame_id: str = ""
    seq_id: str = ""
    before: list = field(default_factory=list)   # list[Label3D] snapshot before
    after: list = field(default_factory=list)    # list[Label3D] snapshot after
    timestamp: float = field(default_factory=_time.time)
    description: str = ""

    def summary(self) -> str:
        """Short human-readable label shown in undo history."""
        n_before = len(self.before)
        n_after = len(self.after)
        if self.description:
            return self.description
        if self.kind == "auto_annotate":
            return f"自动标注 → {n_after} 个框"
        if self.kind == "create":
            return f"新建框 ({n_after - n_before:+d})"
        if self.kind == "delete":
            return f"删除框 ({n_after - n_before:+d})"
        if self.kind == "modify":
            return f"修改框"
        if self.kind == "calibrate":
            return "标定调整"
        return self.kind


# ---------------------------------------------------------------------------
# Agent types
# ---------------------------------------------------------------------------

@dataclass
class AutoAction:
    type: str = ""  # adjust_dimensions | adjust_center_z | adjust_yaw | delete | delete_lower_score
    value: Any = None
    confidence: float = 0.0


@dataclass
class RuleResult:
    rule: str = ""
    severity: str = "ok"  # ok | warning | error | skip
    message: str = ""
    auto_action: AutoAction | None = None
    box_id: str = ""


@dataclass
class AgentAction:
    box_id: str = ""
    action_type: str = ""  # adjust | delete | confirm | refit
    confidence: float = 0.0
    changes: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


@dataclass
class VisionVerification:
    box_id: str = ""
    alignment: str = "good"
    class_correct: bool = True
    suggested_class: str = ""
    notes: str = ""


@dataclass
class FinalDecision:
    box_id: str = ""
    action: str = "keep"  # keep | adjust | delete
    confidence: float = 1.0
    execution_mode: str = "info_only"  # auto | ask_human | info_only
    changes: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)
    source: str = ""


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

@dataclass
class MatchRow:
    pred_id: str = ""
    gt_index: int = -1
    class_name: str = ""
    iou_3d: float = 0.0
    dx: float = 0.0
    dy: float = 0.0
    dz: float = 0.0
    dh: float = 0.0
    dw: float = 0.0
    dl: float = 0.0
    dyaw: float = 0.0


@dataclass
class EvalSummary:
    class_ap: dict[str, float] = field(default_factory=dict)
    match_rows: list[MatchRow] = field(default_factory=list)
    total_pred: int = 0
    total_gt: int = 0
