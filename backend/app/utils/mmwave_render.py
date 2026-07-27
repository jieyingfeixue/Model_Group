"""毫米波 .mat → 距离-方位热力图 PNG（与激光雷达 BEV 一样在接口侧现算）。"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image


def _extract_heatmap(data_ori_item: Any) -> np.ndarray:
    """Data_Ori[i] = [scalar, angles(76,), heatmap(666,76), heatmap2, dets(76,7)]"""
    item = data_ori_item
    if isinstance(item, np.ndarray) and item.dtype == object:
        item = list(item)
    heat = np.asarray(item[2], dtype=np.float32)
    if heat.ndim != 2:
        raise ValueError(f"Unexpected mmwave heatmap shape: {heat.shape}")
    return heat


def load_mmwave_heatmap_from_mat(mat_bytes: bytes, frame_index: int) -> np.ndarray:
    import scipy.io as sio

    bio = BytesIO(mat_bytes)
    raw = sio.loadmat(bio, simplify_cells=True)
    if "Data_Ori" not in raw:
        raise ValueError("MAT missing Data_Ori")
    arr = raw["Data_Ori"]
    n = len(arr)
    if frame_index < 0 or frame_index >= n:
        raise ValueError(f"mmwave frame_index {frame_index} out of range 0..{n-1}")
    return _extract_heatmap(arr[frame_index])


def render_heatmap_png(heat: np.ndarray, image_size: tuple[int, int] = (512, 448)) -> bytes:
    """把距离-方位热力图渲染为伪彩色 PNG。"""
    h = np.array(heat, dtype=np.float64)
    h = np.nan_to_num(h, nan=0.0, posinf=0.0, neginf=0.0)
    lo, hi = np.percentile(h, (2, 98))
    if hi <= lo:
        hi = lo + 1.0
    norm = np.clip((h - lo) / (hi - lo), 0, 1)

    # 简单 turbo 风格：蓝 → 青 → 黄 → 红
    t = norm
    r = np.clip(1.5 * t - 0.2, 0, 1)
    g = np.clip(1.5 - abs(1.5 * t - 0.75) * 1.2, 0, 1)
    b = np.clip(1.2 - 1.4 * t, 0, 1)
    rgb = np.stack([r, g, b], axis=-1)
    rgb = (rgb * 255).astype(np.uint8)

    img = Image.fromarray(rgb, mode="RGB")
    # 转置后更接近「横轴方位、纵轴距离」的常见雷达图；再缩放到目标尺寸
    img = img.transpose(Image.Transpose.ROTATE_90)
    img = img.resize(image_size, Image.Resampling.BILINEAR)
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def mat_bytes_to_mmwave_png(mat_bytes: bytes, frame_index: int = 0, image_size: tuple[int, int] = (512, 448)) -> bytes:
    heat = load_mmwave_heatmap_from_mat(mat_bytes, frame_index)
    return render_heatmap_png(heat, image_size=image_size)
