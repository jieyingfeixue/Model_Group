"""数据集审核 Service — 审核员查看 / 认领 / 裁决数据集"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.dataset import Dataset


def list_pending_datasets(
    db: Session,
    reviewer_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询待审核数据集列表。

    支持筛选：
      - 所有 review_status = 'pending_review' 的数据集
      - 可选按 reviewer_id 筛选已认领的数据集
    """
    query = db.query(Dataset).filter(Dataset.review_status == "pending_review")

    if reviewer_id is not None:
        query = query.filter(Dataset.reviewer_id == reviewer_id)

    total = query.count()
    datasets = (
        query.order_by(Dataset.updated_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for ds in datasets:
        from app.models.dataset_item import DatasetItem

        counts = DatasetItem.count_by_subset(db, ds.dataset_id)
        items.append({
            "dataset_id": ds.dataset_id,
            "name": ds.name,
            "description": ds.description,
            "owner_id": ds.owner_id,
            "review_status": ds.review_status,
            "sample_count": sum(counts.values()),
            "created_at": ds.created_at.isoformat() if ds.created_at else None,
            "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
        })

    return items, total


def claim_dataset(
    db: Session, dataset_id: int, reviewer_id: int
) -> dict[str, Any]:
    """审核员认领数据集审核任务。

    规则：
      - 数据集 review_status 必须为 pending_review
      - 若已被他人认领则拒绝
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )

    if dataset.review_status != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该数据集当前不在待审核状态",
        )

    if dataset.reviewer_id is not None and dataset.reviewer_id != reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="该数据集已被其他审核员认领",
        )

    dataset.reviewer_id = reviewer_id
    dataset.save(db)
    return {
        "dataset_id": dataset.dataset_id,
        "reviewer_id": reviewer_id,
        "message": "认领成功",
    }


def submit_dataset_verdict(
    db: Session,
    dataset_id: int,
    verdict: str,
    reviewer_id: int,
    notes: str | None = None,
) -> dict[str, Any]:
    """审核员提交数据集审核结果。

    规则：
      - 必须已被该审核员认领
      - verdict 为 approved 或 rejected
    """
    if verdict not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="verdict 必须为 approved 或 rejected",
        )

    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="数据集不存在"
        )

    if dataset.reviewer_id != reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="您尚未认领该数据集，无法提交审核结果",
        )

    if dataset.review_status != "pending_review":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该数据集当前不在待审核状态",
        )

    dataset.review_status = verdict
    dataset.review_notes = {"verdict": verdict, "notes": notes or "", "reviewer_id": reviewer_id}
    dataset.save(db)

    return {
        "dataset_id": dataset.dataset_id,
        "review_status": dataset.review_status,
        "reviewer_id": dataset.reviewer_id,
        "review_notes": dataset.review_notes,
        "message": "审核完成",
    }
