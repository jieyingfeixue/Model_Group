"""数据资源路由 — /api/data/*"""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.models.data_resource import DataResource
from app.schemas.data_resource import DataResourceCreate, DataResourceResponse
from app.services import normal_data_service

router = APIRouter(tags=["Data"])


@router.post("/data/upload", response_model=list[DataResourceResponse], status_code=201)
async def upload_data(
    files: list[UploadFile] = File(..., description="图片文件，支持多文件上传"),
    name: str = Form(..., description="文件名"),
    modality: str = Form("visible", description="模态类型"),
    meta_info: str = Form("{}", description="JSON 字符串，附加元信息"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传图片到 MinIO。multipart/form-data，Pillow 自动提取宽高/通道数。

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
    DataResourceCreate(name=name, modality=meta.get("modality", "visible"), meta_info=meta)

    resources = normal_data_service.upload_data(
        db,
        files=files,
        meta_info=meta,
        owner_id=current_user.user_id,
    )
    return [DataResourceResponse.model_validate(r) for r in resources]


@router.get("/data", response_model=dict[str, Any])
def list_data(
    modality: str | None = Query(None),
    annotation_status: str | None = Query(None),
    status: str | None = Query(None),
    scene: str | None = Query(None),
    weather: str | None = Query(None),
    time_of_day: str | None = Query(None),
    terrain: str | None = Query(None),
    obstacle: str | None = Query(None),
    batch_id: str | None = Query(None),
    sample_group: int | None = Query(None),
    start_time: str | None = Query(None, description="起始时间 ISO 字符串"),
    end_time: str | None = Query(None, description="结束时间 ISO 字符串"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=6000),
    db: Session = Depends(get_db),
):
    """查询平台全部数据资源（数据浏览），支持多条件筛选 + 分页"""
    filters: dict[str, Any] = {}
    if modality:
        filters["modality"] = modality
    if annotation_status:
        filters["annotation_status"] = annotation_status
    if status:
        filters["status"] = status
    if scene:
        filters["scene"] = scene
    if weather:
        filters["weather"] = weather
    if time_of_day:
        filters["time_of_day"] = time_of_day
    if terrain:
        filters["terrain"] = terrain
    if obstacle:
        filters["obstacle"] = obstacle
    if batch_id:
        filters["batch_id"] = batch_id
    if sample_group is not None:
        filters["sample_group"] = sample_group
    if start_time:
        filters["start_time"] = start_time
    if end_time:
        filters["end_time"] = end_time

    items, total = DataResource.search(db, filters=filters, page=page, size=size)
    return {
        "items": [DataResourceResponse.model_validate(r) for r in items],
        "total": total,
        "page": page,
        "size": size,
    }


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
