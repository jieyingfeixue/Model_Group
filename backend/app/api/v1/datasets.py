"""数据集路由 — /api/datasets/*"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.dataset import (
    DatasetCreateRequest,
    DatasetListResponse,
    DatasetPublishRequest,
    DatasetResponse,
    DatasetSplitRequest,
)
from app.services import normal_dataset_service

router = APIRouter(prefix="/datasets", tags=["Datasets"])


# ──── POST /api/datasets ────

@router.post("", response_model=DatasetResponse, status_code=201)
def create_dataset(
    body: DatasetCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建数据集，自动切分资源到 train/val/test"""
    result = normal_dataset_service.create_dataset(
        db,
        name=body.name,
        description=body.description,
        resource_ids=body.resource_ids,
        owner_id=current_user.user_id,
        split_config=body.split_config,
        visibility=body.visibility,
    )
    return DatasetResponse(**result)


# ──── GET /api/datasets ────

@router.get("", response_model=DatasetListResponse)
def list_datasets(
    visibility: str | None = Query(None, description="可见性: private / public"),
    keyword: str | None = Query(None, description="数据集名称关键字"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询数据集列表。默认为当前用户的全部数据集。"""
    items, total = normal_dataset_service.list_datasets(
        db,
        owner_id=current_user.user_id,
        visibility=visibility,
        keyword=keyword,
        page=page,
        size=size,
    )
    return DatasetListResponse(
        items=[DatasetResponse(**it) for it in items],
        total=total,
        page=page,
        size=size,
    )


# ──── GET /api/datasets/{dataset_id} ────

@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """获取数据集详情"""
    result = normal_dataset_service.get_dataset(db, dataset_id)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="数据集不存在")
    return DatasetResponse(**result)


# ──── POST /api/datasets/{dataset_id}/split ────

@router.post("/{dataset_id}/split", response_model=DatasetResponse)
def split_dataset(
    dataset_id: int,
    body: DatasetSplitRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """重新切分数据集（清除旧分配，按新比例随机分配）"""
    result = normal_dataset_service.split_dataset(
        db,
        dataset_id,
        split_config={"train": body.train, "val": body.val, "test": body.test, "strategy": body.strategy},
    )
    return DatasetResponse(**result)


# ──── POST /api/datasets/{dataset_id}/freeze ────

@router.post("/{dataset_id}/freeze", response_model=DatasetResponse)
def freeze_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """冻结数据集"""
    result = normal_dataset_service.freeze_dataset(db, dataset_id)
    return DatasetResponse(**result)


# ──── POST /api/datasets/{dataset_id}/publish ────

@router.post("/{dataset_id}/publish", response_model=DatasetResponse)
def publish_dataset(
    dataset_id: int,
    body: DatasetPublishRequest = DatasetPublishRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """发布数据集（需先冻结）"""
    result = normal_dataset_service.publish_dataset(db, dataset_id, body.version_note)
    return DatasetResponse(**result)
