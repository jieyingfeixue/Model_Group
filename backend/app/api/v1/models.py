"""模型管理路由 — /api/models/*"""

from typing import Any

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.model import (
    ModelDetailResponse,
    ModelLineageResponse,
    ModelResponse,
    ModelVersionResponse,
    ModelVisibilityRequest,
)
from app.services import normal_model_service

router = APIRouter(tags=["Models"])


@router.post("/models", response_model=ModelResponse, status_code=201)
async def register_model(
    file: UploadFile = File(...),
    name: str = Form(...),
    framework: str = Form(...),
    metadata: str = Form("{}"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """注册模型并创建初始版本（Phase2：校验扩展名与 meta_info）"""
    meta = normal_model_service.parse_metadata_form(metadata)
    model = normal_model_service.register_model(
        db,
        name=name,
        framework=framework,
        file=file,
        metadata=meta,
        owner_id=current_user.user_id,
    )
    return ModelResponse.model_validate(model)


@router.get("/models")
def list_models(
    framework: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """我的模型列表"""
    filters: dict[str, Any] = {}
    if framework:
        filters["framework"] = framework
    if status:
        filters["status"] = status
    items, total = normal_model_service.list_my_models(
        db, owner_id=current_user.user_id, filters=filters, page=page, size=size
    )
    return {
        "items": [ModelResponse.model_validate(m) for m in items],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/models/baselines", response_model=list[ModelResponse])
def list_baselines(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """平台基线模型（只读）"""
    items = normal_model_service.list_baselines(db)
    return [ModelResponse.model_validate(m) for m in items]


@router.get("/models/{model_id}", response_model=ModelDetailResponse)
def get_model(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """模型详情 + 版本列表"""
    model, versions = normal_model_service.get_model_detail(db, model_id, current_user)
    payload = ModelResponse.model_validate(model).model_dump()
    payload["versions"] = [ModelVersionResponse.model_validate(v) for v in versions]
    return ModelDetailResponse(**payload)


@router.get("/models/{model_id}/lineage", response_model=ModelLineageResponse)
def get_model_lineage(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """模型多版本血缘树"""
    data = normal_model_service.get_model_lineage(db, model_id, current_user)
    return ModelLineageResponse(
        model_id=data["model_id"],
        versions=[ModelVersionResponse.model_validate(v) for v in data["versions"]],
        tree=data["tree"],
    )


@router.get(
    "/models/{model_id}/versions/{version_id}",
    response_model=ModelVersionResponse,
)
def get_model_version(
    model_id: int,
    version_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """单个版本详情"""
    version = normal_model_service.get_model_version(
        db, model_id, version_id, current_user
    )
    return ModelVersionResponse.model_validate(version)


@router.post(
    "/models/{model_id}/versions",
    response_model=ModelVersionResponse,
    status_code=201,
)
async def upload_version(
    model_id: int,
    file: UploadFile = File(...),
    version_note: str = Form(""),
    trained_on_dataset_id: int | None = Form(None),
    parent_version_id: int | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传模型新版本（可指定父版本与训练数据集）"""
    version = normal_model_service.upload_model_version(
        db,
        model_id=model_id,
        file=file,
        version_note=version_note,
        owner_id=current_user.user_id,
        trained_on_dataset_id=trained_on_dataset_id,
        parent_version_id=parent_version_id,
    )
    return ModelVersionResponse.model_validate(version)


@router.put("/models/{model_id}/visibility", response_model=ModelResponse)
def set_visibility(
    model_id: int,
    body: ModelVisibilityRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """设置模型可见性"""
    model = normal_model_service.set_model_visibility(
        db, model_id, body.is_public, current_user.user_id
    )
    return ModelResponse.model_validate(model)


@router.delete("/models/{model_id}", status_code=204)
def deprecate_model(
    model_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """废弃模型"""
    normal_model_service.deprecate_model(db, model_id, current_user)
