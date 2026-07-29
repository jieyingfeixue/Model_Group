"""Constants and class-size priors."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SizePrior:
    """Expected (L, W, H) mean and std for a class (metres)."""
    mean: np.ndarray
    std: np.ndarray


# Priors based on K-Radar / nuScenes / KITTI statistics
CLASS_SIZE_PRIORS: dict[str, SizePrior] = {
    "Sedan": SizePrior(mean=np.array([4.5, 1.8, 1.5]), std=np.array([0.4, 0.15, 0.15])),
    "Bus or Truck": SizePrior(mean=np.array([8.5, 2.5, 3.2]), std=np.array([2.0, 0.3, 0.5])),
    "Motorcycle": SizePrior(mean=np.array([2.0, 0.8, 1.5]), std=np.array([0.3, 0.15, 0.2])),
    "Bicycle": SizePrior(mean=np.array([1.7, 0.6, 1.1]), std=np.array([0.2, 0.1, 0.15])),
    "Bicycle Group": SizePrior(mean=np.array([2.5, 1.5, 1.4]), std=np.array([0.5, 0.3, 0.2])),
    "Pedestrian": SizePrior(mean=np.array([0.8, 0.6, 1.75]), std=np.array([0.15, 0.1, 0.15])),
    "Pedestrian Group": SizePrior(mean=np.array([2.0, 2.0, 1.75]), std=np.array([0.5, 0.5, 0.2])),
    "car": SizePrior(mean=np.array([4.5, 1.8, 1.5]), std=np.array([0.4, 0.15, 0.15])),
    "truck": SizePrior(mean=np.array([8.5, 2.5, 3.2]), std=np.array([2.0, 0.3, 0.5])),
    "bus": SizePrior(mean=np.array([10.0, 2.5, 3.5]), std=np.array([2.0, 0.3, 0.5])),
    "pedestrian": SizePrior(mean=np.array([0.8, 0.6, 1.75]), std=np.array([0.15, 0.1, 0.15])),
    "cyclist": SizePrior(mean=np.array([1.7, 0.6, 1.7]), std=np.array([0.25, 0.1, 0.15])),
    # Infrastructure / custom classes
    "Street Light": SizePrior(mean=np.array([0.3, 0.3, 5.0]), std=np.array([0.1, 0.1, 1.0])),
    "路灯": SizePrior(mean=np.array([0.3, 0.3, 5.0]), std=np.array([0.1, 0.1, 1.0])),
    "Traffic Cone": SizePrior(mean=np.array([0.4, 0.4, 0.8]), std=np.array([0.05, 0.05, 0.1])),
    "交通锥": SizePrior(mean=np.array([0.4, 0.4, 0.8]), std=np.array([0.05, 0.05, 0.1])),
    "Traffic Sign": SizePrior(mean=np.array([0.6, 0.1, 1.2]), std=np.array([0.2, 0.05, 0.3])),
    "交通标志": SizePrior(mean=np.array([0.6, 0.1, 1.2]), std=np.array([0.2, 0.05, 0.3])),
    "Barrier": SizePrior(mean=np.array([1.5, 0.5, 1.0]), std=np.array([0.3, 0.1, 0.15])),
    "隔离墩": SizePrior(mean=np.array([1.5, 0.5, 1.0]), std=np.array([0.3, 0.1, 0.15])),
}

# Default colours per class (RGBA 0-255)
CLASS_COLORS: dict[str, tuple[int, int, int, int]] = {
    "Sedan": (0, 255, 0, 200),
    "Bus or Truck": (255, 128, 0, 200),
    "Motorcycle": (0, 128, 255, 200),
    "Bicycle": (255, 255, 0, 200),
    "Bicycle Group": (200, 200, 0, 200),
    "Pedestrian": (255, 0, 0, 200),
    "Pedestrian Group": (255, 64, 64, 200),
    "car": (0, 255, 0, 200),
    "truck": (255, 128, 0, 200),
    "bus": (255, 160, 0, 200),
    "pedestrian": (255, 0, 0, 200),
    "cyclist": (0, 128, 255, 200),
}

DEFAULT_CLASS_NAMES = [
    "Sedan",
    "Bus or Truck",
    "Motorcycle",
    "Bicycle",
    "Bicycle Group",
    "Pedestrian",
    "Pedestrian Group",
    "Street Light",
    "Traffic Cone",
    "Traffic Sign",
    "Barrier",
]

# Stage names for the pipeline progress bar
STAGES = ["detect", "project", "lidar_fit", "radar_map", "agent"]
STAGE_LABELS = {
    "detect": "① 检测",
    "project": "② 投影",
    "lidar_fit": "③ LiDAR",
    "radar_map": "④ Radar",
    "agent": "⑤ Agent",
}
