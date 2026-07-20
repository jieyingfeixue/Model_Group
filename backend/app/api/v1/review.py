"""审核路由 — /api/review/*（数据集审核 + 标注审核）"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.user import User
from app.services import reviewer_annotation_service, reviewer_dataset_service

router = APIRouter(tags=["Review"])

# 审核员角色鉴权
_reviewer = Depends(require_role("reviewer", "admin"))


# ──── 数据集审核 ────


@router.get("/review/datasets", dependencies=[_reviewer])
def get_pending_datasets(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """查看待审核数据集列表（reviewer/admin）。"""
    datasets, total = reviewer_dataset_service.get_pending_datasets(
        db, page=page, size=size
    )
    return {
        "items": [
            {
                "dataset_id": ds.dataset_id,
                "name": ds.name,
                "owner_id": ds.owner_id,
                "status": ds.status,
                "review_status": ds.review_status,
                "version": ds.version,
                "created_at": ds.created_at,
                "updated_at": ds.updated_at,
            }
            for ds in datasets
        ],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/review/datasets/{dataset_id}/claim", dependencies=[_reviewer])
def claim_dataset_review(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """认领数据集审核。锁定数据集，reviewer_id 赋值。"""
    ds = reviewer_dataset_service.claim_dataset_review(
        db, dataset_id=dataset_id, reviewer_id=current_user.user_id
    )
    return {
        "dataset_id": ds.dataset_id,
        "review_status": ds.review_status,
        "reviewer_id": ds.reviewer_id,
        "message": "认领成功",
    }


@router.post("/review/datasets/{dataset_id}/unclaim", dependencies=[_reviewer])
def unclaim_dataset_review(
    dataset_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """放弃认领。回退为 submitted，清空 reviewer_id。"""
    ds = reviewer_dataset_service.unclaim_dataset_review(
        db, dataset_id=dataset_id, reviewer_id=current_user.user_id
    )
    return {
        "dataset_id": ds.dataset_id,
        "review_status": ds.review_status,
        "message": "已放弃认领",
    }


@router.get("/review/datasets/{dataset_id}/checklist", dependencies=[_reviewer])
def get_checklist(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """获取系统辅助检查结果（7 项自动检测）。"""
    return reviewer_dataset_service.get_review_checklist_result(db, dataset_id=dataset_id)


@router.post("/review/datasets/{dataset_id}/verdict", dependencies=[_reviewer])
def review_dataset(
    dataset_id: int,
    result: str = Query(..., description="approved / rejected"),
    failed_items: str | None = Query(None, description="不通过项编号，逗号分隔"),
    notes: str | None = Query(None, description="审核备注"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """审核裁决。approved → 发布；rejected → 写入不通过项和备注。"""
    failed_list = (
        [item.strip() for item in failed_items.split(",") if item.strip()]
        if failed_items
        else None
    )
    ds = reviewer_dataset_service.review_dataset(
        db,
        dataset_id=dataset_id,
        reviewer_id=current_user.user_id,
        result=result,
        failed_items=failed_list,
        notes=notes,
    )
    return {
        "dataset_id": ds.dataset_id,
        "review_status": ds.review_status,
        "status": ds.status,
        "review_notes": ds.review_notes,
        "message": "审核通过" if result == "approved" else "审核驳回",
    }


# ──── 标注审核 ────


@router.get("/review/annotation-tasks", dependencies=[_reviewer])
def get_pending_annotation_tasks(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """查看待审核标注任务列表（reviewer/admin）。"""
    tasks, total = reviewer_annotation_service.get_pending_annotation_tasks(
        db, page=page, size=size
    )
    return {
        "items": [
            {
                "task_id": t.task_id,
                "name": t.name,
                "schema_id": t.schema_id,
                "assignee_ids": t.assignee_ids,
                "status": t.status,
                "deadline": t.deadline,
                "created_by": t.created_by,
                "created_at": t.created_at,
            }
            for t in tasks
        ],
        "total": total,
        "page": page,
        "size": size,
    }


@router.post("/review/annotation-tasks/{task_id}/claim", dependencies=[_reviewer])
def claim_annotation_review(
    task_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """认领标注审核。锁定任务，校验不可审自己标的图。"""
    task = reviewer_annotation_service.claim_annotation_review(
        db, task_id=task_id, reviewer_id=current_user.user_id
    )
    return {
        "task_id": task.task_id,
        "status": task.status,
        "reviewer_id": task.reviewer_id,
        "message": "认领成功",
    }


@router.post("/review/annotation-tasks/{task_id}/sample", dependencies=[_reviewer])
def setup_sampling(
    task_id: int,
    ratio: float = Query(0.2, ge=0.1, le=1.0, description="抽检比例 10%-100%"),
    mode: str = Query("random", description="random / manual"),
    manual_ids: str | None = Query(None, description="手动模式下的 annotation_id 列表，逗号分隔"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """配置抽检。random 按比例随机抽样，manual 传入 annotation_id 列表。"""
    manual_list = None
    if mode == "manual" and manual_ids:
        manual_list = [
            int(x.strip()) for x in manual_ids.split(",") if x.strip().isdigit()
        ]
    result = reviewer_annotation_service.setup_sampling(
        db,
        task_id=task_id,
        reviewer_id=current_user.user_id,
        ratio=ratio,
        mode=mode,
        manual_ids=manual_list,
    )
    return result


@router.post("/review/annotations/{annotation_id}/verdict", dependencies=[_reviewer])
def review_annotation(
    annotation_id: int,
    action: str = Query(..., description="approved / rejected"),
    reject_codes: str | None = Query(None, description="驳回原因代码，逗号分隔（如 T01,T03）"),
    note: str | None = Query(None, description="审核备注"),
    db: Session = Depends(get_db),
):
    """审核单张标注。rejected 时必须选至少一项 T01-T10 驳回原因。"""
    codes = None
    if reject_codes:
        codes = [c.strip() for c in reject_codes.split(",") if c.strip()]
    ann = reviewer_annotation_service.review_annotation(
        db,
        annotation_id=annotation_id,
        action=action,
        reject_codes=codes,
        note=note,
    )
    return {
        "annotation_id": ann.annotation_id,
        "review_status": ann.review_status,
        "reject_reasons": ann.reject_reasons,
        "message": "审核通过" if action == "approved" else "已驳回",
    }


@router.get("/review/annotation-tasks/{task_id}/summary", dependencies=[_reviewer])
def get_sampling_result(
    task_id: int,
    db: Session = Depends(get_db),
):
    """抽检结果摘要（通过率、驳回原因分布）。"""
    return reviewer_annotation_service.get_sampling_result(db, task_id=task_id)


@router.post("/review/annotation-tasks/{task_id}/finalize", dependencies=[_reviewer])
def finalize_review(
    task_id: int,
    action: str = Query(..., description="dismiss_only / expand / reject_all"),
    new_ratio: float | None = Query(None, description="expand 时的新抽检比例"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """结束审核。dismiss_only：仅驳回问题图，其余通过。expand：扩大抽检重新抽样。
    reject_all：全部驳回。"""
    task = reviewer_annotation_service.finalize_review(
        db,
        task_id=task_id,
        reviewer_id=current_user.user_id,
        action=action,
        new_ratio=new_ratio,
    )
    return {
        "task_id": task.task_id,
        "status": task.status,
        "message": f"审核结束（{action}）",
    }


# ──── 质量检查 + 绩效统计 ────


@router.get("/review/annotation-tasks/{task_id}/quality-check", dependencies=[_reviewer])
def run_quality_check(
    task_id: int,
    db: Session = Depends(get_db),
):
    """质量检查辅助。规则引擎 5 项自动检测（越界/面积/宽高比/重复框/深度值）。"""
    return reviewer_annotation_service.run_quality_check(db, task_id=task_id)


@router.get("/review/stats", dependencies=[_reviewer])
def get_reviewer_stats(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """审核员绩效统计（数据集审核 + 标注审核双维度）。"""
    return reviewer_annotation_service.get_reviewer_stats(
        db, reviewer_id=current_user.user_id
    )
