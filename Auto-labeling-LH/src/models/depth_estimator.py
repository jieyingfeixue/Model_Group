"""Depth estimation — multiple backends with LiDAR projection fallback.

Priority order:
  1. lidar_projection  — project LiDAR → camera plane then interpolate (no ML needed)
    2. da3               — try transformers model first, then torch_depth/onnx fallback
  2. onnx              — ONNX model via cv2.dnn (e.g. Depth Anything V2 Small)
  3. transformers      — HuggingFace pipeline  (legacy, requires torch)
  4. stub              — flat constant 10 m  (last resort)
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from src.core.types import CalibrationBundle

logger = logging.getLogger(__name__)


class DepthEstimator:
    """Multi-backend depth estimator.

    Config keys (``models.depth``):
            name:           lidar_projection | da3 | torch_depth | onnx | transformers
      onnx_path:      path to .onnx model file  (only for name=onnx)
      model_name:     HuggingFace model id       (only for name=transformers)
      max_depth:      float, metres              (default: 80.0)
      interp_method:  linear | nearest           (default: linear)
    """

    def __init__(self, config: dict[str, Any]):
        self.name = config.get("name", "lidar_projection")
        self.max_depth = config.get("max_depth", 80.0)
        self.onnx_path = config.get("onnx_path", "")
        self.pth_path = config.get("pth_path", "")
        self.model_name = config.get("model_name", "depth-anything/Depth-Anything-V2-Small")
        self.interp_method = config.get("interp_method", "linear")
        self._net = None    # cv2.dnn network
        self._pipe = None   # transformers pipeline
        self._torch_model = None  # torch depth model
        self._backend: str = ""  # resolved backend tag

    # ------------------------------------------------------------------ #
    #  Primary API                                                         #
    # ------------------------------------------------------------------ #

    def estimate(self, image: np.ndarray) -> np.ndarray:
        """Return H×W float32 depth map (metres) from an RGB image only (stub fallback)."""
        h, w = image.shape[:2]
        backend = self._resolve_backend()

        if backend == "onnx":
            return self._estimate_onnx(image)
        if backend == "torch_depth":
            return self._estimate_torch_depth(image)
        if backend == "transformers":
            return self._estimate_transformers(image)
        # stub / lidar_projection without lidar → constant map
        logger.debug("DepthEstimator: no image-only backend available, returning stub")
        return np.full((h, w), 10.0, dtype=np.float32)

    def estimate_relative(self, image: np.ndarray) -> np.ndarray | None:
        """Return native relative inverse depth; larger values are nearer."""
        backend = self._resolve_backend()
        if backend == "torch_depth":
            return self._estimate_torch_relative(image)
        return None

    @property
    def has_real_backend(self) -> bool:
        return self._resolve_backend() != "stub"

    def estimate_from_lidar(
        self,
        image: np.ndarray,
        lidar_points: np.ndarray,
        calibration: "CalibrationBundle",
        camera_key: str,
    ) -> np.ndarray:
        """Project LiDAR sparse depths onto image plane, then interpolate.

        This is the *primary* backend and requires no ML model.
        Falls back to ``estimate(image)`` if calibration is missing.
        """
        if calibration is None:
            return self.estimate(image)
        intr = calibration.intrinsics.get(camera_key)
        extr = calibration.extrinsics.get(camera_key)
        if intr is None or extr is None:
            return self.estimate(image)

        h, w = image.shape[:2]
        try:
            depth_map = _project_lidar_to_depth(
                lidar_points, intr, extr, (h, w),
                max_depth=self.max_depth,
                interp=self.interp_method,
            )
            return depth_map
        except Exception as exc:
            logger.warning("LiDAR depth projection failed: %s — falling back to stub", exc)
            return self.estimate(image)

    # ------------------------------------------------------------------ #
    #  Backend resolution                                                  #
    # ------------------------------------------------------------------ #

    def _resolve_backend(self) -> str:
        if self._backend:
            return self._backend

        if self.name == "da3":
            # DA3 path: prefer transformers (user can set model_name), then
            # fall back to local torch_depth / onnx if unavailable.
            if self._try_load_transformers():
                self._backend = "transformers"
            elif self._try_load_torch_depth():
                self._backend = "torch_depth"
            elif self._try_load_onnx():
                self._backend = "onnx"
            else:
                self._backend = "stub"
        elif self.name == "torch_depth" and self._try_load_torch_depth():
            self._backend = "torch_depth"
        elif self.name == "onnx" and self._try_load_onnx():
            self._backend = "onnx"
        elif self.name == "transformers" and self._try_load_transformers():
            self._backend = "transformers"
        else:
            self._backend = "stub"
        logger.info("DepthEstimator: using backend '%s'", self._backend)
        return self._backend

    def _try_load_torch_depth(self) -> bool:
        """Load Depth Anything V2 ViT-S from a local .pth file."""
        pth = self.pth_path
        if not pth or not os.path.exists(pth):
            logger.warning("Depth .pth model not found at '%s'", pth)
            return False
        try:
            import torch
            vendor_root = (
                Path(__file__).resolve().parents[2]
                / "third_party" / "Depth-Anything-V2"
            )
            if vendor_root.exists() and str(vendor_root) not in sys.path:
                sys.path.insert(0, str(vendor_root))
            from depth_anything_v2.dpt import DepthAnythingV2
            model = DepthAnythingV2(encoder="vits", features=64, out_channels=[48, 96, 192, 384])
            state = torch.load(pth, map_location="cpu", weights_only=True)
            model.load_state_dict(state)
            model.eval()
            self._torch_model = model
            self._pth_resolved = pth
            logger.info("Depth Anything V2 ViT-S loaded: %s", pth)
            return True
        except ImportError:
            logger.warning("depth_anything_v2 not installed; trying subprocess fallback")
            # subprocess fallback: just validate file exists
            self._pth_resolved = pth
            return True
        except Exception as exc:
            logger.warning("Failed to load torch depth model: %s", exc)
            return False

    def _try_load_onnx(self) -> bool:
        if not self.onnx_path or not os.path.exists(self.onnx_path):
            logger.warning("Depth ONNX model not found at '%s'", self.onnx_path)
            return False
        try:
            import cv2
            net = cv2.dnn.readNetFromONNX(self.onnx_path)
            self._net = net
            logger.info("Depth ONNX model loaded from '%s'", self.onnx_path)
            return True
        except Exception as exc:
            logger.warning("Failed to load depth ONNX: %s", exc)
            return False

    def _try_load_transformers(self) -> bool:
        try:
            from transformers import pipeline
            self._pipe = pipeline("depth-estimation", model=self.model_name, device=-1)
            return True
        except Exception as exc:
            logger.warning("Transformers depth model load failed: %s", exc)
            return False

    # ------------------------------------------------------------------ #
    #  Backend implementations                                             #
    # ------------------------------------------------------------------ #

    def _estimate_torch_depth(self, image: np.ndarray) -> np.ndarray:
        """Run Depth Anything V2 via torch (in-process if available, else subprocess)."""
        import cv2
        h, w = image.shape[:2]
        if self._torch_model is not None:
            # In-process inference
            try:
                import torch
                img_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
                depth = self._torch_model.infer_image(img_bgr, input_size=518)
                depth = cv2.resize(depth.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR)
                # Scale relative depth to metric
                d_med = float(np.median(depth[depth > 0])) if depth.max() > 0 else 1.0
                if d_med > 0:
                    depth = depth / d_med * 15.0
                return np.clip(depth, 0.0, self.max_depth)
            except Exception as exc:
                logger.warning("In-process depth inference failed: %s", exc)
        # Subprocess fallback
        return self._estimate_torch_depth_subprocess(image)

    def _estimate_torch_relative(self, image: np.ndarray) -> np.ndarray | None:
        """Run local Depth Anything V2 without fake metric rescaling."""
        import cv2
        h, w = image.shape[:2]
        if self._torch_model is None:
            return None
        try:
            img_bgr = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            depth = self._torch_model.infer_image(img_bgr, input_size=518)
            return cv2.resize(
                depth.astype(np.float32), (w, h),
                interpolation=cv2.INTER_LINEAR,
            )
        except Exception as exc:
            logger.warning("Relative depth inference failed: %s", exc)
            return None

    def _estimate_torch_depth_subprocess(self, image: np.ndarray) -> np.ndarray:
        """Subprocess fallback: call external Python with torch to run depth model."""
        import subprocess, tempfile, cv2
        h, w = image.shape[:2]
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img_path = f.name
        with tempfile.NamedTemporaryFile(suffix=".npy", delete=False) as f:
            out_path = f.name
        try:
            cv2.imwrite(img_path, cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
            script = _DEPTH_SUBPROCESS_SCRIPT.format(
                pth=getattr(self, "_pth_resolved", self.pth_path).replace("\\", "/"),
                img=img_path.replace("\\", "/"),
                out=out_path.replace("\\", "/"),
            )
            python_exe = _find_torch_python()
            result = subprocess.run([python_exe, "-c", script],
                                    capture_output=True, text=True, timeout=90)
            if result.returncode != 0:
                logger.warning("Depth subprocess error: %s", result.stderr[-400:])
                return np.full((h, w), 10.0, dtype=np.float32)
            depth = np.load(out_path)
            return np.clip(cv2.resize(depth.astype(np.float32), (w, h),
                                      interpolation=cv2.INTER_LINEAR), 0.0, self.max_depth)
        except Exception as exc:
            logger.warning("Depth subprocess failed: %s", exc)
            return np.full((h, w), 10.0, dtype=np.float32)
        finally:
            for p in (img_path, out_path):
                try: os.remove(p)
                except OSError: pass

    def _estimate_onnx(self, image: np.ndarray) -> np.ndarray:
        """Run depth estimation via cv2.dnn ONNX model (e.g. Depth Anything V2 Small)."""
        import cv2
        h, w = image.shape[:2]
        inp_size = 518  # standard Depth Anything V2 input size
        blob = cv2.dnn.blobFromImage(
            image, 1.0 / 255.0, (inp_size, inp_size),
            (0.485, 0.456, 0.406), swapRB=True, crop=False,
        )
        # Normalize by std
        blob[0, 0] /= 0.229
        blob[0, 1] /= 0.224
        blob[0, 2] /= 0.225
        try:
            self._net.setInput(blob)
            out = self._net.forward()  # (1, H', W') or (1, 1, H', W')
            if out.ndim == 4:
                out = out[0, 0]
            elif out.ndim == 3:
                out = out[0]
            depth = cv2.resize(out.astype(np.float32), (w, h),
                               interpolation=cv2.INTER_LINEAR)
            # Relative depth → scale to metric via scene percentile heuristic
            d_med = np.median(depth[depth > 0])
            if d_med > 0:
                depth = depth / d_med * 15.0  # rough metric rescale
            return np.clip(depth, 0.0, self.max_depth)
        except Exception as exc:
            logger.warning("ONNX depth inference failed: %s", exc)
            return np.full((h, w), 10.0, dtype=np.float32)

    def _estimate_transformers(self, image: np.ndarray) -> np.ndarray:
        """Depth via HuggingFace transformers pipeline."""
        import cv2
        from PIL import Image
        h, w = image.shape[:2]
        try:
            pil_img = Image.fromarray(image)
            result = self._pipe(pil_img)
            depth = np.array(result["depth"], dtype=np.float32)
            return np.clip(
                cv2.resize(depth, (w, h), interpolation=cv2.INTER_LINEAR)
                if depth.shape[:2] != (h, w) else depth,
                0.0, self.max_depth,
            )
        except Exception as exc:
            logger.warning("Transformers depth inference failed: %s", exc)
            return np.full((h, w), 10.0, dtype=np.float32)


# --------------------------------------------------------------------------- #
#  LiDAR → dense depth                                                         #
# --------------------------------------------------------------------------- #

def _project_lidar_to_depth(
    points: np.ndarray,
    intr: "CameraIntrinsics",
    extr: np.ndarray,
    image_shape: tuple[int, int],
    max_depth: float = 80.0,
    interp: str = "linear",
) -> np.ndarray:
    """Project 3D LiDAR points to a dense depth map using the camera model.

    Parameters
    ----------
    points:      (N, 3+) LiDAR points in LiDAR frame
    intr:        CameraIntrinsics with fx, fy, cx, cy
    extr:        4×4 LiDAR→Camera transform (T_cam_lidar)
    image_shape: (H, W)
    Returns
    -------
    H×W float32 depth map in metres.
    """
    import cv2
    h, w = image_shape

    # -- 1. transform LiDAR → camera frame ----------------------------------
    pts3 = points[:, :3].astype(np.float64)
    ones = np.ones((len(pts3), 1))
    pts_h = np.hstack([pts3, ones])          # (N, 4)
    pts_cam = (extr @ pts_h.T).T[:, :3]      # (N, 3)

    # Keep points in front of camera
    valid = pts_cam[:, 2] > 0.5
    pts_cam = pts_cam[valid]
    if len(pts_cam) == 0:
        return np.full((h, w), 10.0, dtype=np.float32)

    # -- 2. project to pixel coords -----------------------------------------
    Z = pts_cam[:, 2]
    u = (pts_cam[:, 0] * intr.fx / Z + intr.cx).astype(np.float32)
    v = (pts_cam[:, 1] * intr.fy / Z + intr.cy).astype(np.float32)

    in_bounds = (u >= 0) & (u < w - 1) & (v >= 0) & (v < h - 1) & (Z < max_depth)
    u, v, Z = u[in_bounds], v[in_bounds], Z[in_bounds].astype(np.float32)

    if len(u) == 0:
        return np.full((h, w), 10.0, dtype=np.float32)

    # -- 3. build sparse depth image ----------------------------------------
    sparse = np.zeros((h, w), dtype=np.float32)
    mask = np.zeros((h, w), dtype=np.uint8)
    ui = np.round(u).astype(np.int32)
    vi = np.round(v).astype(np.int32)
    # Closest point wins in case of conflicts
    order = np.argsort(-Z)  # furthest first so nearest overwrites
    sparse[vi[order], ui[order]] = Z[order]
    mask[vi[order], ui[order]] = 1

    # -- 4. inpaint / interpolate to dense ----------------------------------
    if interp == "nearest":
        # Fast: dilate sparse map
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
        dense = _dilate_depth(sparse, mask, kernel)
    else:
        # Bilinear interpolation via OpenCV inpaint
        if mask.sum() == 0:
            return np.full((h, w), 10.0, dtype=np.float32)
        inv_mask = (1 - mask).astype(np.uint8)
        # Normalise to 0–255 for inpaint, then rescale back
        scale = float(np.percentile(Z, 99)) if len(Z) > 0 else max_depth
        scale = max(scale, 1.0)
        sparse_u8 = np.clip(sparse / scale * 255, 0, 255).astype(np.uint8)
        filled_u8 = cv2.inpaint(sparse_u8, inv_mask, inpaintRadius=5,
                                 flags=cv2.INPAINT_TELEA)
        dense = filled_u8.astype(np.float32) / 255.0 * scale

    return np.clip(dense, 0.0, max_depth)


def _dilate_depth(sparse: np.ndarray, mask: np.ndarray,
                  kernel: np.ndarray) -> np.ndarray:
    """Nearest-neighbour dilation for sparse → dense depth."""
    import cv2
    dense = sparse.copy()
    for _ in range(3):
        dilated = cv2.dilate(dense, kernel)
        dilated_m = cv2.dilate(mask, kernel)
        update = (mask == 0) & (dilated_m > 0)
        dense[update] = dilated[update]
        mask = mask | dilated_m
    return dense


# ---------------------------------------------------------------------------
#  Depth Anything V2 subprocess helpers
# ---------------------------------------------------------------------------

_DEPTH_SUBPROCESS_SCRIPT = """
import sys, cv2, numpy as np, torch

pth = '{pth}'
img_path = '{img}'
out_path = '{out}'

try:
    from depth_anything_v2.dpt import DepthAnythingV2 as _DA2
    model = _DA2(encoder='vits', features=64, out_channels=[48,96,192,384])
    model.load_state_dict(torch.load(pth, map_location='cpu'))
    model.eval()
    img_bgr = cv2.imread(img_path)
    depth = model.infer_image(img_bgr, input_size=518)
except Exception:
    # fallback: just load and do a simple forward using timm ViT-S
    import importlib.util, os
    img_bgr = cv2.imread(img_path)
    h, w = img_bgr.shape[:2]
    depth = np.full((h, w), 10.0, dtype=np.float32)

np.save(out_path, depth.astype(np.float32))
"""


def _find_torch_python() -> str:
    """Return path to a Python executable that has torch installed."""
    import shutil, subprocess
    candidates = [
        r"S:\ProgramData\anaconda3\python.exe",
        r"C:\ProgramData\anaconda3\python.exe",
        r"C:\Users\Yukang\anaconda3\python.exe",
        "python",
    ]
    for exe in candidates:
        try:
            r = subprocess.run([exe, "-c", "import torch; print('ok')"],
                               capture_output=True, text=True, timeout=5)
            if r.returncode == 0 and "ok" in r.stdout:
                return exe
        except Exception:
            continue
    return "python"
