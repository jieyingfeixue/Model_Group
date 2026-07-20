"""数据集划分策略 — 随机划分 + 分层均衡划分 + 分布统计"""

import random
from typing import Any

import numpy as np
from sklearn.model_selection import train_test_split
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.data_resource import DataResource


def random_split(
    items: list[int],
    ratios: tuple[float, float, float],
) -> dict[str, list[int]]:
    """随机划分策略。

    直接打乱列表，按比例切分为 train/val/test 三组。

    Args:
        items: 样本 resource_id 列表
        ratios: (train, val, test) 比例，如 (0.7, 0.2, 0.1)

    Returns:
        {train: [...], val: [...], test: [...]}
    """
    if not items:
        return {"train": [], "val": [], "test": []}

    shuffled = list(items)
    random.shuffle(shuffled)

    n = len(shuffled)
    train_end = round(n * ratios[0])
    val_end = train_end + round(n * ratios[1])

    return {
        "train": shuffled[:train_end],
        "val": shuffled[train_end:val_end],
        "test": shuffled[val_end:],
    }


def stratified_split(
    items: list[int],
    ratios: tuple[float, float, float],
    db: Session,
    stratify_by: str = "scene",
) -> dict[str, list[int]]:
    """分层均衡划分策略。

    原理：
    1. 查询每个 item 对应的分层标签（场景类型 / 模态）
    2. 校验每种标签的样本数 ≥ 2，否则降级为随机划分（sklearn stratify 要求）
    3. 按 stratify_by 分组
    4. 每组内独立执行 sklearn train_test_split 分层划分
    5. 合并各组的三子集

    确保各子集中各类别/场景/模态的分布与总体一致。

    Args:
        items: 样本 resource_id 列表
        ratios: (train, val, test) 比例
        db: 数据库 session
        stratify_by: 分层依据 — 'scene'（meta_info->>'scene'）/ 'modality'

    Returns:
        {train: [...], val: [...], test: [...]}
    """
    if not items:
        return {"train": [], "val": [], "test": []}

    # ── 1. 批量查询 resource 的分层标签 ──
    resources = (
        db.query(DataResource.resource_id, DataResource.modality, DataResource.meta_info)
        .filter(DataResource.resource_id.in_(items))
        .all()
    )
    resource_map: dict[int, str] = {}
    for rid, modality, meta_info in resources:
        if stratify_by == "modality":
            resource_map[rid] = modality or "unknown"
        elif stratify_by == "scene":
            resource_map[rid] = (meta_info or {}).get("scene", "unknown")
        else:
            resource_map[rid] = "unknown"

    # 按资源 ID 顺序构建标签数组
    labels = np.array([resource_map.get(rid, "unknown") for rid in items])

    # ── 2. 校验分层可行性 ──
    # sklearn train_test_split(stratify=...) 要求每种标签至少出现 2 次
    unique, counts = np.unique(labels, return_counts=True)
    min_count = int(counts.min()) if len(counts) > 0 else 0
    if min_count < 2:
        # 某标签样本数不足，降级为随机划分
        return random_split(items, ratios)

    # ── 3. 两次分层划分 ──
    items_arr = np.array(items)
    indices = np.arange(len(items))

    # 第一次划分：分出 test
    train_val_idx, test_idx = train_test_split(
        indices,
        test_size=ratios[2],
        stratify=labels,
        random_state=42,
    )

    # 第二次划分：train_val 分成 train 和 val
    train_val_labels = labels[train_val_idx]
    val_ratio = ratios[1] / (ratios[0] + ratios[1]) if (ratios[0] + ratios[1]) > 0 else 0.0
    train_idx, val_idx = train_test_split(
        train_val_idx,
        test_size=val_ratio,
        stratify=train_val_labels,
        random_state=42,
    )

    return {
        "train": items_arr[train_idx].tolist(),
        "val": items_arr[val_idx].tolist(),
        "test": items_arr[test_idx].tolist(),
    }


def calculate_split_distribution(
    db: Session,
    dataset_id: int,
    split_result: dict[str, list[int]],
) -> dict[str, Any]:
    """计算划分后的分布统计。

    对各子集的样本，查询其最新标注中的 bboxes，逐类别统计框数。
    返回结构供前端渲染堆叠柱状图（ECharts）。

    Args:
        db: 数据库 session
        dataset_id: 数据集 ID
        split_result: {train: [resource_id, ...], val: [...], test: [...]}

    Returns:
        {
            "total": N,
            "train": {"count": N1, "categories": {"cat_001": 100, "cat_002": 200, ...}},
            "val": {"count": N2, "categories": {...}},
            "test": {"count": N3, "categories": {...}}
        }
    """
    from sqlalchemy import func

    result: dict[str, Any] = {"total": 0}
    total_count = 0

    for subset, rids in split_result.items():
        subset_count = len(rids)
        total_count += subset_count
        categories: dict[str, int] = {}

        if rids:
            # 子查询：每个 resource 在每个 task 中的最新标注版本
            # 仅统计 approved / submitted 标注，与 search() label_categories 过滤逻辑一致
            subq = (
                db.query(
                    Annotation.resource_id,
                    Annotation.task_id,
                    func.max(Annotation.version).label("max_version"),
                )
                .filter(
                    Annotation.resource_id.in_(rids),
                    Annotation.review_status.in_(["approved", "submitted"]),
                )
                .group_by(Annotation.resource_id, Annotation.task_id)
            ).subquery()

            # JOIN 获取最新版本的 bboxes
            annotations = (
                db.query(Annotation.bboxes)
                .join(
                    subq,
                    (Annotation.resource_id == subq.c.resource_id)
                    & (Annotation.task_id == subq.c.task_id)
                    & (Annotation.version == subq.c.max_version),
                )
                .all()
            )

            for (bboxes,) in annotations:
                if not bboxes:
                    continue
                for bbox in bboxes:
                    cat_id = bbox.get("category_id", "unknown")
                    categories[cat_id] = categories.get(cat_id, 0) + 1

        result[subset] = {
            "count": subset_count,
            "categories": categories,
        }

    result["total"] = total_count
    return result
