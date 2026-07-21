"""质量检查规则引擎 — 5 项自动检测

check_bbox_bounds       — 坐标越界
check_bbox_area         — 面积异常（极小框 / 过大框）
check_bbox_aspect_ratio — 宽高比异常
check_duplicate_bboxes  — 同类别多框高度重叠（IoU > 0.9）
check_depth_range       — 深度值合理性（0~500m）
"""

from __future__ import annotations

from typing import Any


def check_bbox_bounds(
    bboxes: list[dict[str, Any]],
    img_width: int,
    img_height: int,
) -> list[dict[str, Any]]:
    """检查标注框坐标越界。

    规则：x < 0 或 x > img_width 或 y < 0 或 y > img_height → 标记为异常。
    注意：输入坐标为归一化 0~1，img_width/img_height 用于换算。
    归一化坐标中，x < 0 或 x > 1 即为越界。
    """
    issues: list[dict[str, Any]] = []
    for i, bbox in enumerate(bboxes):
        x, y, w, h = bbox.get("x", 0), bbox.get("y", 0), bbox.get("w", 0), bbox.get("h", 0)
        out_of_bounds = []
        if not (0.0 <= x <= 1.0):
            out_of_bounds.append(f"x={x}")
        if not (0.0 <= y <= 1.0):
            out_of_bounds.append(f"y={y}")
        if not (0.0 < w <= 1.0):
            out_of_bounds.append(f"w={w}")
        if not (0.0 < h <= 1.0):
            out_of_bounds.append(f"h={h}")

        if out_of_bounds:
            issues.append({
                "bbox_index": i,
                "category_id": bbox.get("category_id", ""),
                "issue": "out_of_bounds",
                "detail": f"坐标越界: {', '.join(out_of_bounds)}",
            })
    return issues


def check_bbox_area(
    bboxes: list[dict[str, Any]],
    img_width: int,
    img_height: int,
) -> list[dict[str, Any]]:
    """检查标注框面积异常。

    规则：
    - 面积 < 图像面积 0.01%（极小框，可能是误标点）
    - 面积 > 图像面积 80%（过大框，可能是错误标注整个画面）
    """
    if img_width <= 0 or img_height <= 0:
        return []

    img_area = img_width * img_height
    min_area = img_area * 0.0001  # 0.01%
    max_area = img_area * 0.8     # 80%

    issues: list[dict[str, Any]] = []
    for i, bbox in enumerate(bboxes):
        w, h = bbox.get("w", 0), bbox.get("h", 0)
        # 归一化面积 × 图像面积 = 实际像素面积
        bbox_area = w * h * img_area
        if bbox_area < min_area:
            issues.append({
                "bbox_index": i,
                "category_id": bbox.get("category_id", ""),
                "issue": "too_small",
                "detail": f"框面积 {bbox_area:.0f}px < 图像面积的 0.01%（{min_area:.0f}px）",
            })
        elif bbox_area > max_area:
            issues.append({
                "bbox_index": i,
                "category_id": bbox.get("category_id", ""),
                "issue": "too_large",
                "detail": f"框面积 {bbox_area:.0f}px > 图像面积的 80%（{max_area:.0f}px）",
            })
    return issues


def check_bbox_aspect_ratio(bboxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """检查标注框宽高比异常。

    规则：宽 > 高 × 5（极端横向框，可能误标）。
    """
    issues: list[dict[str, Any]] = []
    for i, bbox in enumerate(bboxes):
        w, h = bbox.get("w", 0), bbox.get("h", 0)
        if h > 0 and w / h > 5:
            issues.append({
                "bbox_index": i,
                "category_id": bbox.get("category_id", ""),
                "issue": "aspect_ratio_anomaly",
                "detail": f"宽高比 w/h={w/h:.2f} > 5",
            })
    return issues


def check_duplicate_bboxes(
    bboxes: list[dict[str, Any]],
    iou_threshold: float = 0.9,
) -> list[dict[str, Any]]:
    """检查同类别多框高度重叠。

    规则：同一 category_id 的两个框 IoU > 0.9 → 标记为"疑似重复标注"。
    """
    issues: list[dict[str, Any]] = []
    n = len(bboxes)
    for i in range(n):
        for j in range(i + 1, n):
            # 只检查同类别
            if bboxes[i].get("category_id") != bboxes[j].get("category_id"):
                continue
            iou = _calculate_iou(bboxes[i], bboxes[j])
            if iou > iou_threshold:
                issues.append({
                    "bbox_indices": [i, j],
                    "category_id": bboxes[i].get("category_id", ""),
                    "issue": "duplicate_bboxes",
                    "detail": f"框 {i} 与框 {j} IoU={iou:.3f} > {iou_threshold}，疑似重复标注",
                })
    return issues


def check_depth_range(
    bboxes: list[dict[str, Any]],
    min_depth: float = 0.0,
    max_depth: float = 500.0,
) -> list[dict[str, Any]]:
    """检查深度值合理性。

    规则：depth 不在 [0, 500] 米范围内 → 标记为异常。
    """
    issues: list[dict[str, Any]] = []
    for i, bbox in enumerate(bboxes):
        depth = bbox.get("depth")
        if depth is not None and not (min_depth <= depth <= max_depth):
            issues.append({
                "bbox_index": i,
                "category_id": bbox.get("category_id", ""),
                "issue": "depth_out_of_range",
                "detail": f"深度值 {depth}m 不在 [{min_depth}, {max_depth}] 范围内",
            })
    return issues


# ═══════════════════════════════════════════════════════════════════════════════
# IoU 辅助函数
# ═══════════════════════════════════════════════════════════════════════════════

def _calculate_iou(bbox_a: dict, bbox_b: dict) -> float:
    """计算两个归一化坐标框的 IoU（交并比）。"""
    # bbox 格式: {x: center_x, y: center_y, w: width, h: height}，归一化 0~1
    ax1 = bbox_a.get("x", 0) - bbox_a.get("w", 0) / 2
    ay1 = bbox_a.get("y", 0) - bbox_a.get("h", 0) / 2
    ax2 = bbox_a.get("x", 0) + bbox_a.get("w", 0) / 2
    ay2 = bbox_a.get("y", 0) + bbox_a.get("h", 0) / 2

    bx1 = bbox_b.get("x", 0) - bbox_b.get("w", 0) / 2
    by1 = bbox_b.get("y", 0) - bbox_b.get("h", 0) / 2
    bx2 = bbox_b.get("x", 0) + bbox_b.get("w", 0) / 2
    by2 = bbox_b.get("y", 0) + bbox_b.get("h", 0) / 2

    # 交集
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0.0, inter_x2 - inter_x1)
    inter_h = max(0.0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    # 并集
    area_a = bbox_a.get("w", 0) * bbox_a.get("h", 0)
    area_b = bbox_b.get("w", 0) * bbox_b.get("h", 0)
    union_area = area_a + area_b - inter_area

    if union_area <= 0:
        return 0.0
    return inter_area / union_area
