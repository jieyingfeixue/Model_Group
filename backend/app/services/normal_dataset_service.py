"""数据集 Service — create / list / detail / split / freeze / publish"""

import random
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.dataset_item import DatasetItem
from app.models.data_resource import DataResource


def _build_response(db: Session, dataset: Dataset) -> dict[str, Any]:
    """将 ORM 对象转为包含统计信息的响应字典"""
    counts = DatasetItem.count_by_subset(db, dataset.dataset_id)
    total_items = sum(counts.values())
    return {
        "dataset_id": dataset.dataset_id,
        "name": dataset.name,
        "description": dataset.description,
        "owner_id": dataset.owner_id,
        "filters": dataset.filters,
        "split_config": dataset.split_config,
        "version": dataset.version,
        "status": dataset.status,
        "archive_status": dataset.archive_status,
        "visibility": dataset.visibility,
        "review_status": dataset.review_status,
        "sample_count": total_items,
        "subset_counts": counts,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "updated_at": dataset.updated_at.isoformat() if dataset.updated_at else None,
    }


# ──── 创建 ────

def create_dataset(
    db: Session,
    name: str,
    description: str,
    resource_ids: list[int],
    owner_id: int,
    split_config: dict[str, Any] | None = None,
    visibility: str = "private",
) -> dict[str, Any]:
    """创建数据集：写入 datasets + 分配 dataset_items。

    Args:
        resource_ids: 数据资源 ID 列表
        split_config: 切分配置，若提供则自动切分到 train/val/test
    """
    # 校验 resource_ids 存在
    existing = (
        db.query(DataResource.resource_id)
        .filter(DataResource.resource_id.in_(resource_ids))
        .all()
    )
    existing_ids = {r[0] for r in existing}
    missing = [rid for rid in resource_ids if rid not in existing_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"以下资源不存在: {missing[:10]}{'...' if len(missing) > 10 else ''}",
        )

    # 创建数据集
    dataset = Dataset.create(
        db,
        name=name,
        description=description or "",
        owner_id=owner_id,
        filters={"resource_ids": resource_ids},
        split_config=split_config,
        visibility=visibility,
    )

    # 切分并写入 dataset_items
    if split_config:
        _apply_split(db, dataset.dataset_id, resource_ids, split_config)
    else:
        # 默认全部放入 train
        items = [{"resource_id": rid, "subset": "train"} for rid in resource_ids]
        DatasetItem.bulk_insert(db, dataset.dataset_id, items)

    db.flush()
    return _build_response(db, dataset)


# ──── 列表 ────

def list_datasets(
    db: Session,
    owner_id: int | None = None,
    visibility: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询数据集列表，支持按拥有者、可见性、关键字筛选"""
    query = db.query(Dataset)

    if owner_id is not None:
        query = query.filter(Dataset.owner_id == owner_id)
    if visibility:
        query = query.filter(Dataset.visibility == visibility)
    if keyword:
        query = query.filter(Dataset.name.ilike(f"%{keyword}%"))

    total = query.count()
    datasets = (
        query.order_by(Dataset.dataset_id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return [_build_response(db, ds) for ds in datasets], total


# ──── 详情 ────

def get_dataset(db: Session, dataset_id: int) -> dict[str, Any] | None:
    """获取数据集详情"""
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        return None
    return _build_response(db, dataset)


# ──── 切分 ────

def _apply_split(
    db: Session,
    dataset_id: int,
    resource_ids: list[int],
    split_config: dict[str, Any],
) -> None:
    """根据配置将 resource_ids 分配到 train / val / test

    支持三种策略:
      - random:   按单个 resource_id 随机打乱后切分
      - grouped:  按 sample_group 分组后整组分配（保持多模态配对不被拆散）
      - 其他:     不 shuffle，按原始顺序切分
    """
    train_pct = int(split_config.get("train", 70))
    val_pct = int(split_config.get("val", 20))
    test_pct = int(split_config.get("test", 10))
    strategy = split_config.get("strategy", "random")

    total = train_pct + val_pct + test_pct
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="切分比例之和不能为 0",
        )

    # ── grouped 策略：按 sample_group 聚合后整组分配 ──
    if strategy == "grouped":
        _apply_grouped_split(db, dataset_id, resource_ids, train_pct, val_pct, test_pct, total)
    else:
        _apply_flat_split(db, dataset_id, resource_ids, train_pct, val_pct, test_pct, total, strategy)

    # 回写 split_config 到数据集
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset:
        dataset.split_config = split_config
        dataset.save(db)


def _apply_grouped_split(
    db: Session,
    dataset_id: int,
    resource_ids: list[int],
    train_pct: int,
    val_pct: int,
    test_pct: int,
    total_pct: int,
) -> None:
    """按 sample_group 分组后整组随机分配到 train/val/test"""
    # 1. 批量查询 sample_group
    rows = (
        db.query(
            DataResource.resource_id,
            DataResource.meta_info["sample_group"].astext,
        )
        .filter(DataResource.resource_id.in_(resource_ids))
        .all()
    )

    # 2. 建立分组: {group_key: [resource_id, ...]}
    groups: dict[str, list[int]] = {}
    seen: set[int] = set()
    for rid, sg in rows:
        seen.add(rid)
        key = sg if sg else f"_single_{rid}"
        groups.setdefault(key, []).append(rid)

    # 3. 未查到的 resource_id 各自独立成组
    for rid in resource_ids:
        if rid not in seen:
            groups.setdefault(f"_single_{rid}", []).append(rid)

    # 4. 打乱 group_id，保持组内顺序
    group_ids = list(groups.keys())
    random.shuffle(group_ids)

    # 5. 按组数量比例分配
    n_groups = len(group_ids)
    train_end = max(1, int(n_groups * train_pct / total_pct))
    val_end = train_end + max(0, int(n_groups * val_pct / total_pct))

    items: list[dict[str, Any]] = []
    for i, gid in enumerate(group_ids):
        if i < train_end:
            subset = "train"
        elif i < val_end:
            subset = "val"
        else:
            subset = "test"
        for rid in groups[gid]:
            items.append({"resource_id": rid, "subset": subset})

    DatasetItem.bulk_insert(db, dataset_id, items)


def _apply_flat_split(
    db: Session,
    dataset_id: int,
    resource_ids: list[int],
    train_pct: int,
    val_pct: int,
    test_pct: int,
    total_pct: int,
    strategy: str,
) -> None:
    """按单个 resource_id 切分（原有逻辑）"""
    ids = list(resource_ids)
    if strategy == "random":
        random.shuffle(ids)

    n = len(ids)
    train_end = max(1, int(n * train_pct / total_pct))
    val_end = train_end + max(0, int(n * val_pct / total_pct))

    items: list[dict[str, Any]] = []
    for i, rid in enumerate(ids):
        if i < train_end:
            subset = "train"
        elif i < val_end:
            subset = "val"
        else:
            subset = "test"
        items.append({"resource_id": rid, "subset": subset})

    DatasetItem.bulk_insert(db, dataset_id, items)


def split_dataset(
    db: Session, dataset_id: int, split_config: dict[str, Any]
) -> dict[str, Any]:
    """对已存在的数据集重新切分。先清除旧条目，再按新比例分配。"""
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )

    # 获取该数据集当前所有条目
    items = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_id == dataset_id)
        .all()
    )
    resource_ids = [it.resource_id for it in items]

    if not resource_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="数据集中没有数据，无法切分"
        )

    # 删除旧条目
    for it in items:
        it.delete(db)

    # 重新切分
    _apply_split(db, dataset_id, resource_ids, split_config)
    db.flush()
    return _build_response(db, dataset)


# ──── 冻结 ────

def freeze_dataset(db: Session, dataset_id: int) -> dict[str, Any]:
    """冻结数据集（draft → frozen）"""
    dataset = Dataset.update_status(db, dataset_id, "frozen")
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )
    return _build_response(db, dataset)


# ──── 发布 ────

def publish_dataset(
    db: Session, dataset_id: int, version_note: str = "v1.0"
) -> dict[str, Any]:
    """发布数据集（frozen → published）"""
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )
    if dataset.status != "frozen":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只有已冻结的数据集才能发布",
        )
    dataset.status = "published"
    dataset.visibility = "public"
    dataset.version = version_note or dataset.version
    dataset.save(db)
    return _build_response(db, dataset)


# ──── 数据集条目查询 ────

# ──── 归档 / 恢复 ────

def archive_dataset(db: Session, dataset_id: int) -> dict[str, Any]:
    """归档数据集（active → archived）"""
    dataset = Dataset.set_archive_status(db, dataset_id, "archived")
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )
    return _build_response(db, dataset)


def restore_dataset(db: Session, dataset_id: int) -> dict[str, Any]:
    """恢复已归档数据集（archived → active）"""
    dataset = Dataset.set_archive_status(db, dataset_id, "active")
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )
    return _build_response(db, dataset)


# ──── 提交审核 ────

def submit_for_review(db: Session, dataset_id: int) -> dict[str, Any]:
    """提交数据集审核（review_status → pending_review）"""
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )
    if dataset.status != "frozen":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="只有已冻结的数据集才能提交审核",
        )
    dataset.review_status = "pending_review"
    dataset.save(db)
    return _build_response(db, dataset)


# ──── 数据集条目查询 ────

def get_dataset_samples(db: Session, dataset_id: int) -> list[dict[str, Any]]:
    """获取数据集内的样本列表，按 sample_group 分组。

    返回格式：
    [
      {
        "sample_group": "1",
        "scene": "daytime",
        "resources": [
          {"resource_id": 6559, "modality": "infrared", "name": "xxx.jpg",
           "annotation_status": "unannotated", "file_path": "/...", ...},
          ...
        ]
      },
      ...
    ]
    """
    from app.models.dataset_item import DatasetItem
    from app.models.data_resource import DataResource

    rows = (
        db.query(
            DatasetItem.resource_id,
            DatasetItem.subset,
            DataResource.name,
            DataResource.modality,
            DataResource.file_path,
            DataResource.annotation_status,
            DataResource.meta_info,
        )
        .join(DataResource, DatasetItem.resource_id == DataResource.resource_id)
        .filter(DatasetItem.dataset_id == dataset_id)
        .all()
    )

    # 按 sample_group 分组
    groups: dict[str, dict[str, Any]] = {}
    for rid, subset, name, modality, file_path, anno_status, meta in rows:
        sg = str(meta.get("sample_group", rid)) if meta else str(rid)
        if sg not in groups:
            groups[sg] = {
                "sample_group": sg,
                "scene": (meta or {}).get("scene", "-"),
                "weather": (meta or {}).get("weather"),
                "time_of_day": (meta or {}).get("time_of_day"),
                "terrain": (meta or {}).get("terrain"),
                "obstacle": (meta or {}).get("obstacle"),
                "subset": subset,
                "resources": [],
            }
        groups[sg]["resources"].append({
            "resource_id": rid,
            "modality": modality,
            "name": name,
            "annotation_status": anno_status,
        })

    return list(groups.values())
