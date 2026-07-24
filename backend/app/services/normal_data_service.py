"""数据管理 Service — upload_data / list_my_data"""

import os
import uuid
from datetime import datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy.orm import Session

from app.core.storage import upload_file
from app.models.data_resource import DataResource


def upload_data(
    db: Session,
    files: list[UploadFile],
    meta_info: dict[str, Any],
    owner_id: int,
) -> list[DataResource]:
    """上传图片到 MinIO，提取元信息，写入 data_resources 表。

    流程：
    1. 每张图片通过 Pillow 提取 width/height/channels/file_size
    2. 合并用户提供的 meta_info（用户字段优先）
    3. 上传到 MinIO → 获得 file_path
    4. DataResource(...).save(db) → 返回记录列表

    Args:
        files: 上传文件列表
        meta_info: 用户提供的附加元信息（scene/weather/device 等）
        owner_id: 上传者 ID

    Returns:
        创建的 DataResource 列表

    Raises:
        HTTPException 400: 文件列表为空
    """

    if not files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请至少选择一个文件上传",
        )

    resources: list[DataResource] = []

    for file in files:
        # 1. 读取文件内容
        content = file.filename or ""
        file_bytes = b""

        try:
            file_bytes = file.file.read()
        except Exception:
            file_bytes = b""

        if not file_bytes:
            continue

        # 2. Pillow 提取图片元信息
        extracted: dict[str, Any] = {"file_size": len(file_bytes)}
        try:
            img = Image.open(__import__("io").BytesIO(file_bytes))
            extracted["width"] = img.width
            extracted["height"] = img.height

            if img.mode == "RGB":
                extracted["channels"] = 3
            elif img.mode == "RGBA":
                extracted["channels"] = 4
            elif img.mode == "L":
                extracted["channels"] = 1
            else:
                extracted["channels"] = len(img.getbands()) if img.getbands() else 3
        except Exception:
            pass

        # 3. 合并 meta_info：自动提取的为基础，用户提供的覆盖
        merged_meta = {**extracted, **meta_info}

        # 4. 上传到 MinIO
        ext = os.path.splitext(content)[1] if content else ".bin"
        object_name = f"images/{uuid.uuid4().hex}{ext}"
        content_type = file.content_type or "application/octet-stream"

        file_path = upload_file(file_bytes, object_name, content_type)

        # 5. 写入数据库
        resource = DataResource(
            name=content,
            owner_id=owner_id,
            modality=meta_info.get("modality", "visible"),
            file_path=file_path,
            meta_info=merged_meta,
        )
        resource.save(db)
        resources.append(resource)

    return resources


def get_data_detail(db: Session, resource_id: int) -> DataResource | None:
    """获取单个数据资源详情"""
    return db.query(DataResource).filter(DataResource.resource_id == resource_id).first()


def get_data_versions(db: Session, resource_id: int) -> dict[str, Any]:
    """获取数据资源版本历史。

    当前版本号记录在 DataResource.version，历史版本需从 data_versions 表读取。
    Phase1 返回当前版本信息；Phase3 扩展为完整版本链。
    """
    resource = db.query(DataResource).filter(DataResource.resource_id == resource_id).first()
    if resource is None:
        return None
    return {
        "resource_id": resource_id,
        "versions": [
            {
                "version": resource.version,
                "updated_at": resource.updated_at.isoformat() if resource.updated_at else None,
            }
        ],
        "current_version": resource.version,
    }


def update_data_metadata(
    db: Session, resource_id: int, meta_info: dict[str, Any]
) -> DataResource | None:
    """更新数据资源元信息（合并模式），版本号自动递增"""
    return DataResource.update_metadata(db, resource_id, meta_info)


def align_multi_modal(
    db: Session, resource_ids: list[int]
) -> dict[str, Any]:
    """多模态帧对齐：按 sample_group 将同一时刻的多模态数据分组。

    返回按 sample_group 分组的结果，标注每组的模态类型。
    """
    resources = (
        db.query(DataResource)
        .filter(DataResource.resource_id.in_(resource_ids))
        .all()
    )

    found_ids = {r.resource_id for r in resources}
    ungrouped = [rid for rid in resource_ids if rid not in found_ids]

    # 按 sample_group 分组
    groups: dict[str, dict[str, Any]] = {}
    for r in resources:
        meta = r.meta_info or {}
        sg = str(meta.get("sample_group", f"_single_{r.resource_id}"))
        if sg not in groups:
            groups[sg] = {
                "sample_group": sg,
                "modalities": [],
                "resource_ids": [],
                "scene": meta.get("scene"),
                "time_of_day": meta.get("time_of_day"),
            }
        if r.modality not in groups[sg]["modalities"]:
            groups[sg]["modalities"].append(r.modality)
        groups[sg]["resource_ids"].append(r.resource_id)

    return {
        "groups": list(groups.values()),
        "total_groups": len(groups),
        "ungrouped": ungrouped,
    }


def list_my_data(
    db: Session,
    owner_id: int,
    filters: dict[str, Any] | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[DataResource], int]:
    """按条件分页查询当前用户的数据资源。

    filters 支持: modality, annotation_status, status, scene, start_time, end_time

    API: GET /api/data
    """
    filters = filters or {}

    # 时间范围转换为 datetime
    if start_time := filters.get("start_time"):
        try:
            filters["start_time"] = datetime.fromisoformat(start_time)
        except ValueError:
            del filters["start_time"]
    if end_time := filters.get("end_time"):
        try:
            filters["end_time"] = datetime.fromisoformat(end_time)
        except ValueError:
            del filters["end_time"]

    return DataResource.get_by_owner(db, owner_id, filters, page, size)
