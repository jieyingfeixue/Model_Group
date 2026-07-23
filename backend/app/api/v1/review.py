"""审核路由 — /api/review/*"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.user import User
from app.schemas.review import (
    AnnotationReviewListResponse,
    AnnotationReviewItem,
    AnnotationVerdictRequest,
    AnnotationVerdictResponse,
    DatasetReviewItem,
    DatasetReviewListResponse,
    DatasetVerdictRequest,
    DatasetVerdictResponse,
)
from app.services import reviewer_dataset_service, reviewer_annotation_service

router = APIRouter(prefix="/review", tags=["Review"])


# ════════════════════════════════════════════════════════════
#  数据集审核
# ════════════════════════════════════════════════════════════

# ──── GET /api/review/datasets ────

@router.get("/datasets", response_model=DatasetReviewListResponse)
def list_review_datasets(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    claimed_only: bool = Query(False, description="仅看我已认领的"),
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
):
    """审核员查看待审核数据集列表"""
    reviewer_id = current_user.user_id if claimed_only else None
    items, total = reviewer_dataset_service.list_pending_datasets(
        db, reviewer_id=reviewer_id, page=page, size=size
    )
    return DatasetReviewListResponse(
        items=[DatasetReviewItem(**it) for it in items],
        total=total,
        page=page,
        size=size,
    )


# ──── POST /api/review/datasets/{dataset_id}/claim ────

@router.post("/datasets/{dataset_id}/claim")
def claim_dataset_review(
    dataset_id: int,
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
):
    """审核员认领数据集审核任务"""
    return reviewer_dataset_service.claim_dataset(db, dataset_id, current_user.user_id)


# ──── POST /api/review/datasets/{dataset_id}/verdict ────

@router.post("/datasets/{dataset_id}/verdict", response_model=DatasetVerdictResponse)
def submit_dataset_verdict(
    dataset_id: int,
    body: DatasetVerdictRequest,
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
):
    """审核员提交数据集审核结果"""
    result = reviewer_dataset_service.submit_dataset_verdict(
        db, dataset_id, body.verdict, current_user.user_id, body.notes
    )
    return DatasetVerdictResponse(**result)


# ════════════════════════════════════════════════════════════
#  标注审核
# ════════════════════════════════════════════════════════════

# ──── GET /api/review/annotation-tasks ────

@router.get("/annotation-tasks", response_model=AnnotationReviewListResponse)
def list_annotation_review_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
):
    """审核员查看标注审核任务列表"""
    items, total = reviewer_annotation_service.list_pending_annotation_tasks(
        db, page=page, size=size
    )
    return AnnotationReviewListResponse(
        items=[AnnotationReviewItem(**it) for it in items],
        total=total,
        page=page,
        size=size,
    )


# ──── POST /api/review/annotations/{annotation_id}/verdict ────

@router.post("/annotations/{annotation_id}/verdict", response_model=AnnotationVerdictResponse)
def submit_annotation_verdict(
    annotation_id: int,
    body: AnnotationVerdictRequest,
    current_user: User = Depends(require_role("admin", "reviewer")),
    db: Session = Depends(get_db),
):
    """审核员提交标注审核结果"""
    result = reviewer_annotation_service.submit_annotation_verdict(
        db, annotation_id, body.verdict, body.reject_reasons
    )
    return AnnotationVerdictResponse(**result)
