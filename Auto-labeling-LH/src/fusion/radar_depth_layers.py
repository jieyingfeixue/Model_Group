"""Robust radar depth selection from an image-box azimuth cone."""

from __future__ import annotations

import math

import numpy as np


MIN_VISIBLE_DEPTH_M = 400.0
MAX_RADAR_DEPTH_M = 4000.0


def cluster_depth_layers(
    distances_m: np.ndarray,
    strengths_db: np.ndarray,
    azimuth_errors_deg: np.ndarray | None = None,
) -> list[dict]:
    """Split cone points into near/middle/far layers using adaptive 1D gaps."""
    dist = np.asarray(distances_m, dtype=np.float64)
    strength = np.asarray(strengths_db, dtype=np.float64)
    az_err = (
        np.zeros_like(dist)
        if azimuth_errors_deg is None
        else np.asarray(azimuth_errors_deg, dtype=np.float64)
    )
    valid = (
        np.isfinite(dist)
        & np.isfinite(strength)
        & np.isfinite(az_err)
        & (dist >= MIN_VISIBLE_DEPTH_M)
        & (dist < MAX_RADAR_DEPTH_M)
    )
    if not valid.any():
        return []

    dist, strength, az_err = dist[valid], strength[valid], np.abs(az_err[valid])
    order = np.argsort(dist)
    dist, strength, az_err = dist[order], strength[order], az_err[order]

    split_at = [0]
    for i, gap in enumerate(np.diff(dist), start=1):
        gap_limit = max(45.0, 0.055 * min(dist[i - 1], dist[i]))
        if gap > gap_limit:
            split_at.append(i)
    split_at.append(len(dist))

    layers = []
    for start, end in zip(split_at[:-1], split_at[1:]):
        d = dist[start:end]
        s = strength[start:end]
        a = az_err[start:end]
        if len(d) == 0:
            continue
        # Undo free-space loss rather than rewarding close strong clutter.
        compensated = s + 40.0 * np.log10(np.maximum(d, 1.0) / MIN_VISIBLE_DEPTH_M)
        layers.append({
            "depth_m": float(np.median(d)),
            "n_points": int(len(d)),
            "strength_db": float(np.percentile(compensated, 75)),
            "az_error_deg": float(np.median(a)),
            "spread_m": float(np.percentile(d, 75) - np.percentile(d, 25)),
        })
    return layers


def select_depth_layer(
    distances_m: np.ndarray,
    strengths_db: np.ndarray,
    azimuth_errors_deg: np.ndarray | None = None,
    previous_depth_m: float | None = None,
) -> dict | None:
    """Choose a stable distance layer, returning its median depth and diagnostics."""
    layers = cluster_depth_layers(distances_m, strengths_db, azimuth_errors_deg)
    if not layers:
        return None

    strengths = np.asarray([x["strength_db"] for x in layers], dtype=np.float64)
    strength_mid = float(np.median(strengths))
    strength_scale = max(float(np.std(strengths)), 6.0)

    for layer in layers:
        score = 2.2 * math.log1p(layer["n_points"])
        score += (layer["strength_db"] - strength_mid) / strength_scale
        score -= 0.12 * layer["az_error_deg"]
        score -= min(layer["spread_m"] / 250.0, 1.5)
        if previous_depth_m and previous_depth_m >= MIN_VISIBLE_DEPTH_M:
            relative_error = abs(layer["depth_m"] - previous_depth_m) / previous_depth_m
            score += 5.0 * math.exp(-relative_error / 0.12)
        layer["score"] = float(score)

    return max(layers, key=lambda x: x["score"])
