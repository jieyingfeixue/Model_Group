"""数据集路由 — /api/datasets/*"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.dataset import (
    DatasetCreateRequest,
    DatasetDiffResponse,
    DatasetListResponse,
    DatasetPreviewRequest,
    DatasetPreviewResponse,
    DatasetPublishRequest,
    DatasetResponse,
    DatasetSplitRequest,
    DatasetVersionListResponse,
    DatasetVisibilityRequest,
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


# ──── GET /api/datasets/{dataset_id}/items ────

@router.get("/{dataset_id}/items")
def get_dataset_items(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """获取数据集内的样本列表，按 sample_group 分组"""
    dataset = normal_dataset_service.get_dataset(db, dataset_id)
    if dataset is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="数据集不存在")
    samples = normal_dataset_service.get_dataset_samples(db, dataset_id)
    return {
        "dataset_id": dataset_id,
        "name": dataset["name"],
        "samples": samples,
        "total": len(samples),
    }


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


# ──── POST /api/datasets/{dataset_id}/archive ────

@router.post("/{dataset_id}/archive", response_model=DatasetResponse)
def archive_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """归档数据集"""
    result = normal_dataset_service.archive_dataset(db, dataset_id)
    return DatasetResponse(**result)


# ──── POST /api/datasets/{dataset_id}/restore ────

@router.post("/{dataset_id}/restore", response_model=DatasetResponse)
def restore_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """恢复已归档数据集"""
    result = normal_dataset_service.restore_dataset(db, dataset_id)
    return DatasetResponse(**result)


# ──── POST /api/datasets/{dataset_id}/submit-review ────

@router.post("/{dataset_id}/submit-review", response_model=DatasetResponse)
def submit_for_review(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交数据集审核（需先冻结）"""
    result = normal_dataset_service.submit_for_review(db, dataset_id)
    return DatasetResponse(**result)


# ──── DELETE /api/datasets/{dataset_id} ────

@router.delete("/{dataset_id}", status_code=204)
def delete_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """物理删除数据集"""
    normal_dataset_service.delete_dataset(db, dataset_id)


# ──── §6 扩展：预览 / 可见性 / 版本 / diff / 导出 / 复制 ────


@router.get("/{dataset_id}/preview")
def preview_dataset(
    dataset_id: int,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """预览数据集样本"""
    result = normal_dataset_service.preview_dataset(db, dataset_id, page=page, size=size)
    if result is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return result


@router.post("/preview", response_model=DatasetPreviewResponse)
def preview_by_filter(
    body: DatasetPreviewRequest,
    db: Session = Depends(get_db),
):
    """按条件预览命中资源数（不创建数据集）"""
    result = normal_dataset_service.preview_dataset_by_filter(
        db,
        resource_ids=body.resource_ids,
        filters=body.filters,
    )
    return DatasetPreviewResponse(**result)


@router.put("/{dataset_id}/visibility", response_model=DatasetResponse)
def set_visibility(
    dataset_id: int,
    body: DatasetVisibilityRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """设置数据集可见性（private / public）"""
    result = normal_dataset_service.set_dataset_visibility(db, dataset_id, body.visibility)
    return DatasetResponse(**result)


@router.get("/{dataset_id}/versions")
def get_versions(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """获取数据集版本列表"""
    result = normal_dataset_service.get_dataset_versions(db, dataset_id)
    if result is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return result


@router.get("/{dataset_id}/diff")
def get_diff(
    dataset_id: int,
    v1: str = Query(..., description="基准版本"),
    v2: str = Query(..., description="对比版本"),
    db: Session = Depends(get_db),
):
    """数据集版本 diff"""
    result = normal_dataset_service.get_dataset_diff(db, dataset_id, v1, v2)
    if result is None:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return result


@router.get("/{dataset_id}/export")
def export_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """导出数据集为 ZIP 文件"""
    from fastapi.responses import Response

    zip_bytes, filename = normal_dataset_service.export_dataset(db, dataset_id)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{dataset_id}/copy", response_model=DatasetResponse, status_code=201)
def copy_dataset(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """复制数据集到个人库"""
    result = normal_dataset_service.copy_dataset(db, dataset_id, current_user.user_id)
    return DatasetResponse(**result)
