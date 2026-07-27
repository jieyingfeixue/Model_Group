"""将 MinIO / 本地 .pcd 点云渲染为鸟瞰俯视图 (BEV) PNG。"""

from __future__ import annotations

from io import BytesIO
from typing import Any

import numpy as np
from PIL import Image


def _parse_pcd_header(data: bytes) -> tuple[dict[str, Any], int]:
    """解析 PCD 头，返回 (meta, data_offset)。"""
    meta: dict[str, Any] = {}
    offset = 0
    while offset < len(data):
        nl = data.find(b"\n", offset)
        if nl < 0:
            break
        line = data[offset:nl].decode("ascii", errors="ignore").strip()
        offset = nl + 1
        if not line or line.startswith("#"):
            continue
        key, _, rest = line.partition(" ")
        key = key.upper()
        if key == "VERSION":
            meta["version"] = rest.strip()
        elif key == "FIELDS":
            meta["fields"] = rest.split()
        elif key == "SIZE":
            meta["size"] = [int(x) for x in rest.split()]
        elif key == "TYPE":
            meta["type"] = rest.split()
        elif key == "COUNT":
            meta["count"] = [int(x) for x in rest.split()]
        elif key == "WIDTH":
            meta["width"] = int(rest)
        elif key == "HEIGHT":
            meta["height"] = int(rest)
        elif key == "POINTS":
            meta["points"] = int(rest)
        elif key == "DATA":
            meta["data"] = rest.strip().lower()
            break
    if "fields" not in meta or "data" not in meta:
        raise ValueError("Invalid PCD header")
    return meta, offset


_TYPE_MAP = {
    ("F", 4): "f4",
    ("F", 8): "f8",
    ("U", 1): "u1",
    ("U", 2): "u2",
    ("U", 4): "u4",
    ("I", 1): "i1",
    ("I", 2): "i2",
    ("I", 4): "i4",
}


def _build_dtype(meta: dict[str, Any]) -> np.dtype:
    fields = meta["fields"]
    sizes = meta["size"]
    types = meta["type"]
    counts = meta.get("count") or [1] * len(fields)
    names: list[str] = []
    formats: list[str] = []
    offsets: list[int] = []
    pos = 0
    for name, size, typ, count in zip(fields, sizes, types, counts):
        fmt = _TYPE_MAP.get((typ.upper(), size))
        if fmt is None:
            raise ValueError(f"Unsupported PCD field: {name} {typ}{size}")
        for i in range(count):
            field_name = name if count == 1 else f"{name}_{i}"
            names.append(field_name)
            formats.append(fmt)
            offsets.append(pos)
            pos += size
    return np.dtype({"names": names, "formats": formats, "offsets": offsets, "itemsize": pos})


def load_pcd_xyzi(data: bytes, max_points: int = 250_000) -> np.ndarray:
    """从 PCD 字节读取点，返回 shape (N, 4) = x,y,z,intensity。"""
    meta, offset = _parse_pcd_header(data)
    n_points = int(meta.get("points") or meta.get("width") or 0)
    if n_points <= 0:
        raise ValueError("PCD has no points")

    dtype = _build_dtype(meta)
    payload = data[offset:]

    if meta["data"] == "ascii":
        text = payload.decode("ascii", errors="ignore").strip().splitlines()
        rows = []
        for line in text:
            parts = line.split()
            if len(parts) < 3:
                continue
            x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
            inten = float(parts[3]) if len(parts) > 3 else z
            rows.append((x, y, z, inten))
        arr = np.asarray(rows, dtype=np.float32)
    elif meta["data"] in ("binary", "binary_compressed"):
        if meta["data"] == "binary_compressed":
            raise ValueError("binary_compressed PCD not supported yet")
        need = n_points * dtype.itemsize
        if len(payload) < need:
            raise ValueError("PCD binary payload truncated")
        structured = np.frombuffer(payload[:need], dtype=dtype)
        names = structured.dtype.names or ()
        x = structured["x"] if "x" in names else structured[names[0]]
        y = structured["y"] if "y" in names else structured[names[1]]
        z = structured["z"] if "z" in names else structured[names[2]]
        if "intensity" in names:
            inten = structured["intensity"]
        elif "reflectance" in names:
            inten = structured["reflectance"]
        else:
            inten = z
        arr = np.column_stack([x, y, z, inten]).astype(np.float32)
    else:
        raise ValueError(f"Unsupported PCD DATA mode: {meta['data']}")

    # 过滤 NaN / Inf
    mask = np.isfinite(arr).all(axis=1)
    arr = arr[mask]
    if arr.size == 0:
        raise ValueError("No valid points after filtering")

    # AT360 等雷达 PCD 常含大量 (0,0,0) 占位，必须去掉，否则分位数视野会崩
    rng = np.sqrt(arr[:, 0] ** 2 + arr[:, 1] ** 2 + arr[:, 2] ** 2)
    arr = arr[rng > 0.5]
    if arr.shape[0] == 0:
        raise ValueError("No valid points after removing origin placeholders")

    # 降采样（随机，避免只取等间隔扫线）
    if arr.shape[0] > max_points:
        idx = np.random.default_rng(0).choice(arr.shape[0], size=max_points, replace=False)
        arr = arr[idx]
    return arr


def render_bev_png(
    points: np.ndarray,
    image_size: int = 768,
    max_range: float | None = None,
) -> bytes:
    """把 (N,4) xyzi 点云投影成俯视图 PNG。

    以点云主体（中位数）为中心做等比例正方形视野；按高度着色并叠加密度。
    AT360 部分帧有效点远离原点，不能死盯 (0,0)。
    """
    xy = points[:, :2].astype(np.float64)
    z = points[:, 2].astype(np.float64)

    # 先去掉极端高度离群
    z_lo, z_hi = np.percentile(z, (1, 99))
    keep = (z >= z_lo - 1.0) & (z <= z_hi + 1.0)
    xy, z = xy[keep], z[keep]
    if xy.shape[0] < 50:
        raise ValueError("Too few points after height filter")

    cx = float(np.median(xy[:, 0]))
    cy = float(np.median(xy[:, 1]))
    dx = np.abs(xy[:, 0] - cx)
    dy = np.abs(xy[:, 1] - cy)

    if max_range is None:
        half = float(max(np.percentile(dx, 98), np.percentile(dy, 98)))
        # 稍留边，并限制视野尺度
        half = float(np.clip(half * 1.05, 25.0, 180.0))
    else:
        half = float(max_range)

    in_view = (dx <= half) & (dy <= half)
    xy = xy[in_view]
    z = z[in_view]
    if xy.shape[0] < 50:
        raise ValueError("Too few points in BEV range")

    # 正方形网格：相对中心，x 向右, y 向上
    scale = (image_size - 1) / (2.0 * half)
    u = ((xy[:, 0] - cx + half) * scale).astype(np.int32)
    v = ((half - (xy[:, 1] - cy)) * scale).astype(np.int32)
    valid_pix = (u >= 0) & (u < image_size) & (v >= 0) & (v < image_size)
    u, v, z = u[valid_pix], v[valid_pix], z[valid_pix]

    height = np.full((image_size, image_size), np.nan, dtype=np.float32)
    density = np.zeros((image_size, image_size), dtype=np.float32)
    flat = v.astype(np.int64) * image_size + u.astype(np.int64)
    np.add.at(density.ravel(), flat, 1.0)
    order = np.argsort(z)
    height.ravel()[flat[order]] = z[order].astype(np.float32)

    occupied = density > 0
    if not occupied.any():
        raise ValueError("Empty BEV grid")

    zh = height[occupied]
    z0, z1 = np.percentile(zh, (5, 95))
    if z1 <= z0:
        z1 = z0 + 1.0
    h_norm = np.zeros_like(height, dtype=np.float32)
    h_norm[occupied] = np.clip((height[occupied] - z0) / (z1 - z0), 0, 1)

    d_norm = np.zeros_like(density, dtype=np.float32)
    d_norm[occupied] = np.clip(
        np.log1p(density[occupied]) / np.log1p(float(density[occupied].max())), 0, 1
    )

    t = h_norm
    bright = 0.35 + 0.65 * d_norm
    rgb = np.zeros((image_size, image_size, 3), dtype=np.float32)
    rgb[..., 0] = np.clip(1.4 * t - 0.1, 0, 1) * bright
    rgb[..., 1] = np.clip(1.2 * t + 0.15, 0, 1) * bright
    rgb[..., 2] = np.clip(1.0 - 0.7 * t, 0.15, 1) * bright
    out = (rgb * 255).astype(np.uint8)
    out[~occupied] = (8, 10, 18)

    # 中心十字（点云主体中心）
    c = image_size // 2
    out[max(0, c - 6) : c + 7, c, :] = (255, 80, 80)
    out[c, max(0, c - 6) : c + 7, :] = (255, 80, 80)

    img = Image.fromarray(out, mode="RGB")
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def pcd_bytes_to_bev_png(pcd_bytes: bytes, image_size: int = 768) -> bytes:
    points = load_pcd_xyzi(pcd_bytes)
    return render_bev_png(points, image_size=image_size)
