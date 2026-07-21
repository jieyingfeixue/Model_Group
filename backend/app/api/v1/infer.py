"""推理任务路由 — /api/infer/tasks/*"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.model import InferTaskCreate, InferTaskResponse
from app.services import normal_model_service

router = APIRouter(tags=["Infer"])


@router.post("/infer/tasks", response_model=InferTaskResponse, status_code=201)
def submit_infer(
    body: InferTaskCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交推理任务并入队 Celery"""
    task = normal_model_service.submit_infer(
        db,
        model_id=body.model_id,
        dataset_id=body.dataset_id,
        image_id=body.image_id,
        user_id=current_user.user_id,
    )
    return InferTaskResponse.model_validate(task)


@router.get("/infer/tasks/{task_id}/results", response_model=InferTaskResponse)
def get_infer_results(
    task_id: int,
    class_filter: int | None = Query(None),
    min_confidence: float = Query(0.1, ge=0.0, le=1.0),
    coord: str = Query(
        "both",
        description="坐标投影：norm=归一化xywh；pixel=像素xyxy；both=同时返回",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查看推理结果（Phase3：支持 coord=norm|pixel|both）"""
    task = normal_model_service.get_infer_results(
        db,
        task_id=task_id,
        user=current_user,
        class_filter=class_filter,
        min_confidence=min_confidence,
        coord=coord,
    )
    return InferTaskResponse.model_validate(task)


@router.get("/infer/tasks/{task_id}/visualize/{image_id}")
def visualize_infer(
    task_id: int,
    image_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """返回叠加框可视化图（Phase3：按像素框画在原图上）"""
    content = normal_model_service.visualize_infer(db, task_id, image_id, current_user)
    return Response(content=content, media_type="image/jpeg")
