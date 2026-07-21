"""数据集构建 Service — 筛选预览 / 创建 / 划分 / 冻结 / 导出 / 版本管理 / 归档"""

import json
import random
import uuid
import zipfile
from io import BytesIO
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.redis import get_redis_client
from app.core.storage import get_file_url, upload_file
from app.models.audit_log import AuditLog
from app.models.data_resource import DataResource
from app.models.dataset import Dataset
from app.models.dataset_item import DatasetItem
from app.models.dataset_version import DatasetVersion
from app.utils.format_converter import FormatConverter
from app.utils.split_strategy import (
    calculate_split_distribution,
    random_split,
    stratified_split,
)


def _build_search_filters(filters: dict[str, Any]) -> dict[str, Any]:
    """将前端 DatasetFilter 转为 DataResource.search() 能用的筛选 dict。

    处理逻辑：
    - modality list → 保持 list，由 search() 内部 IN 查询
    - label_categories list → 保持 list，由 search() 内部 JSONB contains 查询
    - time_range {start, end} → 展开为 start_time / end_time
    - 其他字段直接透传
    """
    search_filters: dict[str, Any] = {}

    for key, value in filters.items():
        if value is None:
            continue
        if key == "time_range" and isinstance(value, dict):
            if start := value.get("start"):
                search_filters["start_time"] = start
            if end := value.get("end"):
                search_filters["end_time"] = end
        elif key == "logic_operator":
            # logic_operator 由 search() 内部消费，透传
            search_filters["logic_operator"] = value
        else:
            search_filters[key] = value

    return search_filters


def preview_by_filters(
    db: Session,
    filters: dict[str, Any],
    owner_id: int,
) -> dict[str, Any]:
    """按条件预览数据。统计命中数量和抽样缩略图，不实际创建数据集。

    每修改一个筛选条件，前端调用此接口实时更新预览结果。

    流程：
    1. filters 写入 owner_id
    2. DataResource.search(db, filters) → (资源列表, 总数)
    3. 随机抽样最多 10 个 file_path
    4. 生成临时签名 URL
    5. 返回 {total_count, sample_thumbnails}

    API: POST /api/datasets/preview
    """
    filters = _build_search_filters(filters)
    filters["owner_id"] = owner_id

    # 查询命中总数（只查第一页少量数据用于抽样）
    resources, total = DataResource.search(
        db, filters=filters, page=1, size=min(50, 50)
    )

    # 如果命中数较多，随机抽样取缩略图
    sample_urls: list[str] = []
    if total > 0:
        # 从当前页随机取最多 10 个
        sample_resources = random.sample(
            resources, min(10, len(resources))
        )
        for r in sample_resources:
            try:
                url = get_file_url(r.file_path, expires=300)
                if url:
                    sample_urls.append(url)
            except Exception:
                pass

    return {
        "total_count": total,
        "sample_thumbnails": sample_urls,
    }


def create_dataset(
    db: Session,
    name: str,
    description: str | None,
    filters: dict[str, Any],
    owner_id: int,
) -> Dataset:
    """创建数据集。按筛选条件圈定样本，生成 Dataset + DatasetItem。

    流程：
    1. filters 写入 owner_id，调用 DataResource.search() 圈定全部样本
    2. 校验命中数 > 0
    3. Dataset.create() 创建数据集记录
    4. DatasetItem.bulk_insert() 批量写入条目（默认 subset='train'）
    5. 记录审计日志
    6. 返回 Dataset

    API: POST /api/datasets
    """
    search_filters = _build_search_filters(filters)
    search_filters["owner_id"] = owner_id

    # ── 1. 圈定全部样本（不分页） ──
    # 先获取总数，再一次性查出全部 ID
    _, total = DataResource.search(db, filters=search_filters, page=1, size=1)
    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="筛选条件未匹配到任何数据资源，请调整条件后重试",
        )

    all_resources, _ = DataResource.search(
        db, filters=search_filters, page=1, size=max(total, 1)
    )

    # ── 2. 创建数据集 ──
    dataset = Dataset.create(
        db,
        name=name,
        description=description,
        owner_id=owner_id,
        filters=filters,
        status="draft",
    )

    # ── 3. 批量写入条目 ──
    items = [
        {"resource_id": r.resource_id, "subset": "train"}
        for r in all_resources
    ]
    DatasetItem.bulk_insert(db, dataset.dataset_id, items)

    # ── 4. 审计日志 ──
    AuditLog(
        user_id=owner_id,
        action="create_dataset",
        target_type="dataset",
        target_id=dataset.dataset_id,
        after_state={
            "name": name,
            "sample_count": len(items),
            "filters": filters,
        },
    ).save(db)

    return dataset


def split_dataset(
    db: Session,
    dataset_id: int,
    ratios: dict[str, int],
    strategy: str = "random",
    stratify_by: str = "scene",
) -> dict[str, Any]:
    """划分子集。按比例将条目分配到 train/val/test。

    参数：
    - ratios: {train: 70, val: 20, test: 10}，三者之和严格等于 100
    - strategy: 'random' / 'stratified'
    - stratify_by: 分层依据（stratified 时生效）：scene / modality

    流程：
    1. 校验 ratios 三者之和 = 100%（误差容限 ±0.1%）
    2. 校验 dataset.status = 'draft'（已冻结不可重新划分）
    3. 查全量 DatasetItem
    4. 根据 strategy 调用对应算法
    5. 批量更新子集归属
    6. 更新 Dataset.split_config
    7. 调用 calculate_split_distribution() 返回分布统计

    API: POST /api/datasets/{id}/split
    """
    # ── 1. 校验比例 ──
    train_pct = ratios.get("train", 0)
    val_pct = ratios.get("val", 0)
    test_pct = ratios.get("test", 0)
    total_pct = train_pct + val_pct + test_pct
    if abs(total_pct - 100) > 0.1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"train + val + test 之和必须等于 100%，当前为 {total_pct}%",
        )
    if train_pct <= 0 or val_pct <= 0 or test_pct <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="train/val/test 比例均需大于 0",
        )

    # ── 2. 校验数据集状态 ──
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅草稿状态的数据集可以划分，当前状态：{dataset.status}",
        )

    # ── 3. 查询全量条目 ──
    items = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_id == dataset_id)
        .all()
    )
    if not items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="数据集为空，无样本可划分",
        )

    item_map: dict[int, int] = {it.resource_id: it.item_id for it in items}
    resource_ids = [it.resource_id for it in items]

    # ── 4. 调用划分算法 ──
    ratios_float = (train_pct / 100.0, val_pct / 100.0, test_pct / 100.0)

    if strategy == "stratified":
        split_result = stratified_split(
            resource_ids, ratios_float, db, stratify_by=stratify_by
        )
    else:
        split_result = random_split(resource_ids, ratios_float)

    # ── 5. 批量更新子集归属 ──
    for subset, rids in split_result.items():
        iids = [item_map[rid] for rid in rids]
        if iids:
            db.query(DatasetItem).filter(
                DatasetItem.item_id.in_(iids)
            ).update(
                {DatasetItem.subset: subset},
                synchronize_session=False,
            )

    # ── 6. 更新 Dataset.split_config ──
    dataset.split_config = {
        "train": train_pct,
        "val": val_pct,
        "test": test_pct,
        "strategy": strategy,
    }
    dataset.save(db)

    # ── 7. 计算分布统计 ──
    distribution = calculate_split_distribution(db, dataset_id, split_result)

    # ── 8. 审计日志 ──
    AuditLog(
        user_id=dataset.owner_id,
        action="split_dataset",
        target_type="dataset",
        target_id=dataset_id,
        after_state={
            "split_config": dataset.split_config,
            "strategy": strategy,
        },
    ).save(db)

    return distribution


# ═══════════════════════════════════════════════════════════════════════════════
# 冻结 / 发布 / 可见范围
# ═══════════════════════════════════════════════════════════════════════════════


def freeze_dataset(db: Session, dataset_id: int) -> Dataset:
    """冻结数据集。将状态从 draft 改为 frozen，此后禁止任何写操作。

    流程：
    1. 校验 dataset.status = 'draft'
    2. 校验数据集非空（至少有 1 条 DatasetItem）
    3. Dataset.update_status(db, dataset_id, 'frozen')
    4. 记录审计日志

    冻结后的行为：
    - 不可修改筛选条件
    - 不可重新划分子集
    - 不可增删条目
    - 可查看、可导出

    API: POST /api/datasets/{id}/freeze
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅草稿状态的数据集可以冻结，当前状态：{dataset.status}",
        )

    # 校验非空
    item_count = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_id == dataset_id)
        .count()
    )
    if item_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="数据集为空，至少需要 1 个样本才能冻结",
        )

    Dataset.update_status(db, dataset_id, "frozen")

    AuditLog(
        user_id=dataset.owner_id,
        action="freeze_dataset",
        target_type="dataset",
        target_id=dataset_id,
        after_state={"status": "frozen"},
    ).save(db)

    db.refresh(dataset)
    return dataset


def unfreeze_dataset(db: Session, dataset_id: int) -> Dataset:
    """解冻数据集（管理员特权）。

    将 frozen 回退为 draft，允许重新编辑。
    仅管理员可调用（API 层 RBAC 校验）。

    API: POST /api/datasets/{id}/unfreeze
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.status != "frozen":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅已冻结状态的数据集可以解冻，当前状态：{dataset.status}",
        )

    Dataset.update_status(db, dataset_id, "draft")

    AuditLog(
        user_id=dataset.owner_id,
        action="unfreeze_dataset",
        target_type="dataset",
        target_id=dataset_id,
        after_state={"status": "draft"},
    ).save(db)

    db.refresh(dataset)
    return dataset


def publish_dataset(
    db: Session,
    dataset_id: int,
    visibility: str,
) -> Dataset:
    """发布数据集。

    流程：
    1. 若当前状态为 draft，先自动 freeze
    2. 校验 review_status（若申请公开且标注未经审核，系统提示）
    3. Dataset.update_status() → 'published'
    4. Dataset.set_visibility() 设置可见范围
    5. 若 visibility='public' 且 review_status='not_submitted'，自动提交审核
    6. 记录审计日志

    API: POST /api/datasets/{id}/publish
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )

    # 终态检查
    if dataset.status == "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="数据集已发布，不可重复操作",
        )

    # 若为 draft，先自动冻结
    if dataset.status == "draft":
        # 校验非空
        item_count = (
            db.query(DatasetItem)
            .filter(DatasetItem.dataset_id == dataset_id)
            .count()
        )
        if item_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="数据集为空，至少需要 1 个样本才能发布",
            )
        Dataset.update_status(db, dataset_id, "frozen")

    # 发布
    Dataset.update_status(db, dataset_id, "published")
    Dataset.set_visibility(db, dataset_id, visibility)

    # 公开且未提交审核 → 自动提交审核（调用设计报告规定的独立函数）
    if visibility == "public" and dataset.review_status == "not_submitted":
        submit_for_review(db, dataset_id)

    AuditLog(
        user_id=dataset.owner_id,
        action="publish_dataset",
        target_type="dataset",
        target_id=dataset_id,
        after_state={
            "status": "published",
            "visibility": visibility,
            "review_status": dataset.review_status,
        },
    ).save(db)

    db.refresh(dataset)
    return dataset


def submit_for_review(db: Session, dataset_id: int) -> Dataset:
    """提交公开审核。将 review_status 改为 submitted，等待审核员认领。

    设计报告 §3.3 独立端点，允许用户在不发布的情况下单独提交审核。

    API: POST /api/datasets/{id}/submit-review
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.review_status != "not_submitted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"当前审核状态为 {dataset.review_status}，无需重复提交",
        )

    dataset.review_status = "submitted"
    dataset.save(db)

    AuditLog(
        user_id=dataset.owner_id,
        action="submit_for_review",
        target_type="dataset",
        target_id=dataset_id,
        after_state={"review_status": "submitted"},
    ).save(db)

    db.refresh(dataset)
    return dataset


def change_visibility(
    db: Session,
    dataset_id: int,
    visibility: str,
) -> Dataset:
    """修改可见范围。

    public → private：
    - 从数据集市场下架
    - TODO: 检测是否有其他用户的评测任务依赖此数据集，若有则提示影响

    private → public：
    - 若标注未经审核（review_status='not_submitted'），自动提交审核
    - 数据集市场标记为"社区贡献"

    API: PUT /api/datasets/{id}/visibility
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )

    if dataset.status != "published":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"仅已发布的数据集可以修改可见范围，当前状态：{dataset.status}",
        )

    old_visibility = dataset.visibility

    # public → private
    if visibility == "private" and old_visibility == "public":
        # TODO Phase 3/4: 检测 eval_tasks 中是否有其他用户的评测依赖此数据集
        pass

    # private → public：自动提交审核
    if visibility == "public" and old_visibility == "private":
        if dataset.review_status == "not_submitted":
            submit_for_review(db, dataset_id)

    Dataset.set_visibility(db, dataset_id, visibility)

    AuditLog(
        user_id=dataset.owner_id,
        action="change_visibility",
        target_type="dataset",
        target_id=dataset_id,
        before_state={"visibility": old_visibility},
        after_state={"visibility": visibility},
    ).save(db)

    db.refresh(dataset)
    return dataset


# ═══════════════════════════════════════════════════════════════════════════════
# 导出
# ═══════════════════════════════════════════════════════════════════════════════


def export_dataset(
    db: Session,
    dataset_id: int,
    format: str,
    subset: str | None,
    user_id: int,
) -> dict[str, Any]:
    """数据集导出（同步版本）。

    参数：
    - format: 'coco' / 'voc' / 'yolo'
    - subset: 'train' / 'val' / 'test' / None（全部）

    流程：
    1. 校验数据集可见性（私有数据集仅拥有者可导出）
    2. 根据格式调用 FormatConverter 对应方法
    3. 流式打包为 ZIP
    4. 上传到 MinIO
    5. 返回签名 URL（有效期 1h）

    API: GET /api/datasets/{id}/export
    """
    # ── 1. 校验可见性 ──
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.visibility == "private" and dataset.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="私有数据集仅拥有者可导出",
        )

    # ── 2. Redis 频率限制（设计报告功能 6） ──
    rate_key = f"export_limit:{user_id}"
    redis_client = get_redis_client()
    current_count = redis_client.incr(rate_key)
    if current_count == 1:
        redis_client.expire(rate_key, 3600)  # 1 小时窗口
    if current_count > 10:  # 每小时最多 10 次
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="导出请求过于频繁，请稍后再试（每小时上限 10 次）",
        )

    # ── 3. 调用 FormatConverter ──
    if format not in ("coco", "voc", "yolo"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的导出格式: {format}，支持 coco/voc/yolo",
        )

    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if format == "coco":
            coco_dict = FormatConverter.to_coco(db, dataset_id, subset)
            json_str = json.dumps(coco_dict, ensure_ascii=False, indent=2)
            zf.writestr("annotations.json", json_str)

        elif format == "voc":
            xml_files = FormatConverter.to_voc(db, dataset_id, subset)
            for base_name, xml_str in xml_files:
                zf.writestr(f"{base_name}.xml", xml_str)

        elif format == "yolo":
            txt_files, yaml_content = FormatConverter.to_yolo(db, dataset_id, subset)
            for base_name, txt_content in txt_files:
                zf.writestr(f"{base_name}.txt", txt_content)
            zf.writestr("data.yaml", yaml_content)

    # ── 4. 上传 ZIP 到 MinIO ──
    zip_buffer.seek(0)
    subset_suffix = f"_{subset}" if subset else ""
    object_name = f"exports/dataset_{dataset_id}{subset_suffix}_{uuid.uuid4().hex[:8]}.zip"
    file_path = upload_file(
        zip_buffer.read(),
        object_name,
        content_type="application/zip",
    )

    # ── 5. 生成签名 URL ──
    download_url = get_file_url(file_path, expires=3600)

    # ── 6. 审计日志 ──
    AuditLog(
        user_id=user_id,
        action="export_dataset",
        target_type="dataset",
        target_id=dataset_id,
        after_state={
            "format": format,
            "subset": subset,
            "file_path": file_path,
        },
    ).save(db)

    return {
        "dataset_id": dataset_id,
        "format": format,
        "subset": subset or "all",
        "download_url": download_url,
        "expires_in": 3600,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 版本管理
# ═══════════════════════════════════════════════════════════════════════════════


def get_dataset_versions(
    db: Session, dataset_id: int
) -> list[dict[str, Any]]:
    """查看版本历史。返回数据集所有语义化版本的列表。

    API: GET /api/datasets/{id}/versions
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )

    versions = DatasetVersion.list_by_dataset(db, dataset_id)
    return [
        {
            "version_id": v.version_id,
            "version": v.version,
            "change_log": v.change_log,
            "sample_count": len(v.item_ids_snapshot) if v.item_ids_snapshot else 0,
            "split_config": v.split_config_snapshot,
            "created_by": v.created_by,
            "created_at": v.created_at,
        }
        for v in versions
    ]


def save_new_version(
    db: Session,
    dataset_id: int,
    change_log: str,
    user_id: int,
    bump_type: str = "minor",
) -> dict[str, Any]:
    """保存新版本。强制填写变更日志。

    流程：
    1. 根据 bump_type 判定新版本号
    2. 快照当前 filters + split_config + DatasetItem 列表
    3. 写入 dataset_versions 表
    4. 更新 datasets.version 字段

    API: POST /api/datasets/{id}/versions
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )

    # ── 1. 计算新版本号 ──
    current = dataset.version or "v1.0"
    # 解析 "v{major}.{minor}"
    try:
        parts = current.lstrip("v").split(".")
        major, minor = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        major, minor = 1, 0

    if bump_type == "major":
        major += 1
        minor = 0
    else:
        minor += 1

    new_version = f"v{major}.{minor}"

    # ── 2. 快照当前状态 ──
    items = (
        db.query(DatasetItem)
        .filter(DatasetItem.dataset_id == dataset_id)
        .all()
    )
    item_ids_snapshot = {
        str(it.resource_id): it.subset for it in items
    }

    # ── 3. 写入 dataset_versions ──
    DatasetVersion.create_snapshot(
        db,
        dataset_id=dataset_id,
        version=new_version,
        filters_snapshot=dataset.filters,
        split_config_snapshot=dataset.split_config,
        item_ids_snapshot=item_ids_snapshot,
        change_log=change_log,
        created_by=user_id,
    )

    # ── 4. 更新 datasets.version ──
    dataset.version = new_version
    dataset.save(db)

    # ── 5. 审计日志 ──
    AuditLog(
        user_id=user_id,
        action="save_dataset_version",
        target_type="dataset",
        target_id=dataset_id,
        after_state={
            "version": new_version,
            "sample_count": len(item_ids_snapshot),
            "change_log": change_log,
        },
    ).save(db)

    return {
        "version": new_version,
        "sample_count": len(item_ids_snapshot),
        "change_log": change_log,
    }


def compare_versions(
    db: Session,
    dataset_id: int,
    v1: str,
    v2: str,
) -> dict[str, Any]:
    """对比版本差异。

    返回新增样本 / 删除样本 / 子集变更 / 筛选条件变更。

    API: GET /api/datasets/{id}/diff?v1=...&v2=...
    """
    snap1 = DatasetVersion.get_by_version(db, dataset_id, v1)
    snap2 = DatasetVersion.get_by_version(db, dataset_id, v2)

    if snap1 is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"版本 {v1} 不存在",
        )
    if snap2 is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"版本 {v2} 不存在",
        )

    items1: dict[str, str] = snap1.item_ids_snapshot or {}
    items2: dict[str, str] = snap2.item_ids_snapshot or {}

    ids1 = set(items1.keys())
    ids2 = set(items2.keys())

    # 批量查询涉及变更的 DataResource 名称
    changed_ids = (ids2 - ids1) | (ids1 - ids2) | {
        rid for rid in (ids1 & ids2) if items1[rid] != items2[rid]
    }
    resource_names: dict[int, str] = {}
    if changed_ids:
        rid_list = [int(rid) for rid in changed_ids]
        resources = (
            db.query(DataResource)
            .filter(DataResource.resource_id.in_(rid_list))
            .all()
        )
        resource_names = {r.resource_id: r.name for r in resources}

    # 新增：v2 有、v1 无
    added = [
        {
            "resource_id": int(rid),
            "name": resource_names.get(int(rid), f"resource_{rid}"),
            "subset": items2[rid],
        }
        for rid in (ids2 - ids1)
    ]
    # 删除：v1 有、v2 无
    removed = [
        {
            "resource_id": int(rid),
            "name": resource_names.get(int(rid), f"resource_{rid}"),
            "subset": items1[rid],
        }
        for rid in (ids1 - ids2)
    ]
    # 子集变更：两版本都有但 subset 不同
    subset_changes = [
        {
            "resource_id": int(rid),
            "name": resource_names.get(int(rid), f"resource_{rid}"),
            "from": items1[rid],
            "to": items2[rid],
        }
        for rid in (ids1 & ids2)
        if items1[rid] != items2[rid]
    ]
    # 筛选条件变更
    filter_changes: dict[str, Any] = {"v1": snap1.filters_snapshot, "v2": snap2.filters_snapshot}

    return {
        "v1": v1,
        "v2": v2,
        "added": added,
        "removed": removed,
        "subset_changes": subset_changes,
        "filter_changes": filter_changes,
        "summary": (
            f"新增 {len(added)} 个样本, "
            f"删除 {len(removed)} 个样本, "
            f"{len(subset_changes)} 个子集变更"
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 归档 / 恢复
# ═══════════════════════════════════════════════════════════════════════════════


def archive_dataset(
    db: Session,
    dataset_id: int,
    user_id: int,
) -> Dataset:
    """归档数据集。

    行为：
    - archive_status: active → archived
    - 归档后仅保留检索和预览
    - 不可新建标注、不可训练或评测引用、不可下载
    - 与冻结/发布状态相互独立（正交关系）
    - 产生审计日志

    API: POST /api/datasets/{id}/archive
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.archive_status == "archived":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="数据集已归档，无需重复操作",
        )

    Dataset.set_archive_status(db, dataset_id, "archived")

    AuditLog(
        user_id=user_id,
        action="archive_dataset",
        target_type="dataset",
        target_id=dataset_id,
        after_state={"archive_status": "archived"},
    ).save(db)

    db.refresh(dataset)
    return dataset


def restore_dataset(
    db: Session,
    dataset_id: int,
    user_id: int,
) -> Dataset:
    """恢复数据集。

    行为：
    - archive_status: archived → active
    - 恢复正常功能
    - 产生审计日志

    API: POST /api/datasets/{id}/restore
    """
    dataset = db.query(Dataset).filter(Dataset.dataset_id == dataset_id).first()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="数据集不存在",
        )
    if dataset.archive_status != "archived":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="仅已归档的数据集可以恢复",
        )

    Dataset.set_archive_status(db, dataset_id, "active")

    AuditLog(
        user_id=user_id,
        action="restore_dataset",
        target_type="dataset",
        target_id=dataset_id,
        after_state={"archive_status": "active"},
    ).save(db)

    db.refresh(dataset)
    return dataset


def batch_archive(
    db: Session,
    filters: dict[str, Any],
    user_id: int,
) -> dict[str, Any]:
    """批量归档。按条件查询数据集后批量执行归档操作。

    筛选条件（全部可选）：
    - owner_id: int — 按拥有者筛选
    - modality: str — 按模态筛选（filters JSONB）
    - created_before: str — 创建时间早于（ISO 格式）

    返回 {archived_count, skipped_count, matched_count}

    API: POST /api/admin/datasets/batch-archive
    """
    from datetime import datetime

    query = db.query(Dataset).filter(
        Dataset.archive_status == "active"
    )

    if owner_id := filters.get("owner_id"):
        query = query.filter(Dataset.owner_id == owner_id)
    if modality := filters.get("modality"):
        query = query.filter(Dataset.filters["modality"].astext == modality)
    if created_before := filters.get("created_before"):
        try:
            query = query.filter(
                Dataset.created_at < datetime.fromisoformat(created_before)
            )
        except (ValueError, TypeError):
            pass

    matched = query.all()
    archived_count = 0
    skipped_count = 0

    for dataset in matched:
        if dataset.archive_status == "archived":
            skipped_count += 1
            continue
        Dataset.set_archive_status(db, dataset.dataset_id, "archived")
        archived_count += 1

    AuditLog(
        user_id=user_id,
        action="batch_archive_datasets",
        target_type="dataset",
        target_id=0,
        after_state={
            "archived_count": archived_count,
            "matched_count": len(matched),
            "filters": filters,
        },
    ).save(db)

    return {
        "archived_count": archived_count,
        "skipped_count": skipped_count,
        "matched_count": len(matched),
    }
