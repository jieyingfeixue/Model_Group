"""Frame data serving endpoints — images, pointclouds, radar, calibration.

NOTE: seq_id and frame_id may contain "/" characters, so they are passed as
query parameters instead of path parameters.
"""

from __future__ import annotations

import io
import logging
from typing import Any

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from ..config import MAX_POINT_CLOUD_POINTS
from ..dependencies import get_loader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/frames", tags=["frames"])


def _get_frame(seq_id: str, frame_id: str, dataset_root: str, profile: str):
    """Load a frame, raising 404 if not found."""
    try:
        loader = get_loader(dataset_root, profile)
        return loader.load_frame(seq_id, frame_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Failed to load frame %s/%s", seq_id, frame_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/metadata")
async def get_frame_metadata(
    seq_id: str = Query(..., description="Sequence ID"),
    frame_id: str = Query(..., description="Frame ID"),
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
):
    """Return frame metadata (sensor list, calibration, GPS, etc.) — no binary blobs."""
    frame = _get_frame(seq_id, frame_id, dataset_root, profile)

    # Serialize calibration
    calib_data: dict[str, Any] | None = None
    if frame.calibration:
        calib_data = {"intrinsics": {}, "extrinsics": {}}
        for cam, intrinsics in (frame.calibration.intrinsics or {}).items():
            calib_data["intrinsics"][cam] = {
                "fx": intrinsics.fx, "fy": intrinsics.fy,
                "cx": intrinsics.cx, "cy": intrinsics.cy,
                "distortion": intrinsics.distortion.tolist() if intrinsics.distortion is not None else None,
            }
        for sensor, T in (frame.calibration.extrinsics or {}).items():
            calib_data["extrinsics"][sensor] = T.tolist() if T is not None else None

    # Image sizes
    images_info = {}
    for cam, img in frame.images.items():
        images_info[cam] = {"width": img.shape[1], "height": img.shape[0],
                            "channels": img.shape[2] if len(img.shape) > 2 else 1}

    # Point cloud sizes
    pc_info = {}
    for lidar, pc in frame.pointclouds.items():
        pc_info[lidar] = {"points": len(pc), "columns": pc.shape[1]}

    # Radar tensor sizes
    radar_info = {}
    for radar, tensor in frame.radar_tensors.items():
        radar_info[radar] = {"shape": list(tensor.shape), "dtype": str(tensor.dtype)}

    return {
        "seq_id": seq_id,
        "frame_id": frame_id,
        "timestamp": frame.timestamp,
        "cameras": images_info,
        "pointclouds": pc_info,
        "radar_tensors": radar_info,
        "calibration": calib_data,
        "meta": _serialize_meta(frame.meta),
        "label_count": len(frame.labels) if frame.labels else 0,
    }


@router.get("/image")
async def get_frame_image(
    seq_id: str = Query(..., description="Sequence ID"),
    frame_id: str = Query(..., description="Frame ID"),
    camera_key: str = Query(..., description="Camera sensor key"),
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
):
    """Serve a camera image as JPEG."""
    import cv2

    frame = _get_frame(seq_id, frame_id, dataset_root, profile)
    if camera_key not in frame.images:
        raise HTTPException(status_code=404, detail=f"Camera '{camera_key}' not in frame")

    img_rgb = frame.images[camera_key]
    _, buf = cv2.imencode(".jpg", cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR))

    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/thumb")
async def get_frame_thumbnail(
    seq_id: str = Query(..., description="Sequence ID"),
    frame_id: str = Query(..., description="Frame ID"),
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
):
    """Return a JPEG thumbnail for a frame."""
    import cv2

    frame = _get_frame(seq_id, frame_id, dataset_root, profile)
    if not frame.images:
        raise HTTPException(status_code=404, detail="No camera images in frame")

    primary_cam = next(iter(frame.images))
    img = frame.images[primary_cam]
    h, w = img.shape[:2]

    thumb_w, thumb_h = 320, 240
    scale = min(thumb_w / w, thumb_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    thumb = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    _, buf = cv2.imencode(".jpg", cv2.cvtColor(thumb, cv2.COLOR_RGB2BGR))
    return Response(
        content=buf.tobytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/pointcloud")
async def get_frame_pointcloud(
    seq_id: str = Query(..., description="Sequence ID"),
    frame_id: str = Query(..., description="Frame ID"),
    lidar_key: str = Query(..., description="LiDAR sensor key"),
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
    downsample: int = Query(0, description="Target point count (0=auto, negative=no downsample)"),
):
    """Serve a LiDAR point cloud as N×4 float32 binary (x, y, z, intensity)."""
    frame = _get_frame(seq_id, frame_id, dataset_root, profile)
    if lidar_key not in frame.pointclouds:
        raise HTTPException(status_code=404, detail=f"LiDAR '{lidar_key}' not in frame")

    pc = frame.pointclouds[lidar_key]

    if pc.shape[1] >= 4:
        data = pc[:, :4].astype(np.float32)
    else:
        # Pad with zeros if fewer columns
        data = np.zeros((len(pc), 4), dtype=np.float32)
        for c in range(min(pc.shape[1], 4)):
            data[:, c] = pc[:, c].astype(np.float32)

    target = downsample if downsample > 0 else MAX_POINT_CLOUD_POINTS
    if target > 0 and len(data) > target:
        indices = np.linspace(0, len(data) - 1, target, dtype=int)
        data = data[indices]

    binary = data.tobytes()
    return Response(
        content=binary,
        media_type="application/octet-stream",
        headers={
            "X-Point-Count": str(len(data)),
            "X-Original-Count": str(len(pc)),
        },
    )


@router.get("/radar")
async def get_frame_radar(
    seq_id: str = Query(..., description="Sequence ID"),
    frame_id: str = Query(..., description="Frame ID"),
    radar_key: str = Query(..., description="Radar sensor key"),
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
):
    """Serve a radar tensor as NPZ binary."""
    from io import BytesIO

    frame = _get_frame(seq_id, frame_id, dataset_root, profile)
    if radar_key not in frame.radar_tensors:
        raise HTTPException(status_code=404, detail=f"Radar '{radar_key}' not in frame")

    tensor = frame.radar_tensors[radar_key]
    buf = BytesIO()
    np.savez_compressed(buf, data=tensor)
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type="application/octet-stream",
        headers={
            "X-Tensor-Shape": str(list(tensor.shape)),
            "X-Tensor-Dtype": str(tensor.dtype),
        },
    )


@router.get("/calibration")
async def get_frame_calibration(
    seq_id: str = Query(..., description="Sequence ID"),
    frame_id: str = Query(..., description="Frame ID"),
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
):
    """Return calibration data as JSON."""
    frame = _get_frame(seq_id, frame_id, dataset_root, profile)
    if frame.calibration is None:
        raise HTTPException(status_code=404, detail="No calibration available")

    intrinsics = {}
    for cam, intr in (frame.calibration.intrinsics or {}).items():
        intrinsics[cam] = {
            "fx": intr.fx, "fy": intr.fy, "cx": intr.cx, "cy": intr.cy,
            "distortion": intr.distortion.tolist() if intr.distortion is not None else [0]*5,
        }

    extrinsics = {}
    for sensor, T in (frame.calibration.extrinsics or {}).items():
        extrinsics[sensor] = T.tolist() if T is not None else None

    return {
        "seq_id": seq_id,
        "frame_id": frame_id,
        "intrinsics": intrinsics,
        "extrinsics": extrinsics,
    }


# ── helpers ─────────────────────────────────────────────────────────────────

def _serialize_meta(meta: dict) -> dict:
    """Convert numpy arrays in meta dict to JSON-serializable types."""
    result = {}
    for k, v in meta.items():
        if isinstance(v, np.ndarray):
            result[k] = v.tolist()
        elif isinstance(v, (np.floating, float)):
            result[k] = float(v)
        elif isinstance(v, (np.integer, int)):
            result[k] = int(v)
        elif isinstance(v, dict):
            result[k] = _serialize_meta(v)
        else:
            result[k] = v
    return result
