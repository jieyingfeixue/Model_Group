"""Map 3D bounding boxes onto 4D mmWave radar tensors."""

from __future__ import annotations

import logging

import numpy as np

from src.core.types import Label3D, RadarROI

logger = logging.getLogger(__name__)


class RadarProjector:
    """Project 3D boxes to radar tensor coordinates and extract power stats."""

    def __init__(
        self,
        range_res: float = 0.4,
        azimuth_res: float = 1.0,
        elevation_res: float = 1.0,
        range_offset: float = 0.0,
    ):
        self.range_res = range_res
        self.azimuth_res = np.deg2rad(azimuth_res)
        self.elevation_res = np.deg2rad(elevation_res)
        self.range_offset = range_offset

    def map_boxes(self, boxes: list[Label3D], radar_tensor: np.ndarray) -> list[RadarROI]:
        """Compute radar ROI for each box."""
        rois = []
        for box in boxes:
            roi = self.project_box(box, radar_tensor)
            rois.append(roi)
        return rois

    def project_box(self, box: Label3D, radar_tensor: np.ndarray) -> RadarROI:
        """Project a single 3D box to the radar tensor and extract the ROI."""
        if radar_tensor is None or radar_tensor.size == 0:
            return RadarROI()

        corners = box.corners()  # 8×3
        # Convert to spherical (range, azimuth, elevation)
        ranges = np.linalg.norm(corners[:, :2], axis=1)
        azimuths = np.arctan2(corners[:, 1], corners[:, 0])
        elevations = np.arctan2(corners[:, 2], np.linalg.norm(corners[:, :2], axis=1))

        r_min, r_max = ranges.min(), ranges.max()
        a_min, a_max = azimuths.min(), azimuths.max()
        e_min, e_max = elevations.min(), elevations.max()

        # Convert to tensor indices
        shape = radar_tensor.shape  # (Z, Y, X) or (D, R, A, E)
        if len(shape) == 3:
            # ZYX cube: index 0=elevation, 1=azimuth (range), 2=range
            nz, ny, nx = shape
            ri_min = max(0, int((r_min - self.range_offset) / self.range_res))
            ri_max = min(nx - 1, int((r_max - self.range_offset) / self.range_res))
            ai_min = max(0, int((a_min + np.pi) / self.azimuth_res))
            ai_max = min(ny - 1, int((a_max + np.pi) / self.azimuth_res))
            ei_min = max(0, int((e_min + np.pi / 2) / self.elevation_res))
            ei_max = min(nz - 1, int((e_max + np.pi / 2) / self.elevation_res))

            roi_slice = radar_tensor[ei_min:ei_max + 1, ai_min:ai_max + 1, ri_min:ri_max + 1]
        else:
            roi_slice = np.array([])

        max_power = float(roi_slice.max()) if roi_slice.size > 0 else 0.0
        mean_power = float(roi_slice.mean()) if roi_slice.size > 0 else 0.0

        return RadarROI(
            tensor=roi_slice,
            stats={"max_power": max_power, "mean_power": mean_power, "voxels": roi_slice.size},
        )


def compute_radar_stats(
    radar_tensor: np.ndarray | None, box: Label3D, radar_config: dict | None = None
) -> dict[str, float]:
    """Convenience: compute radar stats for a single box."""
    proj = RadarProjector(**(radar_config or {}))
    roi = proj.project_box(box, radar_tensor if radar_tensor is not None else np.array([]))
    return roi.stats
