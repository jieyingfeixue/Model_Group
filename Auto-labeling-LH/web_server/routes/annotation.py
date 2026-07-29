"""Annotation endpoints — 2D detection and 2D→3D box creation."""

from __future__ import annotations

import logging

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..dependencies import get_loader, get_or_create_session
from ..config import DATASET_ROOT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["annotation"])


class DetectRequest(BaseModel):
    seq_id: str
    frame_id: str
    camera_key: str | None = None  # None = all cameras with intrinsics
    dataset_root: str = str(DATASET_ROOT)
    profile: str = "lh"
    prompt: str | None = None  # For Grounding DINO


class BoxFrom2DRequest(BaseModel):
    seq_id: str
    frame_id: str
    camera_key: str
    bbox: list[float]  # [x1, y1, x2, y2]
    class_name: str
    dataset_root: str = str(DATASET_ROOT)
    profile: str = "lh"


@router.post("/detect")
async def run_detection(req: DetectRequest):
    """Run 2D object detection on a frame's camera image(s)."""
    try:
        from src.core.config import load_config
        from src.models.model_manager import ModelManager

        loader = get_loader(req.dataset_root, req.profile)
        import asyncio

        frame = await asyncio.to_thread(loader.load_frame, req.seq_id, req.frame_id)

        config = load_config()

        def create_detector():
            return ModelManager(config).get_detector()

        detector = await asyncio.to_thread(create_detector)

        if detector is None:
            raise HTTPException(status_code=500, detail="No detector available")

        # Determine cameras to run detection on
        cam_list = [req.camera_key] if req.camera_key else list(frame.images.keys())
        # Filter to cameras that have calibration intrinsics
        if frame.calibration and frame.calibration.intrinsics:
            cam_list = [c for c in cam_list if c in frame.calibration.intrinsics]
        if not cam_list:
            cam_list = [list(frame.images.keys())[0]]  # fallback to primary

        all_detections: dict[str, list] = {}
        for cam_name in cam_list:
            img = frame.images.get(cam_name)
            if img is None:
                continue
            try:
                dets = await asyncio.to_thread(detector.detect, img, req.prompt)
                all_detections[cam_name] = [
                    {"bbox": list(d.bbox), "class_name": d.class_name,
                     "score": d.score}
                    for d in dets
                ]
            except Exception as exc:
                logger.warning("Detection failed for %s: %s", cam_name, exc)
                all_detections[cam_name] = []

        return {
            "seq_id": req.seq_id,
            "frame_id": req.frame_id,
            "detections_per_cam": all_detections,
            "total": sum(len(v) for v in all_detections.values()),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Detection failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/box-from-2d")
async def create_box_from_2d(req: BoxFrom2DRequest):
    """Convert a 2D bounding box to a 3D box via LiDAR frustum / depth projection."""
    try:
        from src.fusion.box_from_2d_v3 import fit_box_from_2d
        from src.core.types import Detection2D

        loader = get_loader(req.dataset_root, req.profile)
        import asyncio

        frame = await asyncio.to_thread(loader.load_frame, req.seq_id, req.frame_id)

        if req.camera_key not in frame.images:
            raise HTTPException(status_code=404, detail=f"Camera '{req.camera_key}' not found")

        if frame.calibration is None:
            raise HTTPException(status_code=400, detail="No calibration available for this frame")

        detection = Detection2D(
            bbox=tuple(req.bbox),
            class_name=req.class_name,
            score=1.0,
        )

        # Determine LiDAR key
        from src.core.pipeline import _pick_lidar

        lidar_key = _pick_lidar(frame)

        lidar_pts = frame.pointclouds.get(lidar_key) if lidar_key else None

        box = await asyncio.to_thread(
            fit_box_from_2d,
            detection=detection,
            image=frame.images[req.camera_key],
            calibration=frame.calibration,
            camera_key=req.camera_key,
            lidar_points=lidar_pts,
        )

        if box is None:
            raise HTTPException(status_code=400, detail="Failed to fit 3D box from 2D detection")

        return {
            "box": {
                "object_id": box.object_id,
                "class_name": box.class_name,
                "center": box.center.tolist(),
                "dimensions": box.dimensions.tolist(),
                "rotation": box.rotation,
                "score": box.score,
                "source": box.source,
                "track_id": box.track_id,
                "attributes": box.attributes,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("box-from-2d failed")
        raise HTTPException(status_code=500, detail=str(e))
