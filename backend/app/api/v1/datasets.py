"""数据集 API 路由 — 筛选预览 / 创建 / 划分 / 冻结 / 导出 / 版本管理 / 归档"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.user import User
from app.schemas.dataset import (
    DatasetCreateRequest,
    DatasetPreviewRequest,
    DatasetPreviewResponse,
    DatasetResponse,
    DatasetSplitRequest,
    DatasetSplitResponse,
    VersionDiffResponse,
    VersionItem,
    VersionSaveRequest,
)
from app.services.normal_dataset_service import archive_dataset as svc_archive_dataset
from app.services.normal_dataset_service import batch_archive as svc_batch_archive
from app.services.normal_dataset_service import (
    change_visibility as svc_change_visibility,
)
from app.services.normal_dataset_service import create_dataset as svc_create_dataset
from app.services.normal_dataset_service import export_dataset as svc_export_dataset
from app.services.normal_dataset_service import freeze_dataset as svc_freeze_dataset
from app.services.normal_dataset_service import preview_by_filters as svc_preview_by_filters
from app.services.normal_dataset_service import publish_dataset as svc_publish_dataset
from app.services.normal_dataset_service import split_dataset as svc_split_dataset
from app.services.normal_dataset_service import compare_versions as svc_compare_versions
from app.services.normal_dataset_service import get_dataset_versions as svc_get_dataset_versions
from app.services.normal_dataset_service import save_new_version as svc_save_new_version
from app.services.normal_dataset_service import restore_dataset as svc_restore_dataset
from app.services.normal_data_service import download_copy as svc_download_copy
from app.services.normal_data_service import get_dataset_detail as svc_get_dataset_detail
from app.services.normal_data_service import list_public_datasets as svc_list_public_datasets
from app.services.normal_data_service import preview_dataset_samples as svc_preview_dataset_samples
from app.services.normal_dataset_service import submit_for_review as svc_submit_for_review
from app.services.normal_dataset_service import unfreeze_dataset as svc_unfreeze_dataset

router = APIRouter(tags=["Datasets"])


@router.post("/datasets/preview", response_model=DatasetPreviewResponse)
def preview_datasets(
    body: DatasetPreviewRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按条件预览数据。统计命中数量和抽样缩略图，不实际创建数据集。

    每修改一个筛选条件，前端调用此接口实时更新预览结果。
    同维度内 OR（如多选模态），跨维度间 AND（默认）。
    """
    # 安全校验：只能预览自己的数据
    if body.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能预览自己的数据资源",
        )

    result = svc_preview_by_filters(
        db,
        filters=body.filters.model_dump(exclude_none=True),
        owner_id=body.owner_id,
    )
    return DatasetPreviewResponse(**result)


@router.post("/datasets", response_model=DatasetResponse, status_code=201)
def create_dataset(
    body: DatasetCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建数据集。按筛选条件圈定样本，生成 Dataset + DatasetItem。

    流程：
    1. 解析 filters 条件
    2. DataResource.search() 圈定样本
    3. Dataset.create() 创建记录
    4. DatasetItem.bulk_insert() 批量写入条目
    5. 记录审计日志
    """
    owner_id = body.owner_id if body.owner_id is not None else current_user.user_id

    # 安全校验：只能用自己的数据创建数据集
    if owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只能使用自己的数据资源创建数据集",
        )

    dataset = svc_create_dataset(
        db,
        name=body.name,
        description=body.description,
        filters=body.filters,
        owner_id=owner_id,
    )
    return dataset


@router.post("/datasets/{dataset_id}/split", response_model=DatasetSplitResponse)
def split_dataset(
    dataset_id: int,
    body: DatasetSplitRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """划分子集。按比例随机或分层将条目分配到 train/val/test。

    比例以整数百分比传入（如 70/20/10），三者之和严格等于 100。
    分层划分基于 scene 或 modality 保持各子集分布一致。
    仅草稿状态（draft）的数据集可划分，已冻结/已发布不可操作。
    """
    # 安全校验：仅数据集拥有者可划分
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以划分",
        )

    result = svc_split_dataset(
        db,
        dataset_id=dataset_id,
        ratios=body.ratios,
        strategy=body.strategy,
        stratify_by=body.stratify_by,
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 冻结 / 发布 / 可见范围
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/datasets/{dataset_id}/freeze", response_model=DatasetResponse)
def freeze_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """冻结数据集。将状态从 draft 改为 frozen。

    冻结后禁止任何写操作（修改筛选条件、重新划分、增删条目）。
    仅数据集拥有者可操作。
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以冻结",
        )

    return svc_freeze_dataset(db, dataset_id)


@router.post("/datasets/{dataset_id}/unfreeze", response_model=DatasetResponse)
def unfreeze_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """解冻数据集（管理员特权）。

    将 frozen 回退为 draft，允许重新编辑。
    仅管理员可操作。
    """
    return svc_unfreeze_dataset(db, dataset_id)


@router.post("/datasets/{dataset_id}/submit-review", response_model=DatasetResponse)
def submit_for_review(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """提交公开审核。将 review_status 改为 submitted，等待审核员认领。

    可在不发布的情况下单独提交审核。
    仅数据集拥有者可操作。
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以提交审核",
        )

    return svc_submit_for_review(db, dataset_id)


@router.post("/datasets/{dataset_id}/publish", response_model=DatasetResponse)
def publish_dataset(
    dataset_id: int,
    visibility: str = "private",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发布数据集。

    若当前为 draft 状态，先自动冻结再发布。
    选择可见范围：private（仅自己）/ public（全平台可见）。
    若选择 public 且标注未经审核，自动提交审核任务。
    仅数据集拥有者可操作。
    """
    if visibility not in ("private", "public"):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="visibility 必须为 private 或 public",
        )

    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以发布",
        )

    return svc_publish_dataset(db, dataset_id, visibility)


@router.put("/datasets/{dataset_id}/visibility", response_model=DatasetResponse)
def update_visibility(
    dataset_id: int,
    visibility: str = "private",
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """修改数据集可见范围。

    public → private：从数据集市场下架。
    private → public：自动提交审核（若标注未经审核）。
    仅数据集拥有者可操作。
    """
    if visibility not in ("private", "public"):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="visibility 必须为 private 或 public",
        )

    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以修改可见范围",
        )

    return svc_change_visibility(db, dataset_id, visibility)


# ═══════════════════════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/datasets/{dataset_id}/export")
def export_dataset(
    dataset_id: int,
    format: str = "coco",
    subset: str | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """导出数据集。将数据集标注转换为标准格式并打包为 ZIP 下载。

    参数：
    - format: coco / voc / yolo
    - subset: train / val / test，不传则导出全部

    导出 ZIP 中仅含标注文件（COCO JSON / VOC XML / YOLO TXT），不含原始图片。
    返回 MinIO 签名下载 URL（有效期 1 小时）。
    私有数据集仅拥有者可导出，公开数据集任意登录用户可导出。
    """
    if format not in ("coco", "voc", "yolo"):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="format 必须为 coco / voc / yolo",
        )
    if subset is not None and subset not in ("train", "val", "test"):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="subset 必须为 train / val / test 或不传",
        )

    return svc_export_dataset(
        db,
        dataset_id=dataset_id,
        format=format,
        subset=subset,
        user_id=current_user.user_id,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 版本管理
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/datasets/{dataset_id}/versions", response_model=list[VersionItem])
def list_versions(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查看数据集版本历史。返回所有语义化版本的列表。

    版本号规则：
    - v1.0（初始）→ v1.1（微调）→ v2.0（重新配置筛选条件或大批量增删）
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    # 公开数据集任意用户可查看，私有仅拥有者
    if dataset.visibility == "private" and dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="私有数据集仅拥有者可查看版本",
        )

    return svc_get_dataset_versions(db, dataset_id)


@router.post("/datasets/{dataset_id}/versions")
def save_version(
    dataset_id: int,
    body: VersionSaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """保存新版本快照。强制填写变更日志。

    版本号自动递增：
    - minor: v1.0 → v1.1（微调子集/修补标注）
    - major: v1.0 → v2.0（重新配置筛选条件/大批量增删）
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以保存版本",
        )

    return svc_save_new_version(
        db,
        dataset_id=dataset_id,
        change_log=body.change_log,
        user_id=current_user.user_id,
        bump_type=body.bump_type,
    )


@router.get("/datasets/{dataset_id}/diff", response_model=VersionDiffResponse)
def diff_versions(
    dataset_id: int,
    v1: str,
    v2: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对比两个版本的差异。

    返回：新增样本 / 删除样本 / 子集变更 / 筛选条件变更。
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    # 公开数据集任意用户可查看差异，私有仅拥有者
    if dataset.visibility == "private" and dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="私有数据集仅拥有者可对比版本",
        )

    return svc_compare_versions(db, dataset_id, v1=v1, v2=v2)


# ═══════════════════════════════════════════════════════════════════════════════
# 归档 / 恢复
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/datasets/{dataset_id}/archive", response_model=DatasetResponse)
def archive_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """归档数据集。与冻结/发布状态正交（独立维度）。

    归档后仅保留检索和预览，不可标注、训练、评测或下载。
    仅数据集拥有者可操作。
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以归档",
        )

    return svc_archive_dataset(db, dataset_id, current_user.user_id)


@router.post("/datasets/{dataset_id}/restore", response_model=DatasetResponse)
def restore_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """恢复数据集。将 archived 恢复为 active。

    仅数据集拥有者可操作。
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="仅数据集拥有者可以恢复",
        )

    return svc_restore_dataset(db, dataset_id, current_user.user_id)


@router.post("/admin/datasets/batch-archive")
def batch_archive(
    filters: dict,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("admin")),
):
    """批量归档数据集（仅管理员）。

    按条件筛选后批量执行归档操作。
    filters 支持：owner_id, modality, created_before(ISO)。
    返回 {archived_count, skipped_count, matched_count}。
    """
    return svc_batch_archive(db, filters, current_user.user_id)


# ═══════════════════════════════════════════════════════════════════════════════
# 我的数据集 / 数据集市场
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/datasets/mine")
def list_my_datasets(
    status: str | None = None,
    page: int = 1,
    size: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户拥有的数据集（含私有/草稿），供「我的数据集」与训练/评测下拉使用。"""
    from app.models.dataset_item import DatasetItem

    rows = Dataset.get_by_owner(db, current_user.user_id)
    if status:
        rows = [d for d in rows if d.status == status]
    total = len(rows)
    start = max(0, (page - 1) * size)
    page_rows = rows[start : start + size]
    items = []
    for d in page_rows:
        counts = DatasetItem.count_by_subset(db, d.dataset_id)
        sample_count = sum(counts.values())
        items.append(
            {
                **DatasetResponse.model_validate(d).model_dump(),
                "sample_count": sample_count,
                "subset_counts": counts,
            }
        )
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/datasets")
def list_public_datasets(
    modality: str | None = None,
    scene: str | None = None,
    weather: str | None = None,
    time_of_day: str | None = None,
    keyword: str | None = None,
    label_categories: str | None = None,
    sort_by: str = "updated_at",
    page: int = 1,
    size: int = 50,
    db: Session = Depends(get_db),
):
    """浏览数据集市场。查询所有已发布的公开数据集。

    支持按模态/场景/天气/时段/标签类别筛选、关键词模糊搜索、排序和分页。
    默认每页 50 条，按更新时间降序。
    """
    filters: dict = {}
    if modality:
        # 支持逗号分隔多选
        modalities = [m.strip() for m in modality.split(",") if m.strip()]
        filters["modality"] = modalities if len(modalities) > 1 else modalities[0]
    if scene:
        filters["scene"] = scene
    if weather:
        filters["weather"] = weather
    if time_of_day:
        filters["time_of_day"] = time_of_day
    if label_categories:
        # 支持逗号分隔多选
        cats = [c.strip() for c in label_categories.split(",") if c.strip()]
        filters["label_categories"] = cats if len(cats) > 1 else cats[0]
    if keyword:
        filters["keyword"] = keyword
    if sort_by:
        filters["sort_by"] = sort_by

    items, total = svc_list_public_datasets(db, filters, page, size)
    return {"items": items, "total": total, "page": page, "size": size}


@router.get("/datasets/{dataset_id}")
def get_dataset_detail(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """查看数据集详情。含基本信息 + 各子集数量统计。

    公开数据集任意登录用户可查看，私有数据集仅拥有者可查看。
    """
    from app.models.dataset import Dataset

    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.visibility == "private" and dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="私有数据集仅拥有者可查看详情",
        )

    return svc_get_dataset_detail(db, dataset_id)


@router.get("/datasets/{dataset_id}/preview")
def preview_dataset(
    dataset_id: int,
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """预览数据集样本。只读模式查看样本图片和标注结果。

    分页返回，每页默认 20 条。
    """
    from app.models.dataset import Dataset

    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.visibility == "private" and dataset.owner_id != current_user.user_id:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="私有数据集仅拥有者可预览",
        )

    return svc_preview_dataset_samples(db, dataset_id, page, size)


@router.post("/datasets/{dataset_id}/copy")
def copy_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """复制数据集到自己的仓库。

    将公开数据集复制一份到当前用户名下，复制后与原数据集解耦。
    """
    return svc_download_copy(db, dataset_id, current_user.user_id)
