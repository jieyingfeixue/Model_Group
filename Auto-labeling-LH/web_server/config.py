"""Server configuration."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPO_ROOT = PROJECT_ROOT.parent


def _resolve_dataset_root() -> Path:
    """Prefer LH_DATASET_ROOT; else NAS path; else local repo capture folders."""
    env = os.environ.get("LH_DATASET_ROOT", "").strip()
    if env:
        return Path(env).expanduser()

    nas = Path("/data1/LHO/nas/LH_Dataset/LH_data_all_sensor")
    if nas.exists():
        return nas

    # 本地联调：仓库根下已有 with_cameras_capture_*
    # 注意：不要指到 E:\\robot，那里没有 LH 采集目录结构
    if any(REPO_ROOT.glob("with_cameras_capture_*")):
        return REPO_ROOT

    local_bundle = PROJECT_ROOT / "local_dataset"
    if local_bundle.exists():
        return local_bundle

    return nas


# Server host/port
HOST = os.environ.get("WEB_HOST", "0.0.0.0")
PORT = int(os.environ.get("WEB_PORT", "8080"))

# CORS origins (comma-separated)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*").split(",")

DATASET_ROOT = _resolve_dataset_root()
SAM3_SOURCE_ROOT = Path(os.environ.get(
    "SAM3_SOURCE_ROOT", str(PROJECT_ROOT.parent / "sam3-main")
)).expanduser()
SAM3_CHECKPOINT = Path(os.environ.get(
    "SAM3_CHECKPOINT", str(PROJECT_ROOT.parent / "sam3-main" / "sam3.pt")
)).expanduser()
MODEL_DEVICE = os.environ.get("MODEL_DEVICE", "cuda")

# Depth Anything 3 is deployed fully offline next to the application.  Keep
# source and weights configurable independently so the server can later move
# either asset without changing application code.
DA3_ROOT = Path(os.environ.get(
    "DA3_ROOT", str(PROJECT_ROOT.parent / "DA3_main")
)).expanduser()
DA3_SOURCE_ROOT = Path(os.environ.get(
    "DA3_SOURCE_ROOT", str(DA3_ROOT / "Depth-Anything-3")
)).expanduser()
DA3_DEVICE = os.environ.get("DA3_DEVICE", MODEL_DEVICE)
DA3_PROCESS_RES = int(os.environ.get("DA3_PROCESS_RES", "504"))

# SAM3 auto-annotation output.  Keep this outside the application directory so
# the generated labels mirror the dataset tree directly under nas_write.
LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT = Path(os.environ.get(
    "LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT",
    str(PROJECT_ROOT.parent / "label_with_annotation_and_depth"),
)).expanduser()

# Sessions directory (server-side)
SESSIONS_DIR = Path(os.environ.get("SESSIONS_DIR", str(PROJECT_ROOT / "sessions")))

# Max point cloud points to serve (downsample if larger)
MAX_POINT_CLOUD_POINTS = int(os.environ.get("MAX_POINT_CLOUD_POINTS", "200000"))

# Pipeline task timeout (seconds)
PIPELINE_TIMEOUT = int(os.environ.get("PIPELINE_TIMEOUT", "300"))

# Camera geometry — from oST stereo calibration (rightcam(1)):
#   Left  DA8679037: fx=12342.23, fy=12338.27, cx=959.5, cy=599.5
#   Right DA8679038: fx=12585.59, fy=12588.75, cx=959.5, cy=599.5
#   Both already rectified (distortion=0).
# HFOV_left  = 2 * atan(1920 / (2 * 12342.23)) ≈ 8.88°
# HFOV_right = 2 * atan(1920 / (2 * 12585.59)) ≈ 8.71°
CAMERA_HFOV_DEG = 8.80  # average, fine for azimuth matching

# Stereo baseline from mechanical design
STEREO_BASELINE_M = 0.4
STEREO_MIN_DEPTH_M = 400.0
STEREO_MAX_DEPTH_M = 4000.0

# Per-camera intrinsics (rectified, no distortion)
CAMERA_INTRINSICS = {
    "037": {"fx": 12342.23, "fy": 12338.27, "cx": 959.5, "cy": 599.5},
    "038": {"fx": 12585.59, "fy": 12588.75, "cx": 959.5, "cy": 599.5},
}

# Thumbnail size
THUMBNAIL_SIZE = (320, 240)


def get_app_config() -> dict[str, Any]:
    """Load the application configuration (reuses src.core.config)."""
    import sys
    _ensure_project_root()
    from src.core.config import load_config
    return load_config()


def _ensure_project_root() -> None:
    """Ensure the project root is on sys.path."""
    project_root = str(Path(__file__).resolve().parent.parent)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
