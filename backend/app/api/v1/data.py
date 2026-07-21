"""数据资源路由 — /api/data/*"""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.data_resource import DataResource
from app.models.user import User
from app.schemas.data_resource import (
    AlignmentRequest,
    AlignmentResponse,
    DataResourceCreate,
    DataResourceResponse,
)
from app.services import normal_data_service

router = APIRouter(tags=["Data"])


@router.post("/data/upload", response_model=list[DataResourceResponse], status_code=201)
async def upload_data(
    files: list[UploadFile] = File(..., description="图片文件，支持多文件上传"),
    name: str = Form(..., description="文件名"),
    modality: str = Form("visible", description="模态类型"),
    meta_info: str = Form("{}", description="JSON 字符串，附加元信息"),
    captured_at: float | None = Form(None, description="采集时间戳（Unix 秒），可选"),
    annotation_file: UploadFile | None = File(None, description="标注文件（COCO JSON / VOC ZIP / YOLO ZIP）"),
    format: str | None = Form(None, description="标注格式：coco / voc / yolo"),
    task_id: int | None = Form(None, description="关联的标注任务 ID，不传则自动创建"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传图片到 MinIO。可选附带标注文件，自动解析并导入 annotations 表。

    Form 参数经 DataResourceCreate Schema 校验后再传入 Service。
    """
    import json

    meta: dict[str, Any] = {}
    try:
        meta = json.loads(meta_info)
    except json.JSONDecodeError:
        pass

    # 将 Form 字段合并进 meta_info（Form 字段优先级低于 meta_info JSON 中的同名键）
    if modality:
        meta.setdefault("modality", modality)

    # 通过 Schema 校验
    DataResourceCreate(name=name, modality=meta.get("modality", "visible"), meta_info=meta, captured_at=captured_at)

    # 附带标注文件 → 导入模式
    if annotation_file and format:
        result = normal_data_service.import_with_annotations(
            db,
            files=files,
            annotation_file=annotation_file,
            format=format,
            owner_id=current_user.user_id,
            meta_info=meta,
            task_id=task_id,
        )
        return {
            "resources": [DataResourceResponse.model_validate(r) for r in result["resources"]],
            "task_id": result["task_id"],
            "annotations_count": result["annotations_count"],
            "warnings": result["warnings"],
        }

    # 普通上传模式
    resources = normal_data_service.upload_data(
        db,
        files=files,
        meta_info=meta,
        owner_id=current_user.user_id,
        captured_at=captured_at,
    )
    return [DataResourceResponse.model_validate(r) for r in resources]


@router.get("/data", response_model=dict[str, Any])
def list_data(
    modality: str | None = Query(None),
    annotation_status: str | None = Query(None),
    status: str | None = Query(None),
    scene: str | None = Query(None),
    start_time: str | None = Query(None, description="起始时间 ISO 字符串"),
    end_time: str | None = Query(None, description="结束时间 ISO 字符串"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询当前用户的数据资源列表，支持多条件筛选 + 分页"""
    filters: dict[str, Any] = {}
    if modality:
        filters["modality"] = modality
    if annotation_status:
        filters["annotation_status"] = annotation_status
    if status:
        filters["status"] = status
    if scene:
        filters["scene"] = scene
    if start_time:
        filters["start_time"] = start_time
    if end_time:
        filters["end_time"] = end_time

    items, total = normal_data_service.list_my_data(
        db,
        owner_id=current_user.user_id,
        filters=filters,
        page=page,
        size=size,
    )
    return {
        "items": [DataResourceResponse.model_validate(r) for r in items],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/data/align", response_model=AlignmentResponse, status_code=201)
def align_data(
    body: AlignmentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """多模态时间戳对齐。按选定策略将多传感器帧配对，结果写入数据库。"""
    result = normal_data_service.multi_modal_align(
        db,
        resource_ids=body.resource_ids,
        strategy=body.strategy,
        params=body.params,
        user_id=current_user.user_id,
    )
    return AlignmentResponse(**result)


@router.get("/data/resources/{resource_id}", response_model=DataResourceResponse)
def get_data_resource(
    resource_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单条数据资源详情（前端 DataDetail 使用）"""
    resource = db.get(DataResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    if (
        resource.owner_id != current_user.user_id
        and current_user.role != "admin"
    ):
        raise HTTPException(status_code=403, detail="无权查看该资源")
    return DataResourceResponse.model_validate(resource)


@router.get("/images/{resource_id}")
def get_image(resource_id: int, db: Session = Depends(get_db)):
    """根据 resource_id 返回图片二进制"""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from minio import Minio
    from app.core.config import settings as s

    resource = db.get(DataResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    client = Minio(endpoint=s.MINIO_ENDPOINT, access_key=s.MINIO_ACCESS_KEY,
                   secret_key=s.MINIO_SECRET_KEY, secure=s.MINIO_SECURE)
    try:
        path = resource.file_path.lstrip("/")
        parts = path.split("/", 1)
        data = client.get_object(parts[0], parts[1])
        return StreamingResponse(data.stream(), media_type="image/jpeg")
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")


@router.get("/images/{resource_id}/thumbnail")
def get_thumbnail(resource_id: int, size: int = 240, db: Session = Depends(get_db)):
    """根据 resource_id 返回缩略图"""
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from minio import Minio
    from PIL import Image as PILImage
    from app.core.config import settings as s

    resource = db.get(DataResource, resource_id)
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    client = Minio(endpoint=s.MINIO_ENDPOINT, access_key=s.MINIO_ACCESS_KEY,
                   secret_key=s.MINIO_SECRET_KEY, secure=s.MINIO_SECURE)
    try:
        path = resource.file_path.lstrip("/")
        parts = path.split("/", 1)
        data = client.get_object(parts[0], parts[1])
        img = PILImage.open(BytesIO(data.read()))
        img.thumbnail((size, size))
        buf = BytesIO()
        img.save(buf, format="JPEG", quality=85)
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/jpeg")
    except Exception:
        raise HTTPException(status_code=404, detail="Image not found")
