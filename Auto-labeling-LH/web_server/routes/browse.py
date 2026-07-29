"""File-system browse endpoints for direct image access.

Optimised with in-memory caching to avoid slow NAS directory walks.
Tree structure is built once then cached; image lists are loaded on demand.
"""

from __future__ import annotations

import asyncio
import logging
import math
import numpy as np
import os
import re
import struct
import sys
import json
import threading
import time
import csv as csv_mod
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel

from ..config import (
    CAMERA_HFOV_DEG,
    CAMERA_INTRINSICS,
    DA3_DEVICE,
    DA3_PROCESS_RES,
    DA3_ROOT,
    DA3_SOURCE_ROOT,
    DATASET_ROOT,
    LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT,
    MODEL_DEVICE,
    SAM3_CHECKPOINT,
    SAM3_SOURCE_ROOT,
    SESSIONS_DIR,
    STEREO_BASELINE_M,
    STEREO_MAX_DEPTH_M,
    STEREO_MIN_DEPTH_M,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/browse", tags=["browse"])

# Camera directories to look for
CAMERA_DIRS = {
    "037": "hikrobot_camera__DA8679037__image_raw",
    "038": "hikrobot_camera__DA8679038__image_raw",
    "IR":  "usb_ir__image_raw",
}

# ── Cache ────────────────────────────────────────────────────────────────────
# {root_path: {"tree": [...], "timestamp": float}}
_tree_cache: dict[str, dict] = {}
# {(root, path): {"images": [...], "timestamp": float}}
_images_cache: dict[tuple, dict] = {}
_CACHE_TTL = 300  # 5 minutes

# Exact-path cache for the small LabelMe documents shown in the annotation UI.
# Positive and negative results are both cached briefly; save endpoints
# invalidate the corresponding entry immediately.
_feature_annotation_cache: dict[tuple[str, str, str, str], dict] = {}
_feature_annotation_cache_lock = threading.Lock()
_FEATURE_ANNOTATION_CACHE_TTL = 30


def _dataset_root(root: str | Path) -> Path:
    """Resolve and restrict dataset access to the configured offline root."""
    configured = DATASET_ROOT.resolve()
    requested = Path(root).expanduser().resolve()
    if requested != configured:
        raise HTTPException(status_code=403, detail="Dataset root is not allowed")
    return requested


def _safe_join(root: Path, *parts: str) -> Path:
    """Join user-supplied relative paths without allowing ``..`` escape."""
    candidate = root.joinpath(*parts).resolve()
    if not candidate.is_relative_to(root.resolve()):
        raise HTTPException(status_code=400, detail="Path escapes the allowed root")
    return candidate


def _safe_session_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise HTTPException(status_code=400, detail="Invalid relative path")
    return path


def _resolve_cam_dir(cam: str) -> str:
    return CAMERA_DIRS.get(cam, cam)


def _build_tree(root: str) -> list[dict]:
    """Walk only dataset directories; image files are listed on demand."""
    root_path = Path(root)
    if not root_path.exists():
        return []

    tree: list[dict] = []

    try:
        entries = sorted(os.scandir(root_path), key=lambda e: e.name)
    except OSError:
        return tree

    for de in entries:
        if not de.is_dir():
            continue
        name = de.name
        # Filter date-like directories, skip non-data dirs
        if name.startswith('.') or name == '__pycache__':
            continue
        if not any(c.isdigit() for c in name):
            continue
        if any(kw in name.lower() for kw in ('extract', 'train', '山地')):
            continue
        # For 6-11 export dirs, only show the _new version
        if '6-11导出' in name and not name.endswith('_new'):
            continue

        date_node = {"n": name, "c": 0}
        _walk_captures_fast(Path(de.path), date_node)
        if date_node["c"] > 0:
            tree.append(date_node)

    return tree


def _walk_captures_fast(capture_parent: Path, date_node: dict) -> None:
    try:
        entries = sorted(os.scandir(capture_parent), key=lambda e: e.name)
    except OSError:
        return
    for ce in entries:
        if not ce.is_dir() or not ce.name.startswith('with_cameras'):
            continue
        # Skip converted (processed) captures — only show raw data
        if '_converted' in ce.name:
            continue
        cap_node = {"n": ce.name, "c": 0}
        _walk_parts_fast(Path(ce.path), cap_node)
        if cap_node["c"] > 0:
            date_node.setdefault("k", []).append(cap_node)
            date_node["c"] += cap_node["c"]


def _walk_parts_fast(part_parent: Path, cap_node: dict) -> None:
    try:
        entries = sorted(os.scandir(part_parent), key=lambda e: e.name)
    except OSError:
        return
    for pe in entries:
        if not pe.is_dir() or not pe.name.startswith('with_cameras'):
            continue
        if '_converted' in pe.name:
            continue
        part_node = {"n": pe.name, "c": 0}
        _walk_segments_fast(Path(pe.path), part_node)
        if part_node["c"] > 0:
            cap_node.setdefault("k", []).append(part_node)
            cap_node["c"] += part_node["c"]


def _walk_segments_fast(seg_parent: Path, part_node: dict) -> None:
    try:
        entries = sorted(os.scandir(seg_parent), key=lambda e: e.name)
    except OSError:
        return
    for se in entries:
        if not se.is_dir() or not se.name.startswith('segment_'):
            continue
        images_dir = Path(se.path) / "images"
        if not images_dir.exists():
            continue

        seg_node = {"n": se.name, "c": None, "k": []}
        try:
            cam_entries = sorted(os.scandir(images_dir), key=lambda e: e.name)
        except OSError:
            cam_entries = []

        for img_de in cam_entries:
            if not img_de.is_dir():
                continue
            cam_key = None
            for ck, cd in CAMERA_DIRS.items():
                if img_de.name == cd:
                    cam_key = ck
                    break
            if cam_key is None:
                continue

            seg_node["k"].append({
                "n": cam_key,
                "d": img_de.name,
                "c": None,
            })

        if seg_node["k"]:
            part_node.setdefault("k", []).append(seg_node)
            # Parent badges now represent segment counts.  Counting every
            # image here made first-page load proportional to dataset size.
            part_node["c"] += 1


def _get_cached_tree(root: str) -> list[dict]:
    """Return cached tree or rebuild."""
    now = time.time()
    cached = _tree_cache.get(root)
    if cached and (now - cached["timestamp"]) < _CACHE_TTL:
        return cached["tree"]

    tree = _build_tree(root)
    _tree_cache[root] = {"tree": tree, "timestamp": now}
    logger.info("Tree cache rebuilt for %s (%d date dirs)", root, len(tree))
    return tree


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/tree")
async def browse_tree(
    root: str = Query(str(DATASET_ROOT)),
    refresh: bool = Query(False, description="Force cache refresh"),
):
    """Return the directory tree: date → capture → part → segment → cameras."""
    if refresh:
        _tree_cache.pop(root, None)
        # Also clear image caches for this root
        keys_to_del = [k for k in _images_cache if k[0] == root]
        for k in keys_to_del:
            del _images_cache[k]

    root_path = _dataset_root(root)
    root = str(root_path)
    if not root_path.exists():
        raise HTTPException(status_code=404, detail=f"Root not found: {root}")

    try:
        tree = await asyncio.to_thread(_get_cached_tree, root)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")

    return {"root": root, "tree": tree}


@router.get("/images")
def browse_images(
    root: str = Query(str(DATASET_ROOT)),
    path: str = Query(..., description="date/capture/part/segment/cam_key"),
):
    """List image filenames in a specific segment + camera."""
    root_path = _dataset_root(root)
    parts = path.split("/")
    if len(parts) < 5:
        raise HTTPException(status_code=400, detail="Path: date/capture/part/segment/cam_key")

    cam_key = parts[-1]
    cam_dir = _resolve_cam_dir(cam_key)

    seg_path = _safe_join(root_path, *parts[:-1])
    images_dir = seg_path / "images" / cam_dir

    if not images_dir.exists():
        raise HTTPException(status_code=404, detail=f"Dir not found: {images_dir}")

    cache_key = (root, path)
    now = time.time()
    cached = _images_cache.get(cache_key)
    if cached and (now - cached["timestamp"]) < _CACHE_TTL:
        return cached["data"]

    image_files = sorted([
        f.name for f in os.scandir(images_dir)
        if f.is_file() and f.name.split('.')[-1].lower() in ('jpg', 'jpeg', 'png', 'bmp')
    ])

    data = {
        "path": path,
        "camera": cam_key,
        "cam_dir": cam_dir,
        "image_count": len(image_files),
        "images": image_files,
    }
    _images_cache[cache_key] = {"data": data, "timestamp": now}
    return data


@router.get("/image")
def serve_image(
    root: str = Query(str(DATASET_ROOT)),
    path: str = Query(..., description="date/.../segment/images/cam_dir/filename"),
    thumb: bool = Query(False),
):
    """Serve a single image file (or thumbnail)."""
    root_path = _dataset_root(root)
    file_path = _safe_join(root_path, path)

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Not found: {path}")

    if thumb:
        import io, cv2
        img = cv2.imread(str(file_path))
        if img is None:
            raise HTTPException(status_code=500, detail="Failed to read image")
        h, w = img.shape[:2]
        scale = min(320 / w, 240 / h)
        thumb_img = cv2.resize(
            img, (max(1, int(w * scale)), max(1, int(h * scale))),
            interpolation=cv2.INTER_AREA,
        )
        _, buf = cv2.imencode('.jpg', thumb_img)
        return Response(content=buf.tobytes(), media_type="image/jpeg")

    suffix = file_path.suffix.lower()
    media_map = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                 '.png': 'image/png', '.bmp': 'image/bmp'}
    return FileResponse(
        file_path,
        media_type=media_map.get(suffix, 'application/octet-stream'),
        headers={"Cache-Control": "public, max-age=86400"},
    )


# ── Timestamp helpers ────────────────────────────────────────────────────────

_TS_RE = re.compile(r"_t(\d+\.\d+)")


def _parse_ts(filename: str) -> float | None:
    """Extract timestamp from image filename. e.g. _t000000.060 → 0.06"""
    m = _TS_RE.search(filename)
    if m:
        return float(m.group(1))
    return None


@router.get("/match")
def match_ir_to_visible(
    root: str = Query(str(DATASET_ROOT)),
    seg_path: str = Query(..., description="date/.../segment"),
    ir_file: str = Query(..., description="IR image filename"),
):
    """Find the closest 037/038 images for a given IR image by timestamp."""
    root_path = _dataset_root(root)
    ir_ts = _parse_ts(ir_file)
    if ir_ts is None:
        raise HTTPException(status_code=400, detail=f"Cannot parse timestamp from: {ir_file}")

    result: dict = {"ir": {"file": ir_file, "ts": ir_ts}, "037": None, "038": None, "seg_path": seg_path}

    for cam_key, cam_dir in [("037", CAMERA_DIRS["037"]), ("038", CAMERA_DIRS["038"])]:
        cam_path = _safe_join(root_path, seg_path, "images", cam_dir)
        if not cam_path.exists():
            continue

        # Scan files in this camera dir, find closest by timestamp
        best_file = None
        best_diff = float("inf")
        try:
            for entry in os.scandir(cam_path):
                if not entry.is_file():
                    continue
                suffix = entry.name.rsplit('.', 1)[-1].lower() if '.' in entry.name else ''
                if suffix not in ('jpg', 'jpeg', 'png', 'bmp'):
                    continue
                ts = _parse_ts(entry.name)
                if ts is None:
                    continue
                diff = abs(ts - ir_ts)
                if diff < best_diff:
                    best_diff = diff
                    best_file = entry.name
        except OSError:
            pass

        if best_file:
            result[cam_key] = {"file": best_file, "ts": _parse_ts(best_file), "diff": best_diff}

    return result


@router.get("/csv")
def get_segment_csv(
    root: str = Query(str(DATASET_ROOT)),
    seg_path: str = Query(..., description="date/.../segment"),
):
    """Get the timestamp match CSV for a segment."""
    # Read from local writable storage
    csv_dir = SESSIONS_DIR / "triple_csvs" / _safe_session_path(seg_path)
    csv_file = csv_dir / "triple_ts.csv"
    if not csv_file.exists():
        return {"seg_path": seg_path, "rows": [], "count": 0}

    rows = []
    try:
        with open(csv_file, "r", newline="") as f:
            for r in csv_mod.DictReader(f):
                rows.append(r)
    except Exception:
        pass
    return {"seg_path": seg_path, "rows": rows, "count": len(rows), "csv_path": str(csv_file)}


class SaveCSVRequest:
    """Pydantic model for CSV save."""
    def __init__(self, seg_path: str, ir_file: str, ir_ts: float,
                 f037: str, ts037: float, f038: str, ts038: float, root: str = ""):
        self.seg_path = seg_path
        self.ir_file = ir_file
        self.ir_ts = ir_ts
        self.f037 = f037
        self.ts037 = ts037
        self.f038 = f038
        self.ts038 = ts038
        self.root = root


@router.post("/csv")
def save_segment_csv(req: dict):
    """Save a timestamp triple row to the segment's CSV file."""
    root = req.get("root", str(DATASET_ROOT))
    _dataset_root(root)
    seg_path = req["seg_path"]
    # Write to local writable storage, mirroring segment structure
    csv_dir = SESSIONS_DIR / "triple_csvs" / _safe_session_path(seg_path)
    csv_dir.mkdir(parents=True, exist_ok=True)
    csv_file = csv_dir / "triple_ts.csv"

    row = {
        "ir_file": req["ir_file"],
        "ir_ts": req["ir_ts"],
        "file_037": req["f037"],
        "ts_037": req["ts037"],
        "file_038": req["f038"],
        "ts_038": req["ts038"],
    }

    file_exists = csv_file.exists()
    try:
        with open(csv_file, "a", newline="") as f:
            writer = csv_mod.DictWriter(f, fieldnames=list(row.keys()))
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"success": True, "csv_path": str(csv_file), "row": row}


# ── Annotation endpoints ─────────────────────────────────────────────────────

ANNOTATIONS_DIR = SESSIONS_DIR / "annotations"


def _annotations_subdir(seg_path: str, ir_ts: float) -> Path:
    """Get the annotation save directory for a triple: seg_path/ir_ts_<ts>/"""
    ts_str = f"{ir_ts:.3f}".replace('.', '_')
    return ANNOTATIONS_DIR / _safe_session_path(seg_path) / f"ir_ts_{ts_str}"


class AnnotationData(BaseModel):
    seg_path: str
    ir_ts: float
    boxes: dict  # {"037": [...], "038": [...], "IR": [...]}


@router.get("/annotations")
def load_annotations(
    seg_path: str = Query(..., description="Segment path"),
    ir_ts: float = Query(..., description="IR timestamp"),
):
    """Load box annotations for 037, 038, IR for a specific IR timestamp."""
    subdir = _annotations_subdir(seg_path, ir_ts)
    result = {"seg_path": seg_path, "ir_ts": ir_ts, "boxes": {}}

    for cam_key in ["037", "038", "IR"]:
        ts_str = f"{ir_ts:.3f}".replace('.', '_')
        fname = f"{cam_key}_ts_{ts_str}.json"
        fpath = subdir / fname
        if fpath.exists():
            try:
                result["boxes"][cam_key] = json.loads(fpath.read_text())
            except Exception:
                result["boxes"][cam_key] = []
        else:
            result["boxes"][cam_key] = []

    result["has_annotations"] = any(v for v in result["boxes"].values())
    return result


@router.post("/annotations")
def save_annotations(req: AnnotationData):
    """Save box annotations for a triple."""
    subdir = _annotations_subdir(req.seg_path, req.ir_ts)
    subdir.mkdir(parents=True, exist_ok=True)
    saved = []
    for cam_key, box_list in req.boxes.items():
        ts_str = f"{req.ir_ts:.3f}".replace('.', '_')
        fname = f"{cam_key}_ts_{ts_str}.json"
        fpath = subdir / fname
        fpath.write_text(json.dumps(box_list, ensure_ascii=False, indent=2))
        saved.append(str(fpath))
    return {"success": True, "files": saved, "dir": str(subdir)}


# ── SAM3 dual-visible-camera auto annotation ────────────────────────────────

SAM3_CLASS_SPECS = (
    {
        "class_id": "power_transmission_tower",
        "label": "Power tower",
        "label_zh": "高压线塔",
        "prompt": "power line tower",
        "threshold": 0.30,
    },
    {
        "class_id": "wind_turbine",
        "label": "Wind turbine",
        "label_zh": "风力发电机",
        "prompt": "wind turbine with blades",
        "threshold": 0.35,
    },
    {
        "class_id": "building",
        "label": "Building",
        "label_zh": "楼房",
        "prompt": "multi-story residential or office building",
        "threshold": 0.45,
    },
    {
        "class_id": "chimney",
        "label": "Chimney",
        "label_zh": "烟囱",
        "prompt": "industrial chimney or smokestack",
        "threshold": 0.35,
    },
    {
        "class_id": "bridge",
        "label": "Bridge",
        "label_zh": "大桥",
        "prompt": "large highway or railway bridge",
        "threshold": 0.40,
    },
    {
        "class_id": "television_tower",
        "label": "Television tower",
        "label_zh": "电视塔",
        "prompt": "television broadcast tower",
        "threshold": 0.30,
    },
    {
        "class_id": "signal_tower",
        "label": "Signal tower",
        "label_zh": "信号塔",
        "prompt": "telecommunication cellular signal tower",
        "threshold": 0.30,
    },
)
SAM3_CLASS_BY_ID = {spec["class_id"]: spec for spec in SAM3_CLASS_SPECS}

_sam3_model = None
_sam3_processor = None
_sam3_lock = threading.Lock()
_da3_model = None
_da3_lock = threading.Lock()
_gpu_inference_lock = threading.Lock()

DA3_TIED_AUX_STATE_ALIASES = frozenset({
    "model.head.scratch.output_conv2_aux.1.2.weight",
    "model.head.scratch.output_conv2_aux.1.2.bias",
    "model.head.scratch.output_conv2_aux.2.2.weight",
    "model.head.scratch.output_conv2_aux.2.2.bias",
    "model.head.scratch.output_conv2_aux.3.2.weight",
    "model.head.scratch.output_conv2_aux.3.2.bias",
})


def _get_sam3():
    """Lazy-load SAM3 model (singleton)."""
    global _sam3_model, _sam3_processor
    if _sam3_model is not None:
        return _sam3_model, _sam3_processor

    import torch
    torch.set_grad_enabled(False)

    # SAM3 source and checkpoint are local-only, configurable deployment assets.
    sam3_root = str(SAM3_SOURCE_ROOT.resolve())
    if sam3_root not in sys.path:
        sys.path.insert(0, sam3_root)

    # Patches for compatibility
    import sam3.model.act_ckpt_utils as _acu
    _acu.activation_ckpt_wrapper = lambda m: (lambda *a, **kw: m(*a, **kw))

    import sam3.perflib.fused as _fm

    def _safe_addmm(act, lin, x):
        y = lin(x)
        if act in (torch.nn.functional.gelu, torch.nn.GELU):
            return torch.nn.functional.gelu(y)
        if act in (torch.nn.functional.relu, torch.nn.ReLU):
            return torch.nn.functional.relu(y)
        return y

    _fm.addmm_act = _safe_addmm
    import sam3.model.vitdet as _vd
    _vd.addmm_act = _safe_addmm

    from sam3 import build_sam3_image_model
    from sam3.model.sam3_image_processor import Sam3Processor

    ckpt = str(SAM3_CHECKPOINT.resolve())
    if not SAM3_CHECKPOINT.exists():
        raise FileNotFoundError(f"SAM3 checkpoint not found: {SAM3_CHECKPOINT}")
    bpe = str(Path(sam3_root) / "sam3" / "assets" / "bpe_simple_vocab_16e6.txt.gz")

    logger.info("Loading SAM3 model (~12s)...")
    _sam3_model = build_sam3_image_model(
        checkpoint_path=ckpt, load_from_HF=False,
        bpe_path=bpe, device=MODEL_DEVICE, eval_mode=True,
    )
    _sam3_processor = Sam3Processor(_sam3_model)
    logger.info("SAM3 model ready")
    return _sam3_model, _sam3_processor


def _get_sam3_serialized():
    """Load SAM3 once; model construction is not safe to run concurrently."""
    with _sam3_lock:
        with _gpu_inference_lock:
            return _get_sam3()


def _get_da3():
    """Lazy-load the copied DA3-BASE model without any network access."""
    global _da3_model
    if _da3_model is not None:
        return _da3_model

    source_dir = DA3_SOURCE_ROOT / "src"
    config_file = DA3_ROOT / "config.json"
    checkpoint_file = DA3_ROOT / "model.safetensors"
    if not source_dir.is_dir():
        raise FileNotFoundError(f"DA3 inference source not found: {source_dir}")
    if not config_file.is_file():
        raise FileNotFoundError(f"DA3 config not found: {config_file}")
    if not checkpoint_file.is_file():
        raise FileNotFoundError(f"DA3 checkpoint not found: {checkpoint_file}")

    source_path = str(source_dir.resolve())
    if source_path not in sys.path:
        sys.path.insert(0, source_path)

    # Report every required inference dependency in one response.  Export,
    # benchmark and visualization-only packages are deliberately excluded.
    import importlib

    dependency_checks = {
        "torch": lambda: importlib.import_module("torch"),
        "torchvision": lambda: importlib.import_module("torchvision"),
        "numpy": lambda: importlib.import_module("numpy"),
        "Pillow": lambda: importlib.import_module("PIL.Image"),
        "opencv-python": lambda: importlib.import_module("cv2"),
        "einops": lambda: (
            getattr(importlib.import_module("einops"), "rearrange"),
            getattr(importlib.import_module("einops"), "repeat"),
            getattr(importlib.import_module("einops"), "einsum"),
        ),
        "safetensors": lambda: importlib.import_module("safetensors.torch"),
    }
    dependency_errors = []
    for dependency, check in dependency_checks.items():
        try:
            check()
        except Exception as exc:
            dependency_errors.append(f"{dependency}: {exc}")
    if dependency_errors:
        raise RuntimeError(
            "DA3 required dependency check failed: " + "; ".join(dependency_errors)
        )

    # The deployment is intentionally offline.  These also prevent the model
    # loader from silently trying Hugging Face when a local asset is missing.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

    import torch
    from depth_anything_3.api import DepthAnything3
    from safetensors.torch import load_file as load_safetensors

    torch.set_grad_enabled(False)
    logger.info("Loading DA3-BASE from %s", DA3_ROOT)
    model_descriptor = json.loads(config_file.read_text(encoding="utf-8"))
    da3_model = DepthAnything3(
        model_name=model_descriptor["model_name"],
        config=model_descriptor["config"],
    )
    state_dict = load_safetensors(str(checkpoint_file), device="cpu")
    aux_projections = da3_model.model.head.scratch.output_conv2_aux
    tied_layer_norm_weights = {id(block[2].weight) for block in aux_projections}
    tied_layer_norm_biases = {id(block[2].bias) for block in aux_projections}
    if len(tied_layer_norm_weights) != 1 or len(tied_layer_norm_biases) != 1:
        raise RuntimeError(
            "DA3 source/checkpoint mismatch: expected tied auxiliary LayerNorm parameters"
        )
    load_result = da3_model.load_state_dict(state_dict, strict=False)
    missing_keys = set(load_result.missing_keys)
    unexpected_keys = set(load_result.unexpected_keys)
    unsupported_missing = missing_keys - DA3_TIED_AUX_STATE_ALIASES
    if unsupported_missing or unexpected_keys:
        raise RuntimeError(
            "DA3 source/checkpoint mismatch: unsupported missing keys="
            f"{sorted(unsupported_missing)}, unexpected keys={sorted(unexpected_keys)}"
        )
    if missing_keys:
        logger.info(
            "DA3 accepted %d tied LayerNorm state aliases omitted by safetensors",
            len(missing_keys),
        )
    del state_dict
    da3_model = da3_model.to(DA3_DEVICE).eval()
    # Publish the singleton only after construction, strict weight loading and
    # device transfer have all succeeded.  Failed attempts remain retryable.
    _da3_model = da3_model
    logger.info("DA3-BASE ready on %s", DA3_DEVICE)
    return _da3_model


def _get_da3_serialized():
    """Load DA3 once; model construction is serialized for GPU safety."""
    with _da3_lock:
        with _gpu_inference_lock:
            return _get_da3()


def _resize_float_map(values, width: int, height: int):
    """Resize a DA3 float map to the original image pixel grid."""
    import numpy as np
    from PIL import Image

    values = np.asarray(values, dtype=np.float32)
    if values.shape == (height, width):
        return values
    resampling = getattr(Image, "Resampling", Image).BILINEAR
    return np.asarray(
        Image.fromarray(values, mode="F").resize((width, height), resampling),
        dtype=np.float32,
    )


def _predict_da3_pair(model, pil_images: list) -> tuple[list, list, float]:
    """Infer relative depth jointly for the two synchronized visible images."""
    import numpy as np

    if not pil_images:
        return [], [], 0.0
    with _da3_lock:
        with _gpu_inference_lock:
            started = time.time()
            prediction = model.inference(
                pil_images,
                process_res=DA3_PROCESS_RES,
                process_res_method="upper_bound_resize",
                export_dir=None,
            )
        raw_depths = np.asarray(prediction.depth)
        raw_confidences = (
            np.asarray(prediction.conf) if prediction.conf is not None else None
        )
        depths = []
        confidences = []
        for index, image in enumerate(pil_images):
            depths.append(_resize_float_map(raw_depths[index], image.width, image.height))
            if raw_confidences is None:
                confidences.append(None)
            else:
                confidences.append(
                    _resize_float_map(
                        raw_confidences[index], image.width, image.height
                    )
                )
        return depths, confidences, time.time() - started


def _finite_percentile_range(maps: list, *, positive: bool) -> tuple[float, float]:
    import numpy as np

    samples = []
    for values in maps:
        if values is None:
            continue
        array = np.asarray(values)
        valid = np.isfinite(array)
        if positive:
            valid &= array > 0
        selected = array[valid]
        if selected.size:
            # Bound memory while retaining a deterministic, uniform sample.
            stride = max(1, selected.size // 250_000)
            samples.append(selected[::stride])
    if not samples:
        return 0.0, 1.0
    merged = np.concatenate(samples)
    low, high = np.percentile(merged, (2.0, 98.0))
    if not np.isfinite(low) or not np.isfinite(high) or high <= low:
        return float(low) if np.isfinite(low) else 0.0, (
            float(low) + 1.0 if np.isfinite(low) else 1.0
        )
    return float(low), float(high)


def _capture_dir_from_seg(seg_path: str) -> Path | None:
    """从 seg_path (如 4_29/.../segment_xxx) 提取 capture 目录."""
    parts = seg_path.replace("\\", "/").split("/")
    while parts and parts[-1].startswith("segment_"):
        parts.pop()
    if len(parts) >= 2:
        return DATASET_ROOT / parts[0] / parts[1]
    return None


def _attach_gps_metric_depth(
    detections_by_camera: dict[str, list[dict]],
    seg_path: str,
    image_files: dict[str, str] | None = None,
) -> None:
    """从 depth_labels/ 加载 GPS 雷达匹配的 metric 深度并注入到检测框.

    通过 camera stem（从 image_file 去掉 .jpg）直接查找 depth_labels 文件，
    再按 IoU 匹配框.
    """
    capture_dir = _capture_dir_from_seg(seg_path)
    if capture_dir is None:
        return

    depth_dir = capture_dir / "depth_labels"
    if not depth_dir.exists():
        return

    for camera, detections in detections_by_camera.items():
        if camera not in ("037", "038") or not detections:
            continue

        # 从 image_file 推断 camera_stem → depth_labels/{camera_stem}.json
        image_file = (image_files or {}).get(camera)
        depth_path: Path | None = None
        if image_file:
            cam_stem = Path(image_file).stem  # 去掉 .jpg
            candidate = depth_dir / f"{cam_stem}.json"
            if candidate.exists():
                depth_path = candidate

        if depth_path is None:
            continue

        try:
            depth_data = json.loads(depth_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        depth_boxes = depth_data.get("boxes", [])
        if not depth_boxes:
            continue

        matched_any = False
        for det in detections:
            if det.get("depth_m") is not None:
                continue  # 已有深度（如 DA3 metric），不覆盖
            det_box = {
                "x1": det["x1"], "y1": det["y1"],
                "x2": det["x2"], "y2": det["y2"],
            }
            best_iou = 0.0
            best_depth = None
            for db in depth_boxes:
                bbox = db.get("bbox_xyxy", [])
                if len(bbox) < 4:
                    continue
                db_box = {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]}
                ix1 = max(det_box["x1"], db_box["x1"])
                iy1 = max(det_box["y1"], db_box["y1"])
                ix2 = min(det_box["x2"], db_box["x2"])
                iy2 = min(det_box["y2"], db_box["y2"])
                inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                area_det = (det_box["x2"] - det_box["x1"]) * (det_box["y2"] - det_box["y1"])
                area_db = (db_box["x2"] - db_box["x1"]) * (db_box["y2"] - db_box["y1"])
                union = area_det + area_db - inter
                iou = inter / union if union > 0 else 0.0
                if iou > best_iou and iou >= 0.3:
                    best_iou = iou
                    best_depth = db

            if best_depth is not None:
                det["depth_m"] = best_depth["depth_m"]
                det["depth_method"] = best_depth.get("method", "gps_ray_clustered")
                det["depth_confidence"] = min(1.0, best_depth.get("depth_cluster_points", 0) / 100.0)
                det["depth_support_points"] = best_depth.get("depth_cluster_points", 0)
                matched_any = True

        if matched_any:
            logger.debug(
                "GPS depth: attached for %s camera=%s (%d/%d boxes matched)",
                depth_path.stem, camera,
                sum(1 for d in detections if d.get("depth_m") is not None),
                len(detections),
            )


def _attach_bin_metric_depth_in_detect(
    detections_by_camera: dict[str, list[dict]],
    seg_path: str,
    image_files: dict[str, str],
    root_path: Path,
) -> None:
    """检测阶段：为仍无 metric 深度的 SAM3 框注入 BIN 深度."""
    import csv as _csv
    capture_dir = _capture_dir_from_seg(seg_path)
    if capture_dir is None:
        logger.warning("BIN detect: capture_dir None from %s", seg_path)
        return

    try:
        from src.io.adapters.lh_adapter import load_capture_bin_detection_map
        from src.fusion.bin_detection_projection import sample_bin_detection_map
    except ImportError as e:
        logger.warning("BIN detect: import failed: %s", e)
        return
    detection_map = load_capture_bin_detection_map(capture_dir)
    if not detection_map:
        logger.warning("BIN detect: no detection_map for %s", capture_dir)
        return
    samples = sample_bin_detection_map(detection_map)
    if len(samples) == 0:
        return

    _FX = CAMERA_INTRINSICS["037"]["fx"]; _CX = CAMERA_INTRINSICS["037"]["cx"]
    _W = 1920; _HDG_OFF = -90.0
    _MIN_D = 400.0; _MAX_D = 4000.0
    _KIND_MAP = [
        (("tower", "power"),      {3.0, 2.0}),
        (("turbine",),             {2.0}),
        (("chimney", "smokestack"), {2.0}),
        (("building",),            {1.0, 2.0}),
        (("bridge",),              {1.0, 2.0}),
        (("signal", "television"), {2.0, 3.0}),
    ]

    lat_a = samples[:, 0]; lon_a = samples[:, 1]
    kinds_a = samples[:, 4].astype(np.float64)

    # 用任一相机的时间戳插值位姿
    seg_dir = DATASET_ROOT / seg_path if (DATASET_ROOT / seg_path).name.startswith("segment_") else None
    if seg_dir is None:
        parts = seg_path.split("/"); cand = DATASET_ROOT
        for pt in parts:
            cand = cand / pt
            if cand.name.startswith("segment_") and cand.exists():
                seg_dir = cand; break
    if seg_dir is None:
        logger.warning("BIN detect: seg_dir not found from %s", seg_path)
        return
    nav_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
    if not nav_csv.exists():
        logger.warning("BIN detect: nav100 not found at %s", nav_csv)
        return
    with open(nav_csv, newline="", encoding="utf-8") as fh:
        nav_rows = list(_csv.DictReader(fh))
    if not nav_rows:
        return
    t_arr = np.array([float(r["relative_time_sec"]) for r in nav_rows])
    lat_arr = np.array([float(r["latitude"]) for r in nav_rows])
    lon_arr = np.array([float(r["longitude"]) for r in nav_rows])
    hdg_arr = np.array([float(r.get("true_heading_deg", 0.0)) for r in nav_rows])

    for camera, image_file in image_files.items():
        detections = detections_by_camera.get(camera, [])
        if not detections:
            continue
        image_width = _W
        # 从 image_file 解析时间戳
        tm = re.search(r"_t(\d+\.\d+)", image_file)
        if not tm:
            continue
        t_rel = float(tm.group(1))
        i = int(np.searchsorted(t_arr, t_rel))
        i = max(1, min(i, len(t_arr) - 1))
        t0, t1 = float(t_arr[i - 1]), float(t_arr[i])
        alpha = (t_rel - t0) / (t1 - t0) if (t1 - t0) > 1e-9 else 0.0
        lat_v = float(lat_arr[i - 1] + alpha * (lat_arr[i] - lat_arr[i - 1]))
        lon_v = float(lon_arr[i - 1] + alpha * (lon_arr[i] - lon_arr[i - 1]))
        h0 = float(hdg_arr[i - 1]); h1 = float(hdg_arr[i])
        dh = (h1 - h0 + 180.0) % 360.0 - 180.0
        hdg_v = (h0 + alpha * dh) % 360.0

        # BIN 投影到 1D 像素线
        east = (lon_a - lon_v) * math.pi / 180.0 * 6378137.0 * math.cos(math.radians(lat_v))
        north = (lat_a - lat_v) * math.pi / 180.0 * 6356752.3
        hdg = math.radians(hdg_v + _HDG_OFF)
        cos_h, sin_h = math.cos(hdg), math.sin(hdg)
        right = east * cos_h - north * sin_h
        forward = east * sin_h + north * cos_h
        dist = np.hypot(right, forward)
        valid = (forward > 0.1) & (dist >= _MIN_D) & (dist <= _MAX_D)
        if not valid.any():
            logger.warning("BIN detect: no valid pts for %s (need forward>0.1, dist [%d,%d])",
                           camera, _MIN_D, _MAX_D)
            continue
        logger.debug("BIN detect: %d valid radar pts for %s", int(valid.sum()), camera)
        pixel_x = _FX * right[valid] / forward[valid] + _CX
        pixel_dist = dist[valid]
        pixel_kinds = kinds_a[valid]
        in_img = (pixel_x >= 0) & (pixel_x < _W)
        if not in_img.any():
            continue
        px = pixel_x[in_img]; pd = pixel_dist[in_img]; pk = pixel_kinds[in_img]

        for det in detections:
            if det.get("depth_m") is not None:
                continue
            label_lower = det.get("class_id", "")
            acceptable: set[float] = set()
            for keywords, ks in _KIND_MAP:
                if any(kw in label_lower.lower() for kw in keywords):
                    acceptable.update(ks)
            if not acceptable:
                acceptable = {1.0, 2.0, 3.0}
            x0, x1 = det["x1"], det["x2"]
            semantic = np.isin(pk, list(acceptable))
            mask = (px >= x0) & (px <= x1) & semantic
            if not mask.any():
                continue
            values = pd[mask]
            depth = float(np.median(values))
            spread = float(np.percentile(values, 75) - np.percentile(values, 25))
            conf = max(0.30, min(0.90, 1.0 - spread / max(depth, 1.0)))
            det["depth_m"] = round(depth, 1)
            det["depth_method"] = "bin_semantic_detect"
            det["depth_confidence"] = round(conf, 3)
            det["depth_support_points"] = int(mask.sum())
            logger.debug("BIN detect: %s → %sm (%d pts)", label_lower, round(depth,1), int(mask.sum()))

    # 统计每相机匹配数
    for cam, dets in detections_by_camera.items():
        n_match = sum(1 for d in dets if d.get("depth_method") == "bin_semantic_detect")
        if n_match:
            logger.info("BIN detect: %s - %d/%d boxes got metric depth",
                        cam, n_match, len(dets))


def _inject_bin_depth_on_save(
    document: dict,
    capture_dir: Path,
    image_width: int,
    vehicle_lat: float,
    vehicle_lon: float,
    vehicle_alt: float,
    vehicle_hdg: float,
) -> bool:
    """BIN 语义匹配在线注入绝对深度.

    从 BIN 雷达检测地图匹配语义目标到 2D 框，注入 depth_m。
    在 .mat 通用点云之前调用，BIN 匹配成功的不再走 .mat 路径。
    返回 True 表示至少有一个框获取到了 BIN 深度。
    """
    try:
        from src.io.adapters.lh_adapter import load_capture_bin_detection_map
        from src.fusion.bin_detection_projection import sample_bin_detection_map
    except ImportError:
        return False

    detection_map = load_capture_bin_detection_map(capture_dir)
    if not detection_map:
        return False

    samples = sample_bin_detection_map(detection_map)
    if len(samples) == 0:
        return False

    _FX = CAMERA_INTRINSICS["037"]["fx"]
    _FY = CAMERA_INTRINSICS["037"]["fy"]
    _CX = CAMERA_INTRINSICS["037"]["cx"]
    _CY = CAMERA_INTRINSICS["037"]["cy"]
    _W = 1920
    _H = 1200
    _HDG_OFF = -90.0
    _MIN_D = 400.0
    _MAX_D = 4000.0

    lat = samples[:, 0]
    lon = samples[:, 1]
    alt = samples[:, 2]
    kinds = samples[:, 4].astype(np.float64)

    east = (
        (lon - vehicle_lon)
        * math.pi / 180.0 * 6378137.0
        * math.cos(math.radians(vehicle_lat))
    )
    north = (lat - vehicle_lat) * math.pi / 180.0 * 6356752.3
    hdg = math.radians(vehicle_hdg + _HDG_OFF)
    cos_h, sin_h = math.cos(hdg), math.sin(hdg)
    right = east * cos_h - north * sin_h
    forward = east * sin_h + north * cos_h
    up = alt - vehicle_alt
    dist = np.hypot(right, forward)

    valid = (
        (forward > 0.1)
        & (dist >= _MIN_D) & (dist <= _MAX_D)
    )
    if not valid.any():
        return False

    pixel_x = _FX * right[valid] / forward[valid] + _CX
    pixel_dist = dist[valid]
    pixel_kinds = kinds[valid]
    # Only X-axis hard filtering (pitch-agnostic 1D projection, same as
    # export_labelme_depth.py).  Y-offset is used as soft weight below.
    pixel_y_norm = (_CY - _FY * up[valid] / forward[valid]) / _H * 2.0 - 1.0
    in_img = (pixel_x >= 0) & (pixel_x < _W)
    if not in_img.any():
        return False

    px = pixel_x[in_img]
    pd = pixel_dist[in_img]
    pk = pixel_kinds[in_img]
    # Vertical deviation from screen centre, used as spatial quality weight.
    # 0 = dead centre, 1 = one screen height off-screen.
    py_dev = pixel_y_norm[in_img]

    # Label → acceptable BIN kinds
    _KIND_MAP = [
        (("tower", "power"),      {3.0, 2.0}),
        (("turbine",),             {2.0}),
        (("chimney", "smokestack"), {2.0}),
        (("building",),            {1.0, 2.0}),
        (("bridge",),              {1.0, 2.0}),
        (("signal", "television"), {2.0, 3.0}),
    ]

    matched_any = False
    for shape in document.get("shapes", []):
        if shape.get("attributes", {}).get("depth_m") is not None:
            continue
        pts = shape.get("points", [])
        if len(pts) < 2:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, y0, x1, y1 = min(xs), min(ys), max(xs), max(ys)

        label_lower = " ".join(str(shape.get("label", "")).lower().split())
        acceptable: set[float] = set()
        for keywords, ks in _KIND_MAP:
            if any(kw in label_lower for kw in keywords):
                acceptable.update(ks)
        if not acceptable:
            acceptable = {1.0, 2.0, 3.0}

        semantic = np.isin(pk, list(acceptable))
        # X-axis only hard filter (no reliable pitch for Y).
        mask = (px >= x0) & (px <= x1) & semantic
        if not mask.any():
            continue

        values = pd[mask]
        depth = float(np.median(values))
        spread = float(np.percentile(values, 75) - np.percentile(values, 25))
        # Y-deviation soft weight: dead centre = 1.0, off-screen → decays
        dev_w = max(0.3, 1.0 - abs(float(np.median(py_dev[mask]))))
        conf = max(0.30, min(0.90, 1.0 - spread / max(depth, 1.0))) * dev_w

        shape.setdefault("attributes", {})["depth_m"] = round(depth, 1)
        shape["attributes"]["depth_method"] = "bin_semantic_online"
        shape["attributes"]["depth_confidence"] = round(conf, 3)
        shape["attributes"]["depth_support_points"] = int(mask.sum())
        matched_any = True
        logger.debug(
            "BIN depth online: %s → %sm (pts=%d, kind=%s)",
            shape.get("label", "?"), round(depth, 1),
            int(mask.sum()),
            set(int(k) for k in pk[mask]),
        )

    return matched_any


def _inject_gps_depth_on_save(
    req: "UpdateFeatureAnnotationsRequest",
    document: dict,
    image_width: int,
) -> None:
    """保存标注时自动注入 GPS 雷达 metric 深度。

    流程:
      1. 找 capture 下的 depth_labels/{camera_stem}.json（深度缓存）
      2. 如果有 → IoU 匹配注入
      3. 如果无 → BIN 雷达语义匹配注入（优先于通用点云）
      4. BIN 未匹配的框 → 直接从 .mat 雷达点云实时计算
    """
    import csv as _csv
    import numpy as np

    capture_dir = _capture_dir_from_seg(req.seg_path)
    if capture_dir is None or not capture_dir.exists():
        logger.debug("GPS depth: capture_dir not found for %s", req.seg_path)
        return

    cam_stem = Path(req.image_file).stem
    depth_dir = capture_dir / "depth_labels"
    depth_path = depth_dir / f"{cam_stem}.json"

    # ── 尝试1: 从 depth_labels 缓存加载 ──
    depth_boxes = None
    if depth_path.exists():
        try:
            depth_data = json.loads(depth_path.read_text(encoding="utf-8"))
            depth_boxes = depth_data.get("boxes", [])
            logger.debug("GPS depth: loaded %d boxes from %s", len(depth_boxes or []), depth_path.name)
        except Exception:
            pass

    # ── 尝试2: 没有缓存，从 .mat 实时计算 ──
    if not depth_boxes:
        from src.io.adapters.lh_adapter import _load_mmwave_enu_pts, _find_radar_dir
        radar_dir = _find_radar_dir(capture_dir)
        if radar_dir is None:
            logger.debug("GPS depth: no radar dir for %s", capture_dir)
            return

        mat_files = sorted(radar_dir.glob("*.mat"))
        if not mat_files:
            return

        # 加载雷达点云
        chunks = []
        for mp in mat_files:
            try:
                pts, _, _ = _load_mmwave_enu_pts(mp)
                if len(pts):
                    chunks.append(pts[:, :4].astype(np.float32))
            except Exception:
                pass
        if not chunks:
            return
        gps_pts = np.concatenate(chunks, axis=0)
        if len(gps_pts) > 20000:
            idx = np.argpartition(gps_pts[:, 3], -20000)[-20000:]
            gps_pts = gps_pts[idx]

        # 找 segment 目录（seg_path 最后一段就是 segment_xxx）
        seg_candidate = DATASET_ROOT / req.seg_path
        if seg_candidate.exists() and seg_candidate.name.startswith("segment_"):
            seg_dir = seg_candidate
        else:
            parts = req.seg_path.split("/")
            cand = DATASET_ROOT
            seg_dir = None
            for pt in parts:
                cand = cand / pt
                if cand.name.startswith("segment_") and cand.exists():
                    seg_dir = cand
                    break
        if seg_dir is None:
            logger.debug("GPS depth: segment not found for %s", req.seg_path)
            return

        nav_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
        if not nav_csv.exists():
            logger.debug("GPS depth: nav100 not found at %s", nav_csv)
            return

        with open(nav_csv, newline="", encoding="utf-8") as fh:
            nav_rows = list(_csv.DictReader(fh))
        if not nav_rows:
            return

        t_arr = np.array([float(r["relative_time_sec"]) for r in nav_rows])
        lat_arr = np.array([float(r["latitude"]) for r in nav_rows])
        lon_arr = np.array([float(r["longitude"]) for r in nav_rows])
        alt_arr = np.array([float(r.get("altitude", 0.0)) for r in nav_rows])
        hdg_arr = np.array([float(r.get("true_heading_deg", 0.0)) for r in nav_rows])

        # 从 image_file 解析时间戳
        import re
        tm = re.search(r"_t(\d+\.\d+)", req.image_file)
        if not tm:
            return
        t_rel = float(tm.group(1))

        # 插值无人机位姿
        i = int(np.searchsorted(t_arr, t_rel))
        i = max(1, min(i, len(t_arr) - 1))
        t0, t1 = float(t_arr[i - 1]), float(t_arr[i])
        alpha = (t_rel - t0) / (t1 - t0) if (t1 - t0) > 1e-9 else 0.0
        lat_v = float(lat_arr[i - 1] + alpha * (lat_arr[i] - lat_arr[i - 1]))
        lon_v = float(lon_arr[i - 1] + alpha * (lon_arr[i] - lon_arr[i - 1]))
        h0 = float(hdg_arr[i - 1])
        h1 = float(hdg_arr[i])
        dh = (h1 - h0 + 180.0) % 360.0 - 180.0
        hdg_v = (h0 + alpha * dh) % 360.0
        alt_v = float(alt_arr[i - 1] + alpha * (alt_arr[i] - alt_arr[i - 1]))

        # ── BIN 语义匹配（优先于 .mat 通用点云） ──
        _inject_bin_depth_on_save(
            document, capture_dir, image_width,
            lat_v, lon_v, alt_v, hdg_v,
        )

        # 计算每个目标点相对无人机的位置
        _R_EARTH_EQ = 6378137.0
        _R_EARTH_POL = 6356752.0
        _CAMERA_HFOV_DEG = CAMERA_HFOV_DEG  # 8.78° from fx=12503.99 calibration
        _MIN_DEPTH_M = 400.0
        _MAX_DEPTH_M = 4000.0

        coslat_v = math.cos(math.radians(lat_v))
        dN = (gps_pts[:, 0].astype(np.float64) - lat_v) * (math.pi / 180.0) * _R_EARTH_POL
        dE = (gps_pts[:, 1].astype(np.float64) - lon_v) * coslat_v * (math.pi / 180.0) * _R_EARTH_EQ
        dist = np.sqrt(dN ** 2 + dE ** 2)
        target_az = np.degrees(np.arctan2(dE, dN))

        logger.debug(
            "GPS depth: %d radar pts, drone=(%.6f, %.6f) hdg=%.1f t=%.3f",
            len(gps_pts), lat_v, lon_v, hdg_v, t_rel,
        )

        matched_boxes = []
        for shape in document.get("shapes", []):
            if shape.get("attributes", {}).get("depth_m") is not None:
                continue
            pts = shape.get("points", [])
            if len(pts) < 2:
                continue
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            cx = (min(xs) + max(xs)) / 2.0
            box_az = (cx / image_width - 0.5) * _CAMERA_HFOV_DEG
            world_az = (hdg_v + box_az) % 360.0

            valid = (dist >= _MIN_DEPTH_M) & (dist < _MAX_DEPTH_M)
            if not valid.any():
                continue
            az_diff = (target_az[valid] - world_az + 180.0) % 360.0 - 180.0
            box_hw = max(0.45, 0.5 * (max(xs) - min(xs)) / image_width * _CAMERA_HFOV_DEG + 0.35)
            in_cone = np.abs(az_diff) <= box_hw
            if not in_cone.any():
                # 再试一次宽视角
                box_hw *= 2
                in_cone = np.abs(az_diff) <= box_hw
                if not in_cone.any():
                    continue

            # ── DBSCAN 聚类: 取最强信号簇的加权中值距离替代单点 ──
            cone_east = dE[valid][in_cone]
            cone_north = dN[valid][in_cone]
            cone_dist = dist[valid][in_cone]
            cone_db = gps_pts[valid, 3][in_cone]

            if len(cone_dist) < 2:
                # 单点回退
                dm = round(float(cone_dist[0]), 1)
                support_pts = 1
                spread_m = 0.0
            else:
                # DBSCAN 在小半径内在 BEV 方向聚类
                _EPS_CLUSTER_M = 30.0
                _MIN_CLUSTER_PTS = 2
                from sklearn.cluster import DBSCAN
                xy_local = np.column_stack([cone_east, cone_north])
                labels = DBSCAN(eps=_EPS_CLUSTER_M, min_samples=_MIN_CLUSTER_PTS).fit_predict(xy_local)
                best_power_idx = int(np.argmax(cone_db))
                best_cluster = labels[best_power_idx]

                if best_cluster < 0:
                    # 最强点是噪点 → 回退到单点
                    dm = round(float(cone_dist[best_power_idx]), 1)
                    support_pts = 1
                    spread_m = 0.0
                else:
                    cluster_mask = labels == best_cluster
                    depth_cluster = cone_dist[cluster_mask]
                    power_cluster = cone_db[cluster_mask]
                    support_pts = int(cluster_mask.sum())
                    # 功率加权中值距离
                    lin_weights = 10.0 ** (power_cluster / 10.0)
                    order = np.argsort(depth_cluster)
                    cum_w = np.cumsum(lin_weights[order])
                    median_idx = int(np.searchsorted(cum_w, cum_w[-1] * 0.5))
                    dm = round(float(depth_cluster[order[min(median_idx, len(order) - 1)]]), 1)
                    spread_m = round(float(
                        np.percentile(depth_cluster, 75) - np.percentile(depth_cluster, 25)
                    ), 1)

            shape["attributes"]["depth_m"] = dm
            shape["attributes"]["depth_method"] = "gps_ray_clustered"
            shape["attributes"]["depth_confidence"] = min(1.0, support_pts / 100.0)
            shape["attributes"]["depth_support_points"] = support_pts
            shape["attributes"]["depth_cluster_spread_m"] = spread_m
            logger.debug(
                "GPS depth real-time: %s → %sm (pts=%d, spread=%.1f)",
                shape.get("label", "?"), dm, support_pts, spread_m,
            )
            matched_boxes.append({
                "label": shape.get("label", ""),
                "bbox_xyxy": [min(xs), min(ys), max(xs), max(ys)],
                "depth_m": dm,
                "method": "gps_ray_clustered",
                "depth_cluster_points": support_pts,
            })

        # 生成 depth_labels 缓存
        if matched_boxes:
            depth_dir.mkdir(parents=True, exist_ok=True)
            depth_path.write_text(
                json.dumps({
                    "camera_name": req.image_file,
                    "method": "gps_ray_metric",
                    "boxes": matched_boxes,
                }, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        return

    # ── 从 depth_labels 缓存按 IoU 匹配注入 ──
    for shape in document.get("shapes", []):
        if shape.get("attributes", {}).get("depth_m") is not None:
            continue
        pts = shape.get("points", [])
        if len(pts) < 2:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        det_box = {"x1": min(xs), "y1": min(ys), "x2": max(xs), "y2": max(ys)}
        best_iou, best_depth = 0.0, None
        for db in depth_boxes:
            bbox = db.get("bbox_xyxy", [])
            if len(bbox) < 4:
                continue
            db_box = {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]}
            ix1 = max(det_box["x1"], db_box["x1"])
            iy1 = max(det_box["y1"], db_box["y1"])
            ix2 = min(det_box["x2"], db_box["x2"])
            iy2 = min(det_box["y2"], db_box["y2"])
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            area_det = (det_box["x2"] - det_box["x1"]) * (det_box["y2"] - det_box["y1"])
            area_db = (db_box["x2"] - db_box["x1"]) * (db_box["y2"] - db_box["y1"])
            union = area_det + area_db - inter
            iou = inter / union if union > 0 else 0.0
            if iou > best_iou and iou >= 0.3:
                best_iou, best_depth = iou, db
        if best_depth is not None:
            shape["attributes"]["depth_m"] = best_depth["depth_m"]
            shape["attributes"]["depth_method"] = best_depth.get("method", "gps_ray_clustered")
            shape["attributes"]["depth_confidence"] = min(1.0, best_depth.get("depth_cluster_points", 0) / 100.0)
            shape["attributes"]["depth_support_points"] = best_depth.get("depth_cluster_points", 0)
            logger.debug(
                "GPS depth cached: %s → %sm (IoU=%.2f)",
                req.image_file, best_depth["depth_m"], best_iou,
            )

    # ── 尝试3: 缓存匹配后仍有空深度的框 → BIN + .mat 实时回退 ──
    _inject_bin_and_mat_fallback(
        req, document, capture_dir, image_width,
    )


def _inject_bin_and_mat_fallback(
    req: "UpdateFeatureAnnotationsRequest",
    document: dict,
    capture_dir: Path,
    image_width: int,
) -> None:
    """缓存 IoU 匹配后仍为空的框 → BIN + .mat 实时计算."""
    import csv as _csv
    remaining = [s for s in document.get("shapes", [])
                 if s.get("attributes", {}).get("depth_m") is None
                 and len(s.get("points", [])) >= 2]
    logger.debug("BIN+MAT fallback: %d/%d shapes need depth",
                 len(remaining), len(document.get("shapes", [])))
    if not remaining:
        return

    # 找 segment 目录
    seg_candidate = DATASET_ROOT / req.seg_path
    if seg_candidate.exists() and seg_candidate.name.startswith("segment_"):
        seg_dir = seg_candidate
    else:
        parts = req.seg_path.split("/")
        cand = DATASET_ROOT
        seg_dir = None
        for pt in parts:
            cand = cand / pt
            if cand.name.startswith("segment_") and cand.exists():
                seg_dir = cand
                break
    if seg_dir is None:
        logger.debug("BIN+MAT fallback: seg_dir not found from %s", req.seg_path)
        return

    nav_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
    if not nav_csv.exists():
        logger.debug("BIN+MAT fallback: nav100 not found at %s", nav_csv)
        return
    with open(nav_csv, newline="", encoding="utf-8") as fh:
        nav_rows = list(_csv.DictReader(fh))
    if not nav_rows:
        logger.debug("BIN+MAT fallback: nav100 empty")
        return
    t_arr = np.array([float(r["relative_time_sec"]) for r in nav_rows])
    lat_arr = np.array([float(r["latitude"]) for r in nav_rows])
    lon_arr = np.array([float(r["longitude"]) for r in nav_rows])
    alt_arr = np.array([float(r.get("altitude", 0.0)) for r in nav_rows])
    hdg_arr = np.array([float(r.get("true_heading_deg", 0.0)) for r in nav_rows])

    tm = re.search(r"_t(\d+\.\d+)", req.image_file)
    if not tm:
        logger.debug("BIN+MAT fallback: no timestamp in %s", req.image_file)
        return
    t_rel = float(tm.group(1))
    i = int(np.searchsorted(t_arr, t_rel))
    i = max(1, min(i, len(t_arr) - 1))
    t0, t1 = float(t_arr[i - 1]), float(t_arr[i])
    alpha = (t_rel - t0) / (t1 - t0) if (t1 - t0) > 1e-9 else 0.0
    lat_v = float(lat_arr[i - 1] + alpha * (lat_arr[i] - lat_arr[i - 1]))
    lon_v = float(lon_arr[i - 1] + alpha * (lon_arr[i] - lon_arr[i - 1]))
    h0 = float(hdg_arr[i - 1]); h1 = float(hdg_arr[i])
    dh = (h1 - h0 + 180.0) % 360.0 - 180.0
    hdg_v = (h0 + alpha * dh) % 360.0
    alt_v = float(alt_arr[i - 1] + alpha * (alt_arr[i] - alt_arr[i - 1]))
    logger.debug("BIN+MAT fallback: pose (%.6f, %.6f) hdg=%.1f alt=%.0f t=%.3f",
                 lat_v, lon_v, hdg_v, alt_v, t_rel)

    # ── BIN 语义匹配 ──
    bin_ok = _inject_bin_depth_on_save(document, capture_dir, image_width,
                               lat_v, lon_v, alt_v, hdg_v)
    logger.debug("BIN+MAT fallback: BIN returned %s", bin_ok)

    # ── .mat 实时 GPS 射线（BIN 未匹配的框补漏） ──
    still_null = [s for s in document.get("shapes", [])
                  if s.get("attributes", {}).get("depth_m") is None
                  and len(s.get("points", [])) >= 2]
    if not still_null:
        logger.debug("BIN+MAT fallback: all shapes got depth from BIN")
        return

    from src.io.adapters.lh_adapter import _load_mmwave_enu_pts, _find_radar_dir
    radar_dir = _find_radar_dir(capture_dir)
    if radar_dir is None:
        logger.debug("BIN+MAT fallback: no radar dir for %s", capture_dir)
        return
    mat_files = sorted(radar_dir.glob("*.mat"))
    if not mat_files:
        logger.debug("BIN+MAT fallback: no .mat files in %s", radar_dir)
        return
    logger.debug("BIN+MAT fallback: %d .mat files, loading radar pts...", len(mat_files))
    chunks = []
    for mp in mat_files:
        try:
            pts, _, _ = _load_mmwave_enu_pts(mp)
            if len(pts):
                chunks.append(pts[:, :4].astype(np.float32))
        except Exception:
            pass
    if not chunks:
        logger.debug("BIN+MAT fallback: no CFAR points from any .mat")
        return
    gps_pts = np.concatenate(chunks, axis=0)
    logger.debug("BIN+MAT fallback: %d total radar pts", len(gps_pts))
    if len(gps_pts) > 20000:
        idx = np.argpartition(gps_pts[:, 3], -20000)[-20000:]
        gps_pts = gps_pts[idx]
    _R_EARTH_EQ = 6378137.0
    _R_EARTH_POL = 6356752.0
    _CAMERA_HFOV_DEG = CAMERA_HFOV_DEG
    _MIN_D = 400.0
    _MAX_D = 4000.0

    coslat_v = math.cos(math.radians(lat_v))
    dN = (gps_pts[:, 0].astype(np.float64) - lat_v) * (math.pi / 180.0) * _R_EARTH_POL
    dE = (gps_pts[:, 1].astype(np.float64) - lon_v) * coslat_v * (math.pi / 180.0) * _R_EARTH_EQ
    dist = np.sqrt(dN ** 2 + dE ** 2)
    target_az = np.degrees(np.arctan2(dE, dN))

    logger.debug("BIN+MAT: %d radar pts, matching %d boxes",
                 len(gps_pts), len(still_null))
    matched_count = 0
    for shape in still_null:
        pts = shape.get("points", [])
        if len(pts) < 2:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        cx = (min(xs) + max(xs)) / 2.0
        box_az = (cx / image_width - 0.5) * _CAMERA_HFOV_DEG
        world_az = (hdg_v + box_az) % 360.0

        valid = (dist >= _MIN_D) & (dist < _MAX_D)
        if not valid.any():
            logger.debug("BIN+MAT: %s no radar in range", shape.get("label","?"))
            continue
        az_diff = (target_az[valid] - world_az + 180.0) % 360.0 - 180.0
        box_hw = max(0.45, 0.5 * (max(xs) - min(xs)) / image_width * _CAMERA_HFOV_DEG + 0.35)
        in_cone = np.abs(az_diff) <= box_hw
        if not in_cone.any():
            box_hw *= 2
            in_cone = np.abs(az_diff) <= box_hw
            if not in_cone.any():
                logger.debug("BIN+MAT: %s no cone match az=%.1f hw=%.2f",
                             shape.get("label","?"), box_az, box_hw)
                continue

        vd = dist[valid][in_cone]
        vs = gps_pts[valid, 3][in_cone]
        bi = np.argmax(vs)
        dm = round(float(vd[bi]), 1)
        shape["attributes"]["depth_m"] = dm
        shape["attributes"]["depth_method"] = "gps_ray_metric_fallback"
        logger.debug("GPS depth fallback: %s → %sm", shape.get("label", "?"), dm)
        matched_count += 1

    logger.debug("BIN+MAT fallback done: %d/%d boxes matched", matched_count, len(still_null))


def _attach_da3_box_depths(
    detections_by_camera: dict[str, list[dict]],
    depth_by_camera: dict[str, object],
    confidence_by_camera: dict[str, object],
) -> None:
    """Attach robust, non-metric DA3 depth summaries to each SAM3 box."""
    import numpy as np

    depth_low, depth_high = _finite_percentile_range(
        list(depth_by_camera.values()), positive=True
    )
    conf_low, conf_high = _finite_percentile_range(
        list(confidence_by_camera.values()), positive=False
    )

    for camera, detections in detections_by_camera.items():
        depth = depth_by_camera.get(camera)
        confidence = confidence_by_camera.get(camera)
        if depth is None:
            continue
        height, width = depth.shape
        for detection in detections:
            x1 = max(0, min(int(math.floor(detection["x1"])), width - 1))
            y1 = max(0, min(int(math.floor(detection["y1"])), height - 1))
            x2 = max(x1 + 1, min(int(math.ceil(detection["x2"])), width))
            y2 = max(y1 + 1, min(int(math.ceil(detection["y2"])), height))

            # The inner 70% reduces background contamination around a box edge.
            inset_x = int((x2 - x1) * 0.15)
            inset_y = int((y2 - y1) * 0.15)
            ix1, ix2 = x1 + inset_x, x2 - inset_x
            iy1, iy2 = y1 + inset_y, y2 - inset_y
            if ix2 <= ix1 or iy2 <= iy1:
                ix1, iy1, ix2, iy2 = x1, y1, x2, y2

            depth_crop = np.asarray(depth[iy1:iy2, ix1:ix2])
            valid = np.isfinite(depth_crop) & (depth_crop > 0)
            conf_crop = None
            if confidence is not None:
                conf_crop = np.asarray(confidence[iy1:iy2, ix1:ix2])
                valid &= np.isfinite(conf_crop)
                if valid.any():
                    threshold = np.percentile(conf_crop[valid], 25.0)
                    high_confidence = valid & (conf_crop >= threshold)
                    if high_confidence.sum() >= min(16, valid.sum()):
                        valid = high_confidence
            if not valid.any():
                continue

            raw_depth = float(np.median(depth_crop[valid]))
            normalized = max(
                0.0, min((raw_depth - depth_low) / (depth_high - depth_low), 1.0)
            )
            raw_confidence = (
                float(np.median(conf_crop[valid])) if conf_crop is not None else None
            )
            normalized_confidence = (
                max(
                    0.0,
                    min(
                        (raw_confidence - conf_low) / (conf_high - conf_low), 1.0
                    ),
                )
                if raw_confidence is not None
                else None
            )
            detection.update({
                "relative_depth": raw_depth,
                "relative_depth_normalized": normalized,
                "relative_depth_confidence": normalized_confidence,
                "relative_depth_confidence_raw": raw_confidence,
                "relative_depth_support_pixels": int(valid.sum()),
                "relative_depth_method": "da3_inner_box_confident_median",
                "relative_depth_is_metric": False,
            })


def _bbox_iou(a: dict, b: dict) -> float:
    x1 = max(a["x1"], b["x1"])
    y1 = max(a["y1"], b["y1"])
    x2 = min(a["x2"], b["x2"])
    y2 = min(a["y2"], b["y2"])
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    if intersection <= 0:
        return 0.0
    area_a = max(0.0, a["x2"] - a["x1"]) * max(0.0, a["y2"] - a["y1"])
    area_b = max(0.0, b["x2"] - b["x1"]) * max(0.0, b["y2"] - b["y1"])
    return intersection / max(area_a + area_b - intersection, 1e-9)


def _deduplicate_sam3_boxes(detections: list[dict]) -> list[dict]:
    """Suppress duplicate prompt results while preserving distinct structures."""
    kept: list[dict] = []
    for candidate in sorted(detections, key=lambda item: item["score"], reverse=True):
        duplicate = False
        for accepted in kept:
            iou = _bbox_iou(candidate, accepted)
            same_class = candidate["class_id"] == accepted["class_id"]
            if (same_class and iou >= 0.55) or (not same_class and iou >= 0.75):
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
    return kept


def _detect_sam3_features(processor, pil_img) -> tuple[list[dict], float]:
    """Run all fine-grained prompts while reusing one image backbone result."""
    with _sam3_lock:
        with _gpu_inference_lock:
            t0 = time.time()
            width, height = pil_img.size
            state = processor.set_image(pil_img)
            original_threshold = processor.confidence_threshold
            detections: list[dict] = []
            try:
                for spec in SAM3_CLASS_SPECS:
                    processor.set_confidence_threshold(spec["threshold"])
                    output = processor.set_text_prompt(spec["prompt"], state)
                    boxes = output.get("boxes", [])
                    scores = output.get("scores", [])
                    for index, box in enumerate(boxes):
                        x1 = max(0.0, min(float(box[0]), float(width)))
                        y1 = max(0.0, min(float(box[1]), float(height)))
                        x2 = max(0.0, min(float(box[2]), float(width)))
                        y2 = max(0.0, min(float(box[3]), float(height)))
                        if x2 <= x1 or y2 <= y1:
                            continue
                        detections.append({
                            "x1": x1,
                            "y1": y1,
                            "x2": x2,
                            "y2": y2,
                            "class_id": spec["class_id"],
                            "class_name": spec["label"],
                            "label_zh": spec["label_zh"],
                            "prompt": spec["prompt"],
                            "score": float(scores[index]) if index < len(scores) else 0.0,
                            "image_width": width,
                            "image_height": height,
                        })
            finally:
                processor.set_confidence_threshold(original_threshold)

        return _deduplicate_sam3_boxes(detections), time.time() - t0


def _timestamp_token(filename: str) -> str:
    match = _TS_RE.search(filename)
    token = match.group(1) if match else Path(filename).stem
    return re.sub(r"[^0-9A-Za-z._-]+", "_", token)


def _build_sam3_labelme_document(
    *,
    detections: list[dict],
    camera: str,
    image_file: str,
    image_width: int,
    image_height: int,
    seg_path: str,
    ir_file: str,
) -> dict:
    """Build a LabelMe-compatible document with explicit centre-origin data."""
    center_x = image_width / 2.0
    center_y = image_height / 2.0
    shapes = []
    for detection in detections:
        x1, y1 = detection["x1"], detection["y1"]
        x2, y2 = detection["x2"], detection["y2"]
        shapes.append({
            "label": detection["class_name"],
            "points": [[round(x1, 3), round(y1, 3)], [round(x2, 3), round(y2, 3)]],
            "group_id": None,
            "description": detection.get("description", ""),
            "shape_type": "rectangle",
            "flags": {},
            "attributes": {
                "label_id": detection["class_id"],
                "label_zh": detection["label_zh"],
                "bbox_centered_xyxy": [
                    round(x1 - center_x, 3),
                    round(y1 - center_y, 3),
                    round(x2 - center_x, 3),
                    round(y2 - center_y, 3),
                ],
                "box_center_centered_xy": [
                    round((x1 + x2) / 2.0 - center_x, 3),
                    round((y1 + y2) / 2.0 - center_y, 3),
                ],
                "sam3_score": round(detection["score"], 6),
                "sam3_prompt": detection["prompt"],
                "annotation_source": detection.get("annotation_source", "sam3"),
                "human_modified": bool(detection.get("human_modified", False)),
                "depth_m": detection.get("depth_m"),
                "depth_method": detection.get("depth_method", "not_computed"),
                "depth_confidence": round(float(detection.get("depth_confidence", 0.0)), 6),
                "depth_support_points": int(detection.get("depth_support_points", 0)),
                "relative_depth": (
                    round(float(detection["relative_depth"]), 6)
                    if detection.get("relative_depth") is not None else None
                ),
                "relative_depth_normalized": (
                    round(float(detection["relative_depth_normalized"]), 6)
                    if detection.get("relative_depth_normalized") is not None else None
                ),
                "relative_depth_confidence": (
                    round(float(detection["relative_depth_confidence"]), 6)
                    if detection.get("relative_depth_confidence") is not None else None
                ),
                "relative_depth_confidence_raw": (
                    round(float(detection["relative_depth_confidence_raw"]), 6)
                    if detection.get("relative_depth_confidence_raw") is not None else None
                ),
                "relative_depth_support_pixels": int(
                    detection.get("relative_depth_support_pixels", 0)
                ),
                "relative_depth_method": detection.get(
                    "relative_depth_method", "not_computed"
                ),
                "relative_depth_is_metric": False,
            },
        })

    relative_image = str(
        Path(seg_path) / "images" / CAMERA_DIRS[camera] / image_file
    )
    return {
        "version": "5.5.0",
        "flags": {},
        "shapes": shapes,
        "imagePath": image_file,
        "imageData": None,
        "imageHeight": image_height,
        "imageWidth": image_width,
        "coordinateSystem": {
            "points": "image_pixel_top_left_x_right_y_down",
            "bbox_centered_xyxy": "image_center_x_right_y_down",
            "image_center_pixel": [center_x, center_y],
        },
        "camera": camera,
        "sourceImage": relative_image,
        "group": {
            "ir_file": ir_file,
            "ir_timestamp": _timestamp_token(ir_file),
            "visible_file": image_file,
            "visible_timestamp": _timestamp_token(image_file),
        },
        "model": {
            "name": "SAM3",
            "checkpoint": SAM3_CHECKPOINT.name,
            "device": MODEL_DEVICE,
        },
        "depthModel": {
            "name": "DA3-BASE",
            "checkpoint": "model.safetensors",
            "device": DA3_DEVICE,
            "processResolution": DA3_PROCESS_RES,
            "output": "relative_depth",
            "isMetric": False,
        },
    }


def _sam3_label_file_path(
    *, seg_path: str, ir_file: str, camera: str, image_file: str
) -> Path:
    """Resolve one SAM3/DA3 LabelMe document without scanning directories."""
    if camera not in ("037", "038"):
        raise HTTPException(status_code=400, detail="Only camera 037/038 is supported")
    if Path(ir_file).name != ir_file or Path(image_file).name != image_file:
        raise HTTPException(status_code=400, detail="Image filename must not contain a path")
    seg_relative = _safe_session_path(seg_path)
    ir_group = re.sub(r"[^0-9A-Za-z._-]+", "_", Path(ir_file).stem)
    output_dir = LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT / seg_relative / ir_group
    return output_dir / f"{_timestamp_token(image_file)}_{camera}.json"


def _invalidate_feature_annotation_cache(path: Path) -> None:
    with _feature_annotation_cache_lock:
        path_key = str(path)
        for key in [key for key in _feature_annotation_cache if key[0] == path_key]:
            _feature_annotation_cache.pop(key, None)


def _annotation_load_result(
    *, camera: str, image_file: str, found: bool = False,
    valid: bool = True, boxes: list[dict] | None = None, error: str = "",
) -> dict:
    return {
        "camera": camera,
        "image_file": image_file,
        "found": found,
        "valid": valid,
        "annotation_count": len(boxes or []),
        "boxes": boxes or [],
        "error": error,
    }


def _load_sam3_label_document(
    *, seg_path: str, ir_file: str, camera: str, image_file: str
) -> dict:
    """Load and validate one saved LabelMe document for the requested frame."""
    path = _sam3_label_file_path(
        seg_path=seg_path, ir_file=ir_file, camera=camera, image_file=image_file
    )
    cache_key = (str(path), ir_file, camera, image_file)
    now = time.time()
    with _feature_annotation_cache_lock:
        cached = _feature_annotation_cache.get(cache_key)
        if cached and now - cached["timestamp"] < _FEATURE_ANNOTATION_CACHE_TTL:
            return cached["data"]

    if not path.is_file():
        result = _annotation_load_result(camera=camera, image_file=image_file)
    else:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(document, dict):
                raise ValueError("Annotation document must be a JSON object")
            group = document.get("group") if isinstance(document.get("group"), dict) else {}
            matches = (
                document.get("imagePath") == image_file
                and document.get("camera") == camera
                and group.get("ir_file") == ir_file
                and group.get("visible_file") == image_file
            )
            if not matches:
                logger.warning("Ignoring mismatched annotation document: %s", path)
                result = _annotation_load_result(
                    camera=camera,
                    image_file=image_file,
                    found=True,
                    valid=False,
                    error="annotation_metadata_mismatch",
                )
            else:
                width = int(document.get("imageWidth") or 0)
                height = int(document.get("imageHeight") or 0)
                boxes: list[dict] = []
                class_by_label = {
                    spec["label"].casefold(): spec for spec in SAM3_CLASS_SPECS
                }
                for shape in document.get("shapes") or []:
                    if not isinstance(shape, dict) or shape.get("shape_type") != "rectangle":
                        continue
                    points = shape.get("points")
                    if not isinstance(points, list) or len(points) < 2:
                        continue
                    try:
                        x_values = [float(points[0][0]), float(points[1][0])]
                        y_values = [float(points[0][1]), float(points[1][1])]
                    except (TypeError, ValueError, IndexError):
                        continue
                    if not all(math.isfinite(value) for value in x_values + y_values):
                        continue
                    attributes = shape.get("attributes")
                    if not isinstance(attributes, dict):
                        attributes = {}
                    label = str(shape.get("label") or "")
                    class_id = str(attributes.get("label_id") or "")
                    spec = SAM3_CLASS_BY_ID.get(class_id) or class_by_label.get(label.casefold())
                    if spec is not None:
                        class_id = spec["class_id"]
                    elif not class_id:
                        class_id = re.sub(r"[^0-9a-z]+", "_", label.casefold()).strip("_") or "unknown"
                    boxes.append({
                        "x1": min(x_values),
                        "y1": min(y_values),
                        "x2": max(x_values),
                        "y2": max(y_values),
                        "class_id": class_id,
                        "class_name": label or (spec["label"] if spec else class_id),
                        "label_zh": attributes.get("label_zh") or (spec["label_zh"] if spec else label),
                        "prompt": attributes.get("sam3_prompt") or (spec["prompt"] if spec else label),
                        "score": attributes.get("sam3_score", 0.0),
                        "image_width": width,
                        "image_height": height,
                        "description": shape.get("description") or "",
                        "annotation_source": attributes.get("annotation_source", "saved_json"),
                        "human_modified": bool(attributes.get("human_modified", False)),
                        "depth_m": attributes.get("depth_m"),
                        "depth_method": attributes.get("depth_method", "not_computed"),
                        "depth_confidence": attributes.get("depth_confidence", 0.0),
                        "depth_support_points": attributes.get("depth_support_points", 0),
                        "relative_depth": attributes.get("relative_depth"),
                        "relative_depth_normalized": attributes.get("relative_depth_normalized"),
                        "relative_depth_confidence": attributes.get("relative_depth_confidence"),
                        "relative_depth_confidence_raw": attributes.get("relative_depth_confidence_raw"),
                        "relative_depth_support_pixels": attributes.get("relative_depth_support_pixels", 0),
                        "relative_depth_method": attributes.get("relative_depth_method", "not_computed"),
                    })
                result = _annotation_load_result(
                    camera=camera, image_file=image_file, found=True, boxes=boxes
                )
        except (OSError, ValueError, TypeError) as exc:
            logger.warning("Could not load annotation document %s: %s", path, exc)
            result = _annotation_load_result(
                camera=camera,
                image_file=image_file,
                found=True,
                valid=False,
                error="annotation_read_failed",
            )

    with _feature_annotation_cache_lock:
        _feature_annotation_cache[cache_key] = {"timestamp": now, "data": result}
    return result


@router.get("/frame_annotations")
async def load_frame_annotations(
    seg_path: str = Query(..., description="Segment path"),
    ir_file: str = Query(..., description="Current IR filename"),
    file_037: str = Query("", description="Matched camera 037 filename"),
    file_038: str = Query("", description="Matched camera 038 filename"),
    root: str = Query(str(DATASET_ROOT)),
):
    """Load saved 037/038 annotations for one matched IR frame in one request."""
    root_path = _dataset_root(root)
    if Path(ir_file).name != ir_file:
        raise HTTPException(status_code=400, detail="Invalid IR filename")
    ir_path = _safe_join(root_path, seg_path, "images", CAMERA_DIRS["IR"], ir_file)
    if not ir_path.is_file():
        raise HTTPException(status_code=404, detail="IR image not found")

    files = {"037": file_037, "038": file_038}
    results: dict[str, dict] = {}
    jobs: list[tuple[str, object]] = []
    for camera, image_file in files.items():
        if not image_file:
            results[camera] = _annotation_load_result(camera=camera, image_file="")
            continue
        if Path(image_file).name != image_file:
            raise HTTPException(status_code=400, detail=f"Invalid {camera} filename")
        image_path = _safe_join(
            root_path, seg_path, "images", CAMERA_DIRS[camera], image_file
        )
        if not image_path.is_file():
            results[camera] = _annotation_load_result(camera=camera, image_file=image_file)
            continue
        jobs.append((camera, asyncio.to_thread(
            _load_sam3_label_document,
            seg_path=seg_path,
            ir_file=ir_file,
            camera=camera,
            image_file=image_file,
        )))

    if jobs:
        loaded = await asyncio.gather(*(job for _, job in jobs), return_exceptions=True)
        for (camera, _), result in zip(jobs, loaded):
            if isinstance(result, Exception):
                logger.warning("Could not load %s frame annotations: %s", camera, result)
                results[camera] = _annotation_load_result(
                    camera=camera,
                    image_file=files[camera],
                    found=True,
                    valid=False,
                    error="annotation_read_failed",
                )
            else:
                results[camera] = result

    # ── GPS 雷达 metric 深度补充（当已有深度为 null 时） ────────────────
    try:
        gps_boxes_map = {}
        capture_dir = _capture_dir_from_seg(seg_path)
        if capture_dir is not None:
            depth_dir = capture_dir / "depth_labels"
            if depth_dir.exists():
                for camera in ("037", "038"):
                    image_file = files.get(camera)
                    if not image_file:
                        continue
                    cam_stem = Path(image_file).stem
                    depth_path = depth_dir / f"{cam_stem}.json"
                    if depth_path.exists():
                        try:
                            gps_boxes_map[camera] = json.loads(
                                depth_path.read_text(encoding="utf-8")
                            ).get("boxes", [])
                        except Exception:
                            pass

        for camera, result_data in results.items():
            if not result_data.get("found") or not result_data.get("boxes"):
                continue
            gps_boxes = gps_boxes_map.get(camera, [])
            if not gps_boxes:
                continue

            matched_any = False
            for box in result_data["boxes"]:
                if box.get("depth_m") is not None:
                    continue  # 已有深度，不覆盖
                det_box = {"x1": box["x1"], "y1": box["y1"], "x2": box["x2"], "y2": box["y2"]}
                best_iou = 0.0
                best_depth = None
                for db in gps_boxes:
                    bbox = db.get("bbox_xyxy", [])
                    if len(bbox) < 4:
                        continue
                    db_box = {"x1": bbox[0], "y1": bbox[1], "x2": bbox[2], "y2": bbox[3]}
                    ix1 = max(det_box["x1"], db_box["x1"])
                    iy1 = max(det_box["y1"], db_box["y1"])
                    ix2 = min(det_box["x2"], db_box["x2"])
                    iy2 = min(det_box["y2"], db_box["y2"])
                    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
                    area_det = (det_box["x2"] - det_box["x1"]) * (det_box["y2"] - det_box["y1"])
                    area_db = (db_box["x2"] - db_box["x1"]) * (db_box["y2"] - db_box["y1"])
                    union = area_det + area_db - inter
                    iou = inter / union if union > 0 else 0.0
                    if iou > best_iou and iou >= 0.3:
                        best_iou = iou
                        best_depth = db
                if best_depth is not None:
                    box["depth_m"] = best_depth["depth_m"]
                    box["depth_method"] = best_depth.get("method", "gps_ray_clustered")
                    box["depth_confidence"] = min(1.0, best_depth.get("depth_cluster_points", 0) / 100.0)
                    box["depth_support_points"] = best_depth.get("depth_cluster_points", 0)
                    matched_any = True

            if matched_any:
                logger.debug(
                    "GPS depth (load): camera=%s matched %d/%d boxes",
                    camera,
                    sum(1 for b in result_data["boxes"] if b.get("depth_m") is not None),
                    len(result_data["boxes"]),
                )
    except Exception as exc:
        logger.warning("GPS depth injection (load) failed: %s", exc)

    return {"seg_path": seg_path, "ir_file": ir_file, "cameras": results}


def _save_sam3_label_document(
    *, seg_path: str, ir_file: str, camera: str, image_file: str, document: dict
) -> Path:
    output_file = _sam3_label_file_path(
        seg_path=seg_path, ir_file=ir_file, camera=camera, image_file=image_file
    )
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temp_file = output_file.with_suffix(".json.tmp")
    temp_file.write_text(
        json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temp_file.replace(output_file)
    _invalidate_feature_annotation_cache(output_file)
    return output_file


# =========================================================================
# Layer 2: OpenCV SGBM stereo matching (双目几何)
# =========================================================================
_sgbm_matcher = None
_sgbm_lock = threading.Lock()


def _get_sgbm_matcher():
    global _sgbm_matcher
    if _sgbm_matcher is not None:
        return _sgbm_matcher
    try:
        import cv2
    except ImportError:
        return None
    with _sgbm_lock:
        if _sgbm_matcher is not None:
            return _sgbm_matcher
        _sgbm_matcher = cv2.StereoSGBM_create(
            minDisparity=0,
            numDisparities=48,       # covers 400m → ~30px @fx=12342
            blockSize=5,
            P1=8 * 3 * 5 * 5,
            P2=32 * 3 * 5 * 5,
            disp12MaxDiff=1,
            uniquenessRatio=10,
            speckleWindowSize=100,
            speckleRange=2,
            mode=cv2.STEREO_SGBM_MODE_SGBM_3WAY,
        )
        return _sgbm_matcher


def _match_stereo_sgbm(
    pil_037, pil_038,
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """双目 SGBM 稠密匹配 → metric depth map (037/038 视角各一张)."""
    import cv2
    import numpy as np

    matcher = _get_sgbm_matcher()
    if matcher is None:
        return {}, {}

    gray_037 = np.asarray(pil_037.convert("L"), dtype=np.uint8)
    gray_038 = np.asarray(pil_038.convert("L"), dtype=np.uint8)
    h, w = gray_037.shape

    # Stereo rectify (both rectified, R=I, T=[B,0,0])
    K1 = np.array([[12342.23, 0, 959.5], [0, 12338.27, 599.5], [0, 0, 1]], dtype=np.float64)
    K2 = np.array([[12585.59, 0, 959.5], [0, 12588.75, 599.5], [0, 0, 1]], dtype=np.float64)
    D = np.zeros((5, 1), dtype=np.float64)
    R = np.eye(3, dtype=np.float64)
    T = np.array([[STEREO_BASELINE_M], [0], [0]], dtype=np.float64)

    R1, R2, P1, P2, Q, _, _ = cv2.stereoRectify(
        K1, D, K2, D, (w, h), R, T,
        alpha=0, newImageSize=(w, h),
    )

    map1x, map1y = cv2.initUndistortRectifyMap(K1, D, R1, P1, (w, h), cv2.CV_32FC1)
    map2x, map2y = cv2.initUndistortRectifyMap(K2, D, R2, P2, (w, h), cv2.CV_32FC1)
    rect_037 = cv2.remap(gray_037, map1x, map1y, cv2.INTER_LINEAR)
    rect_038 = cv2.remap(gray_038, map2x, map2y, cv2.INTER_LINEAR)

    disp = matcher.compute(rect_037, rect_038).astype(np.float32) / 16.0
    disp[disp <= 0] = 1.0

    # Q = [[1,0,0,-cx],[0,1,0,-cy],[0,0,0,f],[0,0,1/B,0]]
    # Z = Q[2,3] / (disp - Q[3,2])
    # 或直接: Z = f * B / disp
    fx_rect = P1[0, 0]
    depth_037 = (fx_rect * STEREO_BASELINE_M) / disp
    depth_037[~np.isfinite(depth_037)] = 0
    depth_037[(depth_037 < STEREO_MIN_DEPTH_M) | (depth_037 > STEREO_MAX_DEPTH_M)] = 0

    # 右图深度: 从视差图重映射到右图坐标
    depth_038 = np.full_like(depth_037, 0, dtype=np.float32)
    for col in range(w):
        src_col = col - disp[:, col].round().astype(np.int32)
        valid = (src_col >= 0) & (src_col < w)
        depth_038[valid, col] = depth_037[valid, src_col[valid]]

    conf = np.clip(1.0 - disp / 48.0, 0.1, 1.0)

    return {"037": depth_037, "038": depth_038}, {"037": conf, "038": conf}


# =========================================================================
# Layer 3: DA3-guided dense stereo matching
# =========================================================================
def _match_da3_stereo_crosscheck(
    depth_rel_by_camera: dict[str, np.ndarray],
    camera_order: list[str],
) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    """DA3 相对深度引导的稠密立体匹配 → metric depth."""
    if len(camera_order) < 2:
        return {}, {}
    cam0, cam1 = camera_order[0], camera_order[1]
    d0 = depth_rel_by_camera.get(cam0)
    d1 = depth_rel_by_camera.get(cam1)
    if d0 is None or d1 is None:
        return {}, {}

    import numpy as np
    h, w = d0.shape
    fx0 = CAMERA_INTRINSICS[cam0]["fx"]
    fx1 = CAMERA_INTRINSICS[cam1]["fx"]
    B = STEREO_BASELINE_M

    # Baseline-bound search window:
    #  d_max = fx * B / MIN_DEPTH ≈ 12342 * 0.4 / 400 ≈ 12.3px
    #  d_min = fx * B / MAX_DEPTH ≈ 12342 * 0.4 / 4000 ≈ 1.2px
    max_disp = int(fx0 * B / STEREO_MIN_DEPTH_M) + 2   # ~14
    min_disp = max(1, int(fx0 * B / STEREO_MAX_DEPTH_M))  # ~1

    depth_metric = np.zeros((h, w), dtype=np.float32)
    confidence = np.zeros((h, w), dtype=np.float32)

    # Process every 2nd row for speed, interpolate the rest
    for y in range(0, h, 2):
        row0 = d0[y, :]
        row1_da3 = d1[y, :]
        for x in range(max_disp, w - max_disp):
            search_s = x - max_disp
            search_e = x - min_disp
            if search_e <= search_s:
                continue
            patch = row0[x]
            search_region = row1_da3[search_s:search_e + 1]
            costs = np.abs(search_region - patch)
            best_idx = int(np.argmin(costs))
            best_d = float(max_disp - best_idx)

            # Sub-pixel refinement (parabolic fit on cost curve)
            if 1 <= best_idx < len(costs) - 1:
                c0, c1, c2 = costs[best_idx - 1], costs[best_idx], costs[best_idx + 1]
                if c1 < c0 and c1 < c2:
                    denom = c0 - 2.0 * c1 + c2
                    if abs(denom) > 1e-9:
                        best_d += 0.5 * (c0 - c2) / denom

            if best_d >= float(min_disp):
                d_sub = best_d
                depth_metric[y, x] = float(fx0 * B / d_sub)
                cnorm = costs[best_idx] / (np.mean(search_region) + 1e-6)
                confidence[y, x] = float(np.clip(1.0 - cnorm, 0.1, 0.95))

            # Copy down one row (interpolate skipped rows)
            if y + 1 < h:
                depth_metric[y + 1, x] = depth_metric[y, x]
                confidence[y + 1, x] = confidence[y, x] * 0.9
                depth_metric[y + 1, x] = depth_metric[y, x]
                confidence[y + 1, x] = confidence[y, x] * 0.9

    # Clean up
    depth_metric[~np.isfinite(depth_metric)] = 0
    mask = (depth_metric < STEREO_MIN_DEPTH_M) | (depth_metric > STEREO_MAX_DEPTH_M)
    depth_metric[mask] = 0
    confidence[mask] = 0

    result_depth = {cam0: depth_metric, cam1: depth_metric}
    result_conf = {cam0: confidence, cam1: confidence}
    return result_depth, result_conf


# =========================================================================
# Layer 4: Per-camera DA3 relative → metric calibration (线性校准补漏)
# =========================================================================
# Sliding window for cross-frame calibration stability
_da3_calib_window: dict[str, list] = {}  # camera → list of (relative_depth, depth_m)


def _da3_calibrate_per_camera(detections_by_camera: dict[str, list[dict]]) -> None:
    """对每相机独立做 DA3→metric 线性校准，为仍为 null 的框补深度."""
    import numpy as np

    for camera, detections in detections_by_camera.items():
        # 收集锚点: 同时有 DA3 relative_depth 和已知 depth_m 的框
        anchors = [(d["relative_depth"], d["depth_m"]) for d in detections
                   if d.get("depth_m") is not None
                   and d.get("relative_depth") is not None
                   and np.isfinite(d["relative_depth"])]
        nulls = [d for d in detections
                 if d.get("depth_m") is None
                 and d.get("relative_depth") is not None]
        if not nulls:
            continue

        x_vals = np.array([a[0] for a in anchors], dtype=np.float64)
        y_vals = np.array([a[1] for a in anchors], dtype=np.float64)
        n_anchor = len(anchors)

        a_cam, b_cam = 0.0, 0.0
        fit_r2 = 0.0

        if n_anchor >= 3:
            try:
                from sklearn.linear_model import RANSACRegressor
                reg = RANSACRegressor(min_samples=3, residual_threshold=max(100.0, y_vals.std() * 1.5), max_trials=50)
                reg.fit(x_vals.reshape(-1, 1), y_vals)
                a_cam = float(reg.estimator_.coef_[0])
                b_cam = float(reg.estimator_.intercept_)
                fit_r2 = max(0.0, float(reg.score(x_vals.reshape(-1, 1), y_vals)))
                # 更新滑动窗口
                key = f"{camera}_a"
                prev = _da3_calib_window.get(key, a_cam)
                _da3_calib_window[key] = 0.9 * prev + 0.1 * a_cam
            except Exception:
                pass

        if n_anchor < 3 or not np.isfinite(a_cam) or abs(a_cam) < 1e-6:
            # 锚点不足 → 用滑动窗口全局 a
            key = f"{camera}_a"
            a_cam = _da3_calib_window.get(key, 0.0)
            if abs(a_cam) < 1e-6:
                continue
            if n_anchor >= 1:
                # 用锚点估算当前帧偏移 b
                b_cam = float(np.median(y_vals - a_cam * x_vals))
            else:
                continue
            fit_r2 = 0.3

        # 补 null 框
        for det in nulls:
            rel = det["relative_depth"]
            pred = float(a_cam * rel + b_cam)
            if not np.isfinite(pred) or pred < STEREO_MIN_DEPTH_M or pred > STEREO_MAX_DEPTH_M:
                continue
            det["depth_m"] = round(pred, 1)
            det["depth_method"] = "da3_calibrated_stereo" if n_anchor >= 3 else "da3_calibrated_window"
            anchor_ratio = min(1.0, n_anchor / 5.0)
            det["depth_confidence"] = round(min(0.90, fit_r2 * anchor_ratio), 3)
            logger.debug(
                "DA3 calib %s: %s → %.0fm (R²=%.2f, anchors=%d)",
                camera, det.get("class_id", "?"), pred, fit_r2, n_anchor,
            )


class DetectFeaturesRequest(BaseModel):
    seg_path: str
    ir_file: str
    visible_files: dict[str, str]
    root: str = str(DATASET_ROOT)


@router.post("/detect_features")
async def detect_features(req: DetectFeaturesRequest):
    """Run SAM3 detection and DA3 relative depth on the two visible frames."""
    root_path = _dataset_root(req.root)
    if Path(req.ir_file).name != req.ir_file:
        raise HTTPException(status_code=400, detail="Invalid IR filename")

    try:
        _model, processor = await asyncio.to_thread(_get_sam3_serialized)
    except Exception as exc:
        logger.warning("SAM3 load failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"SAM3 unavailable: {exc}")

    try:
        da3_model = await asyncio.to_thread(_get_da3_serialized)
    except Exception as exc:
        logger.warning("DA3 load failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"DA3 unavailable: {exc}")

    result: dict = {
        "037": [],
        "038": [],
        "detector": "sam3+da3",
        "depth_output": "relative_non_metric",
        "ir_file": req.ir_file,
        "output_root": str(LABEL_WITH_ANNOTATION_AND_DEPTH_ROOT),
        "saved": {},
        "elapsed": {"sam3": {}, "da3": 0.0},
    }

    images: dict[str, object] = {}
    image_files: dict[str, str] = {}
    for camera in ("037", "038"):
        image_file = req.visible_files.get(camera)
        if not image_file:
            continue
        if Path(image_file).name != image_file:
            raise HTTPException(status_code=400, detail=f"Invalid {camera} filename")

        image_path = _safe_join(
            root_path, req.seg_path, "images", CAMERA_DIRS[camera], image_file
        )
        if not image_path.is_file():
            raise HTTPException(status_code=404, detail=f"Image not found: {image_file}")

        try:
            from PIL import Image

            with Image.open(image_path) as source_image:
                images[camera] = source_image.convert("RGB")
            image_files[camera] = image_file
        except Exception as exc:
            logger.exception("Could not load visible image for %s", camera)
            raise HTTPException(
                status_code=500, detail=f"Could not load {camera} image: {exc}"
            )

    detections_by_camera: dict[str, list[dict]] = {}
    try:
        for camera, pil_image in images.items():
            detections, elapsed = await asyncio.to_thread(
                _detect_sam3_features, processor, pil_image
            )
            detections_by_camera[camera] = detections
            result["elapsed"]["sam3"][camera] = round(elapsed, 3)

        camera_order = list(images)
        depths, confidences, da3_elapsed = await asyncio.to_thread(
            _predict_da3_pair,
            da3_model,
            [images[camera] for camera in camera_order],
        )
        depth_by_camera = dict(zip(camera_order, depths))
        confidence_by_camera = dict(zip(camera_order, confidences))
        _attach_da3_box_depths(
            detections_by_camera, depth_by_camera, confidence_by_camera
        )
        result["elapsed"]["da3"] = round(da3_elapsed, 3)

        # ── GPS 雷达 metric 深度注入 ────────────────────────────────────────
        try:
            _attach_gps_metric_depth(
                detections_by_camera, req.seg_path, image_files,
            )
        except Exception as exc:
            logger.warning("GPS metric depth attachment failed: %s", exc)

        # ── BIN 雷达语义深度注入（为仍无深度的检测框补漏） ───────────────────
        try:
            _attach_bin_metric_depth_in_detect(
                detections_by_camera, req.seg_path, image_files, root_path,
            )
        except Exception as exc:
            logger.warning("BIN metric depth attachment failed: %s", exc)

        # ── Layer 2: 双目 SGBM 几何匹配（中近距离） ────────────────────────
        try:
            sgbm_depth, sgbm_conf = _match_stereo_sgbm(
                images.get("037"), images.get("038"),
            )
            for camera in ("037", "038"):
                depth_map = sgbm_depth.get(camera)
                conf_map = sgbm_conf.get(camera)
                if depth_map is None:
                    continue
                for det in detections_by_camera.get(camera, []):
                    if det.get("depth_m") is not None:
                        continue
                    x0, y0, x1, y1 = map(int, [det["x1"], det["y1"], det["x2"], det["y2"]])
                    crop = depth_map[y0:y1, x0:x1]
                    valid = (crop > 0) & np.isfinite(crop)
                    if valid.sum() >= 3:
                        det["depth_m"] = round(float(np.median(crop[valid])), 1)
                        det["depth_method"] = "stereo_sgbm"
                        det["depth_confidence"] = round(float(np.median(conf_map[y0:y1, x0:x1][valid])), 3)
                        det["depth_support_points"] = int(valid.sum())
        except Exception as exc:
            logger.warning("SGBM stereo failed: %s", exc)

        # ── Layer 3: DA3 引导稠密立体匹配（中远距离） ──────────────────────
        try:
            da3_stereo_depth, da3_stereo_conf = _match_da3_stereo_crosscheck(
                depth_by_camera, camera_order,
            )
            for camera in ("037", "038"):
                depth_map = da3_stereo_depth.get(camera)
                conf_map = da3_stereo_conf.get(camera)
                if depth_map is None:
                    continue
                for det in detections_by_camera.get(camera, []):
                    if det.get("depth_m") is not None:
                        continue
                    x0, y0, x1, y1 = map(int, [det["x1"], det["y1"], det["x2"], det["y2"]])
                    crop = depth_map[y0:y1, x0:x1]
                    valid = (crop > 0) & np.isfinite(crop)
                    if valid.sum() >= 3:
                        det["depth_m"] = round(float(np.median(crop[valid])), 1)
                        det["depth_method"] = "da3_dense_stereo"
                        det["depth_confidence"] = round(float(np.median(conf_map[y0:y1, x0:x1][valid])), 3)
                        det["depth_support_points"] = int(valid.sum())
        except Exception as exc:
            logger.warning("DA3 stereo failed: %s", exc)

        # ── Layer 4: 分相机 DA3 相对深度校准补漏（最终补漏） ───────────────
        try:
            _da3_calibrate_per_camera(detections_by_camera)
        except Exception as exc:
            logger.warning("DA3 calibration failed: %s", exc)

    except Exception as exc:
        logger.exception("SAM3+DA3 inference failed")
        raise HTTPException(status_code=500, detail=f"SAM3+DA3 inference failed: {exc}")

    for camera, pil_image in images.items():
        image_file = image_files[camera]
        detections = detections_by_camera.get(camera, [])
        try:
            document = _build_sam3_labelme_document(
                detections=detections,
                camera=camera,
                image_file=image_file,
                image_width=pil_image.width,
                image_height=pil_image.height,
                seg_path=req.seg_path,
                ir_file=req.ir_file,
            )
            saved_path = await asyncio.to_thread(
                _save_sam3_label_document,
                seg_path=req.seg_path,
                ir_file=req.ir_file,
                camera=camera,
                image_file=image_file,
                document=document,
            )
            result[camera] = detections
            result["saved"][camera] = str(saved_path)
            logger.info(
                "SAM3+DA3 %s: %d objects -> %s",
                camera,
                len(detections),
                saved_path,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("SAM3+DA3 annotation save failed for %s", camera)
            raise HTTPException(
                status_code=500,
                detail=f"SAM3+DA3 {camera} annotation save failed: {exc}",
            )

    return result


class FeatureAnnotationEdit(BaseModel):
    class_id: str
    bbox_xyxy: list[float]
    sam3_score: float = 0.0
    sam3_prompt: str = ""
    depth_m: float | None = None
    depth_method: str = "not_computed"
    depth_confidence: float = 0.0
    depth_support_points: int = 0
    relative_depth: float | None = None
    relative_depth_normalized: float | None = None
    relative_depth_confidence: float | None = None
    relative_depth_confidence_raw: float | None = None
    relative_depth_support_pixels: int = 0
    relative_depth_method: str = "not_computed"
    description: str = ""


class UpdateFeatureAnnotationsRequest(BaseModel):
    seg_path: str
    ir_file: str
    camera: str
    image_file: str
    annotations: list[FeatureAnnotationEdit]
    root: str = str(DATASET_ROOT)


@router.post("/update_feature_annotations")
async def update_feature_annotations(req: UpdateFeatureAnnotationsRequest):
    """Validate UI edits and atomically replace one visible frame's JSON."""
    root_path = _dataset_root(req.root)
    if req.camera not in ("037", "038"):
        raise HTTPException(status_code=400, detail="Only camera 037/038 can be edited")
    if Path(req.ir_file).name != req.ir_file or Path(req.image_file).name != req.image_file:
        raise HTTPException(status_code=400, detail="Invalid image filename")

    image_path = _safe_join(
        root_path, req.seg_path, "images", CAMERA_DIRS[req.camera], req.image_file
    )
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail=f"Image not found: {req.image_file}")

    from PIL import Image

    with Image.open(image_path) as image:
        image_width, image_height = image.size

    detections: list[dict] = []
    for index, annotation in enumerate(req.annotations):
        spec = SAM3_CLASS_BY_ID.get(annotation.class_id)
        if spec is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported class at annotation {index}: {annotation.class_id}",
            )
        if len(annotation.bbox_xyxy) != 4:
            raise HTTPException(
                status_code=400, detail=f"bbox_xyxy must have 4 values at annotation {index}"
            )
        x1, y1, x2, y2 = (float(value) for value in annotation.bbox_xyxy)
        if not all(math.isfinite(value) for value in (x1, y1, x2, y2)):
            raise HTTPException(
                status_code=400, detail=f"Non-finite box coordinate at annotation {index}"
            )
        x1 = max(0.0, min(x1, float(image_width)))
        y1 = max(0.0, min(y1, float(image_height)))
        x2 = max(0.0, min(x2, float(image_width)))
        y2 = max(0.0, min(y2, float(image_height)))
        if x2 <= x1 or y2 <= y1:
            raise HTTPException(
                status_code=400, detail=f"Invalid box geometry at annotation {index}"
            )
        if annotation.depth_m is not None and (
            not math.isfinite(float(annotation.depth_m)) or annotation.depth_m < 0
        ):
            raise HTTPException(
                status_code=400, detail=f"Invalid depth at annotation {index}"
            )
        depth_confidence_raw = float(annotation.depth_confidence)
        if not math.isfinite(depth_confidence_raw):
            raise HTTPException(
                status_code=400, detail=f"Invalid depth confidence at annotation {index}"
            )
        depth_confidence = max(0.0, min(depth_confidence_raw, 1.0))
        relative_values = (
            annotation.relative_depth,
            annotation.relative_depth_normalized,
            annotation.relative_depth_confidence,
            annotation.relative_depth_confidence_raw,
        )
        if any(
            value is not None and not math.isfinite(float(value))
            for value in relative_values
        ):
            raise HTTPException(
                status_code=400, detail=f"Invalid relative depth at annotation {index}"
            )
        detections.append({
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
            "class_id": spec["class_id"],
            "class_name": spec["label"],
            "label_zh": spec["label_zh"],
            "prompt": annotation.sam3_prompt or spec["prompt"],
            "score": max(0.0, min(float(annotation.sam3_score), 1.0)),
            "image_width": image_width,
            "image_height": image_height,
            "description": annotation.description.strip(),
            "annotation_source": "sam3_human_edited",
            "human_modified": True,
            "depth_m": annotation.depth_m,
            "depth_method": (
                annotation.depth_method.strip() or "manual"
                if annotation.depth_m is not None
                else "not_computed"
            ),
            "depth_confidence": depth_confidence,
            "depth_support_points": max(0, int(annotation.depth_support_points)),
            "relative_depth": annotation.relative_depth,
            "relative_depth_normalized": annotation.relative_depth_normalized,
            "relative_depth_confidence": annotation.relative_depth_confidence,
            "relative_depth_confidence_raw": annotation.relative_depth_confidence_raw,
            "relative_depth_support_pixels": max(
                0, int(annotation.relative_depth_support_pixels)
            ),
            "relative_depth_method": annotation.relative_depth_method.strip()
            or "not_computed",
            "relative_depth_is_metric": False,
        })

    document = _build_sam3_labelme_document(
        detections=detections,
        camera=req.camera,
        image_file=req.image_file,
        image_width=image_width,
        image_height=image_height,
        seg_path=req.seg_path,
        ir_file=req.ir_file,
    )

    # ── 保存时自动注入 GPS 雷达 metric 深度 ────────────────────────────────
    try:
        _inject_gps_depth_on_save(req, document, image_width)
    except Exception as exc:
        logger.warning("GPS depth auto-inject failed: %s", exc)

    saved_path = await asyncio.to_thread(
        _save_sam3_label_document,
        seg_path=req.seg_path,
        ir_file=req.ir_file,
        camera=req.camera,
        image_file=req.image_file,
        document=document,
    )
    return {
        "success": True,
        "camera": req.camera,
        "annotation_count": len(detections),
        "saved": str(saved_path),
    }


@router.get("/detect_buildings")
@router.post("/detect_buildings")
async def detect_buildings(
    seg_path: str = Query(..., description="Segment path"),
    ir_file: str = Query(..., description="IR filename for timestamp matching"),
    root: str = Query(str(DATASET_ROOT)),
):
    """Compatibility endpoint; now returns all configured fine-grained classes."""
    matched = match_ir_to_visible(root=root, seg_path=seg_path, ir_file=ir_file)
    visible_files = {
        camera: matched[camera]["file"]
        for camera in ("037", "038")
        if matched.get(camera)
    }
    return await detect_features(DetectFeaturesRequest(
        root=root,
        seg_path=seg_path,
        ir_file=ir_file,
        visible_files=visible_files,
    ))


@router.get("/lidar_bev")
def serve_lidar_bev(
    seg_path: str = Query(..., description="Segment path"),
    frame_id: str = Query(..., description="Camera frame filename for timestamp matching"),
):
    """Serve a top-down LiDAR point cloud BEV image from PCD files.

    Finds the PCD file in ``pointclouds/at360__points/`` whose timestamp is
    closest to the camera frame, then renders a colour-mapped bird's-eye view
    (height → hue, intensity → brightness).  Returns a 1×1 transparent PNG
    when no point cloud data is available.
    """
    import cv2
    import numpy as np

    root_path = _dataset_root(DATASET_ROOT).resolve()
    seg_dir = root_path / Path(*seg_path.split("/"))
    if not seg_dir.exists():
        return _empty_bev_response()

    # ── Find PCD directory ────────────────────────────────────────────────
    pcd_dir = seg_dir / "pointclouds" / "at360__points"
    if not pcd_dir.is_dir():
        return _empty_bev_response()

    # ── Match closest PCD file by timestamp ───────────────────────────────
    pcd_path = _match_pcd_for_frame(pcd_dir, frame_id)
    if pcd_path is None:
        return _empty_bev_response()

    # ── Load PCD point cloud ──────────────────────────────────────────────
    try:
        pts = _load_at360_pcd(pcd_path)
        if pts is None or len(pts) == 0:
            return _empty_bev_response()
    except Exception as exc:
        logger.debug("BEV: PCD load failed for %s: %s", pcd_path, exc)
        return _empty_bev_response()

    # ── Render top-down BEV ───────────────────────────────────────────────
    try:
        img_size = 512
        bev = np.zeros((img_size, img_size, 3), dtype=np.uint8)

        x, y, z = pts[:, 0], pts[:, 1], pts[:, 2]
        intensity = pts[:, 3] if pts.shape[1] >= 4 else np.ones_like(x)

        # Downsample for performance (retain ~100k points)
        if len(x) > 120_000:
            idx = np.random.RandomState(42).choice(len(x), 120_000, replace=False)
            x, y, z, intensity = x[idx], y[idx], z[idx], intensity[idx]

        # Filter sensor self-returns: the at360 LiDAR records many returns
        # at (x≈0, y≈0) from the sensor housing.  Drop those and estimate
        # the BEV range from the remaining environmental points.
        min_dist = 1.0
        env_mask = x >= min_dist
        if env_mask.sum() < 10:
            # All points are near-zero clutter — nothing useful to show
            return _empty_bev_response()

        x_env, y_env = x[env_mask], y[env_mask]
        fwd_range = float(np.percentile(x_env, 98)) * 1.05
        lat_range = float(np.percentile(np.abs(y_env), 98)) * 1.05
        fwd_range = max(20.0, min(300.0, fwd_range))
        lat_range = max(15.0, min(300.0, lat_range))

        # Filter
        mask = env_mask & (x < fwd_range) & (np.abs(y) < lat_range)
        x, y, z, intensity = x[mask], y[mask], z[mask], intensity[mask]

        if len(x) == 0:
            return _empty_bev_response()

        # Normalize intensity
        i_hi = float(np.percentile(intensity, 95))
        i_norm = np.clip(intensity / max(i_hi, 1e-8), 0, 1)

        # Map: ego at bottom-centre, forward → up, lateral → left/right
        col = ((y + lat_range) / (2 * lat_range) * (img_size - 1)).astype(int)
        row = (img_size - 1 - ((x - min_dist) / (fwd_range - min_dist) * (img_size - 1))).astype(int)
        col = np.clip(col, 0, img_size - 1)
        row = np.clip(row, 0, img_size - 1)

        # Height colour map: low → blue, high → red
        z_lo, z_hi = float(np.percentile(z, 2)), float(np.percentile(z, 98))
        z_span = max(z_hi - z_lo, 1.0)
        z_norm = np.clip((z - z_lo) / z_span, 0, 1)
        point_radius = max(1, int(img_size / 256))  # 2px for 512
        for i in range(len(x)):
            r_val = int(z_norm[i] * 255)
            g_val = int(i_norm[i] * 200)
            b_val = int((1 - z_norm[i]) * 200) + 55
            rr, cc = row[i], col[i]
            r0 = max(0, rr - point_radius)
            r1 = min(img_size - 1, rr + point_radius)
            c0 = max(0, cc - point_radius)
            c1 = min(img_size - 1, cc + point_radius)
            bev[r0:r1 + 1, c0:c1 + 1] = [r_val, g_val, b_val]

        _, buf = cv2.imencode(".jpg", bev)
        return Response(content=buf.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=60"})
    except Exception as exc:
        logger.debug("BEV: render failed: %s", exc)
        return _empty_bev_response()


# ── PCD helpers ────────────────────────────────────────────────────────────────

# at360 PCD record: x(F4) y(F4) z(F4) intensity(F4) ring(U2) timestamp(F8) confidence(F4)
_PCD_STRUCT = struct.Struct("<4fHdf")
_PCD_RECORD_SIZE = _PCD_STRUCT.size  # 30 bytes


def _load_at360_pcd(path: Path) -> "np.ndarray | None":
    """Load an at360 PCD file, returning N×4 ``[x, y, z, intensity]``."""
    import numpy as np
    data = path.read_bytes()
    hdr_end = data.find(b"DATA binary")
    if hdr_end < 0:
        return None
    # Parse point count from header
    hdr_text = data[:hdr_end].decode("ascii", errors="replace")
    m = re.search(r"POINTS\s+(\d+)", hdr_text)
    num_points = int(m.group(1)) if m else 0
    if num_points <= 0:
        return None
    body = data[hdr_end + len(b"DATA binary\n"):]
    # Unpack
    count = min(num_points, len(body) // _PCD_RECORD_SIZE)
    pts = np.empty((count, 4), dtype=np.float32)
    for i in range(count):
        offset = i * _PCD_RECORD_SIZE
        vals = _PCD_STRUCT.unpack_from(body, offset)
        pts[i, 0] = vals[0]  # x
        pts[i, 1] = vals[1]  # y
        pts[i, 2] = vals[2]  # z
        pts[i, 3] = vals[3]  # intensity
    return pts


_TS_RE = re.compile(r"_t(\d+\.\d+)")


def _match_pcd_for_frame(pcd_dir: Path, frame_id: str) -> Path | None:
    """Return the PCD file whose embedded timestamp is closest to *frame_id*."""
    camera_ts = _parse_camera_rel_time(frame_id)
    if camera_ts is None:
        # No timestamp in frame filename — return first PCD
        pcd_files = sorted(pcd_dir.glob("*.pcd"))
        return pcd_files[0] if pcd_files else None

    best, best_dist = None, float("inf")
    for pcd in pcd_dir.glob("*.pcd"):
        m = _TS_RE.search(pcd.name)
        if m is None:
            continue
        pcd_ts = float(m.group(1))
        dist = abs(pcd_ts - camera_ts)
        if dist < best_dist:
            best_dist = dist
            best = pcd
    # Fallback: first file if no timestamps matched
    if best is None:
        pcd_files = sorted(pcd_dir.glob("*.pcd"))
        best = pcd_files[0] if pcd_files else None
    return best


def _parse_camera_rel_time(filename: str) -> float | None:
    """Extract relative timestamp from ``hikrobot_..._t000006.960.jpg``."""
    m = _TS_RE.search(filename)
    return float(m.group(1)) if m else None


# ── mmWave radar building detection from bin ────────────────────────────────

_BIN_PACKET_BYTES = 8624
_BIN_SUM_SAMPLES = 672       # 和路 range gates per packet
_BIN_MIN_SIGNAL_DB = 80.0    # minimum signal for a detection
_BIN_SCAN_WINDOW_S = 2.0     # ± seconds around camera frame to scan


def _parse_bin_header(data: bytes) -> dict:
    """Parse the 256-byte header of a single bin UDP packet.

    The heading field in the bin is the **camera/radar body heading**,
    which follows the LH dataset convention ``camera_heading = gps_hdg - 90°``.
    The camera is mounted 90° left of the GPS true heading.
    So for ``gps_hdg ≈ 57°`` the bin heading reads ``≈ -33°`` (same as 327°).
    """
    return {
        "fz": struct.unpack_from("<I", data, 12)[0],
        "ant_start": struct.unpack_from("<I", data, 24)[0],
        "range_km": struct.unpack_from("<f", data, 32)[0],
        "ts_cst_sec": _decode_bin_ts(struct.unpack_from("<I", data, 44)[0]),
        "lon": float(struct.unpack_from("<f", data, 48)[0]),
        "lat": float(struct.unpack_from("<f", data, 52)[0]),
        "heading": float(struct.unpack_from("<f", data, 56)[0]),
        "alt": float(struct.unpack_from("<f", data, 60)[0]),
        "ant_az": float(struct.unpack_from("<f", data, 80)[0]),
        "ant_el": float(struct.unpack_from("<f", data, 84)[0]),
    }


def _decode_bin_ts(ts_lo: int) -> float:
    """Decode HHMMSSMMM → seconds of day (CST)."""
    hh = ts_lo // 10_000_000
    mm = (ts_lo % 10_000_000) // 100_000
    ss = (ts_lo % 100_000) // 1_000
    ms = ts_lo % 1_000
    return hh * 3600 + mm * 60 + ss + ms / 1000.0


def _find_bin_file(capture_dir: Path) -> Path | None:
    """Find the mmwave_udp.bin file in a capture directory."""
    for cand in capture_dir.glob("*_mmwave_udp.bin"):
        return cand
    return None


def _scan_bin_time_index(bin_path: Path) -> list[tuple[float, int]]:
    """Build (cst_sec, byte_offset) index for a bin file.  Cached on disk."""
    cache_path = bin_path.with_suffix(bin_path.suffix + ".idx")
    if cache_path.exists():
        try:
            pairs = []
            with open(cache_path, "rb") as fh:
                while True:
                    data = fh.read(12)
                    if len(data) < 12:
                        break
                    ts, off = struct.unpack("<dI", data)
                    pairs.append((ts, off))
            if pairs:
                return pairs
        except Exception:
            pass

    pairs: list[tuple[float, int]] = []
    file_size = bin_path.stat().st_size
    with open(bin_path, "rb") as fh:
        offset = 0
        while offset + _BIN_PACKET_BYTES <= file_size:
            fh.seek(offset)
            header = fh.read(256)
            if len(header) < 256:
                break
            sync = struct.unpack_from("<I", header, 0)[0]
            if sync != 0xABABABAB:
                offset += _BIN_PACKET_BYTES
                continue
            ts_lo = struct.unpack_from("<I", header, 44)[0]
            cst_sec = _decode_bin_ts(ts_lo)
            pairs.append((cst_sec, offset))
            offset += _BIN_PACKET_BYTES
            # Progress every 50000 packets
            if len(pairs) % 50000 == 0:
                logger.info("Bin index: %d packets scanned...", len(pairs))

    # Persist index
    try:
        with open(cache_path, "wb") as fh:
            for ts, off in pairs:
                fh.write(struct.pack("<dI", ts, off))
    except Exception:
        pass
    return pairs


def _extract_radar_detections(
    bin_path: Path, time_index: list, target_cst: float
) -> list[dict]:
    """Extract GPS-tagged radar detections within ±_BIN_SCAN_WINDOW_S of target_cst.

    Returns list of ``{lat, lon, signal_db, range_m, az_deg}`` dicts.
    """
    import bisect, math as _math
    timestamps = [p[0] for p in time_index]
    lo = bisect.bisect_left(timestamps, target_cst - _BIN_SCAN_WINDOW_S)
    hi = bisect.bisect_right(timestamps, target_cst + _BIN_SCAN_WINDOW_S)
    if lo >= hi:
        return []

    detections: list[dict] = []
    with open(bin_path, "rb") as fh:
        for idx in range(lo, min(hi, len(time_index))):
            offset = time_index[idx][1]
            fh.seek(offset)
            pkt = fh.read(_BIN_PACKET_BYTES)
            if len(pkt) < _BIN_PACKET_BYTES:
                continue
            hdr = _parse_bin_header(pkt[:256])
            range_km = max(hdr["range_km"], 0.5)  # minimum 500m
            gate_m = range_km * 1000.0 / _BIN_SUM_SAMPLES

            # Read sum-channel signal (float32, 672 range gates)
            sig = np.frombuffer(pkt[256:256 + _BIN_SUM_SAMPLES * 4], dtype=np.float32)

            # Threshold-based detection
            strong = np.where(sig > _BIN_MIN_SIGNAL_DB)[0]
            for gi in strong:
                r_m = (gi + 0.5) * gate_m  # centre of range gate
                # Compute target GPS from sensor GPS + heading + antenna azimuth + range
                bearing_deg = hdr["heading"] + hdr["ant_az"]
                bearing_rad = _math.radians(bearing_deg)
                cos_lat = _math.cos(_math.radians(hdr["lat"]))
                east = r_m * math.sin(bearing_rad)
                north = r_m * math.cos(bearing_rad)
                tgt_lat = hdr["lat"] + north / 111_320.0
                tgt_lon = hdr["lon"] + east / (111_320.0 * cos_lat)
                detections.append({
                    "lat": tgt_lat,
                    "lon": tgt_lon,
                    "signal_db": float(sig[gi]),
                    "range_m": r_m,
                    "az_deg": hdr["ant_az"],
                    "sensor_lat": hdr["lat"],
                    "sensor_lon": hdr["lon"],
                })
    return detections


def _read_gps_nav_rel_time(seg_dir: Path, cst_sec: float) -> float | None:
    """Convert bin CST seconds → camera relative_time using nav100_state.csv."""
    state_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
    if not state_csv.exists():
        return None
    try:
        best_rel, best_dist = None, float("inf")
        with open(state_csv, newline="", encoding="utf-8") as fh:
            reader = csv_mod.DictReader(fh)
            for row in reader:
                try:
                    h = int(row["gps_hour"]) + 8  # UTC → CST
                    m = int(row["gps_minute"])
                    s = int(row["gps_second"])
                    ms = int(row["gps_millisecond"])
                    csv_cst = h * 3600 + m * 60 + s + ms / 1000.0
                    dist = abs(csv_cst - cst_sec)
                    if dist < best_dist:
                        best_dist = dist
                        best_rel = float(row["relative_time_sec"])
                except (KeyError, ValueError):
                    continue
        return best_rel
    except Exception:
        return None


def _sample_bin_detections(bin_path: Path, max_packets: int = 600) -> list[dict]:
    """Sample radar packets evenly across the bin file and extract detections.

    Results are cached to ``{bin_path}.detcache`` so subsequent requests for
    the same bin file are near-instant.
    """
    import math as _math
    import json
    import numpy as np

    # Check on-disk cache (one dir per capture)
    cache_path = bin_path.with_suffix(bin_path.suffix + ".detcache")
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            if isinstance(cached, list) and len(cached) > 0:
                return cached
        except (json.JSONDecodeError, OSError):
            pass

    file_size = bin_path.stat().st_size
    n_total = file_size // _BIN_PACKET_BYTES
    if n_total <= 0:
        return []

    # Sample ~600 packets to cover the scan pattern, especially important
    # when the drone is hovering — the full antenna sweep repeats every ~80
    # packets, so 600 packets gives ~7 full sweeps and ~1400 detections
    n_sample = min(max_packets, 80)
    step = max(1, n_total // n_sample)
    indices = list(range(0, n_total, step))[:n_sample]

    detections: list[dict] = []
    buf = bytearray(_BIN_PACKET_BYTES)
    with open(bin_path, "rb") as fh:
        for idx in indices:
            offset = idx * _BIN_PACKET_BYTES
            fh.seek(offset)
            n = fh.readinto(buf)
            if n < _BIN_PACKET_BYTES:
                continue
            sync = struct.unpack_from("<I", buf, 0)[0]
            if sync != 0xABABABAB:
                continue
            hdr = _parse_bin_header(bytes(buf[:256]))
            if not (20 < hdr["lat"] < 50 and 100 < hdr["lon"] < 130):
                continue
            range_km = max(hdr["range_km"], 0.5)
            gate_m = range_km * 1000.0 / _BIN_SUM_SAMPLES
            sig = np.frombuffer(buf[256:256 + _BIN_SUM_SAMPLES * 4], dtype=np.float32)
            strong = np.where(sig > _BIN_MIN_SIGNAL_DB)[0]
            if len(strong) == 0:
                continue
            # Top 4 strongest returns per packet (covers multiple objects)
            top_k = min(4, len(strong))
            top_idx = strong[np.argpartition(sig[strong], -top_k)[-top_k:]]
            bearing = _math.radians(hdr["heading"] + hdr["ant_az"])
            cos_lat = _math.cos(_math.radians(hdr["lat"]))
            for gi in top_idx:
                r_m = (gi + 0.5) * gate_m
                east = r_m * _math.sin(bearing)
                north = r_m * _math.cos(bearing)
                detections.append({
                    "lat": hdr["lat"] + north / 111_320.0,
                    "lon": hdr["lon"] + east / (111_320.0 * cos_lat),
                    "signal_db": float(sig[gi]),
                    "range_m": r_m,
                    "az_deg": hdr["ant_az"],
                })

    # Write cache
    try:
        with open(cache_path, "w", encoding="utf-8") as fh:
            json.dump(detections, fh, ensure_ascii=False)
    except OSError:
        pass

    return detections


def _read_drone_gps_path(seg_dir: Path) -> list[list[float]]:
    """Read drone GPS trajectory from nav100__fix.csv.

    Returns a list of ``[lat_gcj, lon_gcj]`` pairs (front-end ready).
    """
    fix_csv = seg_dir / "gps" / "nav100__fix" / "nav100__fix.csv"
    if not fix_csv.exists():
        return []
    path = []
    try:
        with open(fix_csv, newline="", encoding="utf-8") as fh:
            reader = csv_mod.DictReader(fh)
            for row in reader:
                try:
                    lat = float(row["latitude"])
                    lon = float(row["longitude"])
                    gcj_lat, gcj_lon = _wgs84_to_gcj02(lat, lon)
                    path.append([gcj_lat, gcj_lon])
                except (KeyError, ValueError):
                    continue
    except Exception:
        return []
    return path


def _subsample_path(path: list, max_points: int) -> list:
    """Keep ``max_points`` evenly-spaced points from *path*."""
    if not path:
        return []
    n = len(path)
    if n <= max_points:
        return path
    step = n / max_points
    return [path[round(i * step)] for i in range(max_points)]


def _camera_rel_to_cst(seg_dir: Path, rel_time: float) -> float | None:
    """Convert camera relative_time_sec → bin CST seconds via nav100_state.csv."""
    state_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
    if not state_csv.exists():
        return None
    try:
        rows: list[tuple[float, float]] = []
        hdr_cst_offset = None
        with open(state_csv, newline="", encoding="utf-8") as fh:
            reader = csv_mod.DictReader(fh)
            for row in reader:
                try:
                    rel = float(row["relative_time_sec"])
                    h = int(row["gps_hour"]) + 8  # UTC → CST
                    m = int(row["gps_minute"])
                    s = int(row["gps_second"])
                    ms = int(row["gps_millisecond"])
                    cst = h * 3600 + m * 60 + s + ms / 1000.0
                    rows.append((rel, cst))
                except (KeyError, ValueError):
                    continue
        if not rows:
            return None
        # Closest match by relative_time
        best, best_dist = rows[0][1], abs(rows[0][0] - rel_time)
        for r, c in rows[1:]:
            dist = abs(r - rel_time)
            if dist < best_dist:
                best_dist = dist
                best = c
        return best
    except Exception:
        return None


# ── Satellite map + radar building overlay ───────────────────────────────────

# AMap satellite tile (style=6, no API key required)
_AMAP_SAT_URL = "https://webst0{n}.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}"
_AMAP_TILE_SIZE = 256
_MAP_RANGE_M = 20000.0  # ~20 km radius, 40 km total coverage
_MAX_MOSAIC_PX = 1024     # cap mosaic dimensions to limit tile count
_MAX_TOTAL_TILES = 36      # safety limit (6×6 tiles at most)

# WGS84 → GCJ02 constants (from gaode_buildings.py)
_GCJ_A = 6_378_245.0
_GCJ_EE = 0.006_693_421_622_965_943


def _wgs84_to_gcj02(lat: float, lon: float) -> tuple[float, float]:
    """WGS-84 → GCJ-02."""
    import math
    x = lon - 105.0; y = lat - 35.0
    dlat = (-100 + 2*x + 3*y + 0.2*y*y + 0.1*x*y + 0.2*abs(x)**0.5
        + (20*math.sin(6*x*math.pi)+20*math.sin(2*x*math.pi))*2/3
        + (20*math.sin(y*math.pi)+40*math.sin(y/3*math.pi))*2/3
        + (160*math.sin(y/12*math.pi)+320*math.sin(y*math.pi/30))*2/3)
    dlon = (300 + x + 2*y + 0.1*x*x + 0.1*x*y + 0.1*abs(x)**0.5
        + (20*math.sin(6*x*math.pi)+20*math.sin(2*x*math.pi))*2/3
        + (20*math.sin(x*math.pi)+40*math.sin(x/3*math.pi))*2/3
        + (150*math.sin(x/12*math.pi)+300*math.sin(x/30*math.pi))*2/3)
    rad = math.radians(lat)
    magic = 1 - _GCJ_EE * math.sin(rad)**2
    sq = math.sqrt(magic)
    dlat = dlat * 180 / ((_GCJ_A*(1-_GCJ_EE))/(magic*sq)*math.pi)
    dlon = dlon * 180 / (_GCJ_A/sq*math.cos(rad)*math.pi)
    return lat + dlat, lon + dlon


def _ll2tile(lon: float, lat: float, z: int) -> tuple[int, int]:
    """GCJ-02 lon/lat → tile (tx, ty)."""
    import math
    n = 2 ** z
    tx = int((lon + 180) / 360 * n)
    lat_r = math.radians(lat)
    ty = int((1 - math.log(math.tan(lat_r) + 1/math.cos(lat_r)) / math.pi) / 2 * n)
    return tx, ty


def _tile2ll(tx: float, ty: float, z: int) -> tuple[float, float]:
    """Tile float coords → GCJ-02 (lon, lat) top-left."""
    import math
    n = 2 ** z
    lon = tx / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * ty / n))))
    return lon, lat


def _meters_per_px(lat: float, z: int) -> float:
    """Meters per pixel at given latitude and zoom."""
    import math
    return 40_075_016.686 * math.cos(math.radians(lat)) / (_AMAP_TILE_SIZE * (2 ** z))


def _read_gps_for_frame(seg_dir: Path, camera_rel_time: float) -> dict | None:
    """Read GPS fix closest to *camera_rel_time* from nav100_state.csv."""
    state_csv = seg_dir / "nav100_state" / "nav100__state" / "nav100__state.csv"
    if not state_csv.exists():
        return None
    try:
        best, best_dist = None, float("inf")
        with open(state_csv, newline="", encoding="utf-8") as fh:
            reader = csv_mod.DictReader(fh)
            for row in reader:
                try:
                    t = float(row["relative_time_sec"])
                except (KeyError, ValueError):
                    continue
                dist = abs(t - camera_rel_time)
                if dist < best_dist:
                    best_dist = dist
                    try:
                        h = int(row["gps_hour"]) + 8  # UTC → CST
                        m = int(row["gps_minute"])
                        s = int(row["gps_second"])
                        ms = int(row["gps_millisecond"])
                        cst_sec = h * 3600 + m * 60 + s + ms / 1000.0
                        best = {
                            "lat": float(row["latitude"]),
                            "lon": float(row["longitude"]),
                            "alt": float(row.get("altitude", 0) or 0),
                            "heading": float(row.get("true_heading_deg", 0) or 0),
                            "rel_time": t,
                            "cst_sec": cst_sec,
                        }
                    except (KeyError, ValueError):
                        continue
        return best
    except Exception:
        return None


def _download_sat_tile(tx: int, ty: int, z: int) -> bytes | None:
    """Download a single AMap satellite tile, with cache."""
    import urllib.request
    cache_dir = Path("temp/sat_tiles")
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"{z}_{tx}_{ty}.jpg"
    if cache_path.exists():
        return cache_path.read_bytes()
    for n in (1, 2, 3, 4):
        url = _AMAP_SAT_URL.format(n=n, x=tx, y=ty, z=z)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AutoLabeling/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = resp.read()
                if len(data) > 500:
                    cache_path.write_bytes(data)
                    return data
        except Exception:
            continue
    return None


@router.get("/lidar_bev_map")
def serve_lidar_bev_map(
    seg_path: str = Query(..., description="Segment path"),
    frame_id: str = Query(..., description="Camera frame filename for GPS matching"),
):
    """Serve satellite map with overlaid LiDAR point cloud (top-down view).

    Downloads AMap satellite tiles around the GPS coordinates from
    nav100_state.csv, then renders the PCD point cloud as a coloured overlay
    on top of the aerial imagery.  Returns a 1×1 transparent PNG when data
    is unavailable.
    """
    import cv2
    import numpy as np
    import urllib.request

    root_path = _dataset_root(DATASET_ROOT).resolve()
    seg_dir = root_path / Path(*seg_path.split("/"))
    if not seg_dir.exists():
        return _empty_bev_response()

    # ── Get GPS fix ────────────────────────────────────────────────────
    cam_ts = _parse_camera_rel_time(frame_id)
    if cam_ts is None:
        return _empty_bev_response()
    gps = _read_gps_for_frame(seg_dir, cam_ts)
    if gps is None:
        return _empty_bev_response()

    # ── Satellite tile mosaic ───────────────────────────────────────────
    # Auto-select the highest zoom that keeps the mosaic ≤ _MAX_MOSAIC_PX per side
    gcj_lat, gcj_lon = _wgs84_to_gcj02(gps["lat"], gps["lon"])
    map_range_m = _MAP_RANGE_M
    auto_zoom = 10  # fallback minimum
    for z in range(18, 9, -1):
        mpp = _meters_per_px(gcj_lat, z)
        needed_px = int(map_range_m / mpp)
        if needed_px <= _MAX_MOSAIC_PX:
            auto_zoom = z
            break
    mpp = _meters_per_px(gcj_lat, auto_zoom)
    logger.info("BEV map: zoom=%d mpp=%.2f range=%dm tiles=%d",
                auto_zoom, mpp, map_range_m, map_range_m / (mpp * _AMAP_TILE_SIZE))
    map_px = int(map_range_m / mpp)
    tiles_per_side = (map_px + _AMAP_TILE_SIZE - 1) // _AMAP_TILE_SIZE
    half_tiles = (tiles_per_side + 1) // 2  # ceil(tiles/2) covers center ± range
    map_px = tiles_per_side * _AMAP_TILE_SIZE

    # Center tile
    ctx, cty = _ll2tile(gcj_lon, gcj_lat, auto_zoom)
    # Tile range covering ±half_tiles around center
    tx0, tx1 = ctx - half_tiles, ctx + half_tiles
    ty0, ty1 = cty - half_tiles, cty + half_tiles

    mosaic_w = (tx1 - tx0 + 1) * _AMAP_TILE_SIZE
    mosaic_h = (ty1 - ty0 + 1) * _AMAP_TILE_SIZE
    if mosaic_w < 256 or mosaic_h < 256:
        return _empty_bev_response()

    total_tiles = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    if total_tiles > _MAX_TOTAL_TILES:
        return _empty_bev_response()
    mosaic = np.zeros((mosaic_h, mosaic_w, 3), dtype=np.uint8)
    tiles_ok = 0
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            data = _download_sat_tile(tx, ty, auto_zoom)
            if data is not None:
                import io
                from PIL import Image
                try:
                    tile_img = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))
                    px = (tx - tx0) * _AMAP_TILE_SIZE
                    py = (ty - ty0) * _AMAP_TILE_SIZE
                    h, w = min(tile_img.shape[0], mosaic_h - py), min(tile_img.shape[1], mosaic_w - px)
                    if h > 0 and w > 0:
                        mosaic[py:py+h, px:px+w] = tile_img[:h, :w]
                        tiles_ok += 1
                except Exception:
                    pass
    if tiles_ok == 0:
        return _empty_bev_response()

    # ── Center pixel of the mosaic (GPS location) ──────────────────────
    # Float tile coords of GCJ center
    import math
    n = 2 ** auto_zoom
    ctx_f = (gcj_lon + 180) / 360 * n
    lat_r = math.radians(gcj_lat)
    cty_f = (1 - math.log(math.tan(lat_r) + 1/math.cos(lat_r)) / math.pi) / 2 * n
    center_px = (ctx_f - tx0) * _AMAP_TILE_SIZE   # col
    center_py = (cty_f - ty0) * _AMAP_TILE_SIZE   # row

    # ── mmWave radar detections from bin ────────────────────────────────
    capture_dir = seg_dir
    for _ in range(4):  # walk up from segment to capture
        if _find_bin_file(capture_dir):
            break
        capture_dir = capture_dir.parent

    radar_dets = None
    bin_path = _find_bin_file(capture_dir) if capture_dir != seg_dir else None
    if bin_path is not None:
        try:
            # Sample radar packets across the capture (skip time alignment
            # complexity — bin and camera have independent clocks).
            # Read ~600 packets spread evenly through the file for coverage.
            radar_dets = _sample_bin_detections(bin_path, max_packets=600)
            if radar_dets:
                logger.info("Radar: %d detections from %s",
                            len(radar_dets), bin_path.name)
        except Exception as exc:
            logger.debug("Radar bin scan failed: %s", exc)

    # ── Overlay radar detections on satellite map ────────────────────────
    if radar_dets and len(radar_dets) > 0:
        # Filter: keep strongest detection per ~10m grid cell
        grid: dict[tuple[int, int], dict] = {}
        for d in radar_dets:
            # GCJ02 lat/lon → pixel
            gcj_tgt_lat, gcj_tgt_lon = _wgs84_to_gcj02(d["lat"], d["lon"])
            tgt_lat_r = math.radians(gcj_tgt_lat)
            tgt_ty = (1 - math.log(math.tan(tgt_lat_r) + 1/math.cos(tgt_lat_r)) / math.pi) / 2 * n
            tgt_tx = (gcj_tgt_lon + 180) / 360 * n
            tgt_col = int((tgt_tx - tx0) * _AMAP_TILE_SIZE)
            tgt_row = int((tgt_ty - ty0) * _AMAP_TILE_SIZE)

            if 0 <= tgt_col < mosaic_w and 0 <= tgt_row < mosaic_h:
                grid_key = (tgt_col // 3, tgt_row // 3)
                if grid_key not in grid or d["signal_db"] > grid[grid_key]["signal_db"]:
                    grid[grid_key] = {**d, "col": tgt_col, "row": tgt_row}

        # Draw detections as coloured circles (signal strength → colour)
        sig_vals = [v["signal_db"] for v in grid.values()]
        sig_lo = float(np.percentile(sig_vals, 10)) if len(sig_vals) > 1 else _BIN_MIN_SIGNAL_DB
        sig_hi = float(np.percentile(sig_vals, 90)) if len(sig_vals) > 1 else max(sig_vals)
        sig_span = max(sig_hi - sig_lo, 1.0)

        radius = 2
        for det in grid.values():
            sig_norm = np.clip((det["signal_db"] - sig_lo) / sig_span, 0, 1)
            # Green (weak) → Yellow → Red (strong)
            r_val = int(sig_norm * 255)
            g_val = int((1 - abs(sig_norm - 0.5) * 2) * 255)
            b_val = int((1 - sig_norm) * 128)
            r0 = max(0, det["row"] - radius)
            r1 = min(mosaic_h - 1, det["row"] + radius)
            c0 = max(0, det["col"] - radius)
            c1 = min(mosaic_w - 1, det["col"] + radius)
            # Draw filled circle
            rr, cc = np.ogrid[r0:r1+1, c0:c1+1]
            mask = (rr - det["row"])**2 + (cc - det["col"])**2 <= radius**2
            alpha = 0.75
            for ch in range(3):
                overlay_val = [r_val, g_val, b_val][ch]
                mosaic[r0:r1+1, c0:c1+1][mask, ch] = (
                    alpha * overlay_val + (1 - alpha) * mosaic[r0:r1+1, c0:c1+1][mask, ch]
                ).astype(np.uint8)

    # Draw GPS center marker
    cx, cy = int(center_px), int(center_py)
    cv2.drawMarker(mosaic, (cx, cy), (0, 255, 255),
                   cv2.MARKER_CROSS, max(10, mosaic_w//30), 2)

    # ── Crop to fixed output size ──────────────────────────────────────
    out_size = 512
    x_start = max(0, int(center_px - out_size // 2))
    y_start = max(0, int(center_py - out_size // 2))
    x_end = min(mosaic_w, x_start + out_size)
    y_end = min(mosaic_h, y_start + out_size)
    crop = mosaic[y_start:y_end, x_start:x_end]
    # Pad if crop is smaller than out_size
    if crop.shape[0] < out_size or crop.shape[1] < out_size:
        padded = np.zeros((out_size, out_size, 3), dtype=np.uint8)
        padded[:crop.shape[0], :crop.shape[1]] = crop
        crop = padded

    _, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    return Response(content=buf.tobytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "public, max-age=120"})


@router.get("/lidar_bev_data")
def serve_lidar_bev_data(
    seg_path: str = Query(..., description="Segment path"),
    frame_id: str = Query(..., description="Camera frame filename for GPS matching"),
):
    """Return GPS position + radar detections as JSON for frontend AMap display.

    Coordinates are converted from WGS-84 to GCJ-02 for AMap compatibility.
    The frontend uses this data to place markers on an interactive AMap JS API map.
    """
    import math as _math
    import numpy as np

    root_path = _dataset_root(DATASET_ROOT).resolve()
    seg_dir = root_path / Path(*seg_path.split("/"))
    if not seg_dir.exists():
        return {"gps": None, "detections": [], "error": "segment not found"}

    # ── Get GPS fix ────────────────────────────────────────────────────
    cam_ts = _parse_camera_rel_time(frame_id)
    if cam_ts is None:
        return {"gps": None, "detections": [], "error": "no camera timestamp"}
    gps = _read_gps_for_frame(seg_dir, cam_ts)
    if gps is None:
        return {"gps": None, "detections": [], "error": "no GPS data"}

    # Convert WGS-84 → GCJ-02 for AMap
    gcj_lat, gcj_lon = _wgs84_to_gcj02(gps["lat"], gps["lon"])

    # ── Full drone GPS trajectory ────────────────────────────────────────
    gps_path = _read_drone_gps_path(seg_dir)

    # ── mmWave radar detections from bin ────────────────────────────────
    capture_dir = seg_dir
    for _ in range(4):
        if _find_bin_file(capture_dir):
            break
        capture_dir = capture_dir.parent

    detections = []
    bin_path = _find_bin_file(capture_dir) if capture_dir != seg_dir else None
    if bin_path is not None:
        try:
            all_dets = _sample_bin_detections(bin_path, max_packets=600)
            for d in all_dets:
                dlat_gcj, dlon_gcj = _wgs84_to_gcj02(d["lat"], d["lon"])
                detections.append({
                    "lat": dlat_gcj,
                    "lon": dlon_gcj,
                    "signal_db": d["signal_db"],
                    "range_m": d["range_m"],
                    "az_deg": d["az_deg"],
                })
        except Exception as exc:
            logger.debug("Radar bin scan failed for /lidar_bev_data: %s", exc)

    # Subsample path to at most 200 points for rendering
    path_subsampled = _subsample_path(gps_path, 200) if gps_path else []

    return {
        "gps": {
            "lat": gcj_lat,
            "lon": gcj_lon,
            "alt": gps["alt"],
            "heading": gps["heading"],
            "camera_heading": (gps["heading"] - 90.0) % 360.0,
        },
        "detections": detections,
        "drone_path": path_subsampled,
    }


def _empty_bev_response() -> Response:
    """Return a minimal transparent PNG so the frontend stays quiet."""
    # 1×1 transparent grey PNG
    import zlib
    def _chunk(ctype, data):
        c = ctype + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\x00\x00"
    idat = zlib.compress(raw)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    return Response(content=png, media_type="image/png",
                    headers={"Cache-Control": "no-cache"})


@router.get("/cameras")
async def list_cameras():
    """List available camera types."""
    return {"cameras": [
        {"key": k, "dir": v, "label": f"{k} ({v})"}
        for k, v in CAMERA_DIRS.items()
    ]}
