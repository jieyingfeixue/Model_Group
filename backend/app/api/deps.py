"""API 通用依赖 — get_current_user 注入 / 数据集状态拦截"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.middleware import get_current_user, require_role
from app.models.dataset import Dataset

__all__ = [
    "get_current_user",
    "require_role",
    "check_dataset_not_frozen",
    "check_dataset_not_archived",
]


def check_dataset_not_frozen(db: Session, dataset_id: int) -> Dataset:
    """校验数据集未冻结/未发布，否则拒绝写操作。

    用于标注保存、子集划分、条目增删等写操作的端点/Service 层调用。
    若已冻结或已发布，抛出 403 Forbidden。
    返回 Dataset 实例供后续使用。

    用法（路由层）：
        def endpoint(dataset_id, db, ...):
            dataset = check_dataset_not_frozen(db, dataset_id)

    用法（Service 层）：
        dataset = check_dataset_not_frozen(db, dataset_id)
    """
    dataset = db.query(Dataset).filter(
        Dataset.dataset_id == dataset_id
    ).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.status in ("frozen", "published"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="数据集已冻结或已发布，不可修改",
        )
    return dataset


def check_dataset_not_archived(db: Session, dataset_id: int) -> Dataset:
    """校验数据集未归档，否则拒绝写操作。

    归档后数据集仅保留检索和预览，不可新建标注、训练、评测或下载。
    与冻结/发布状态正交（独立维度）。

    用法：与 check_dataset_not_frozen 一致，路由层或 Service 层直接调用。
    """
    dataset = db.query(Dataset).filter(
        Dataset.dataset_id == dataset_id
    ).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.archive_status == "archived":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="数据集已归档，不可操作",
        )
    return dataset
