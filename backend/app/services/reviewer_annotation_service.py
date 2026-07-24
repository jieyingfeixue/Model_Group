"""标注审核 Service — 审核员查看 / 裁决标注结果"""

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.annotation_task import AnnotationTask


def list_pending_annotation_tasks(
    db: Session,
    reviewer_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """查询待审核标注任务列表。

    筛选 review_status = 'pending' 的所有标注记录，按任务聚合。
    """
    # 找到有 pending 标注的 task_id
    pending_task_ids = (
        db.query(Annotation.task_id)
        .filter(Annotation.review_status == "pending")
        .distinct()
        .all()
    )
    task_id_list = [t[0] for t in pending_task_ids]

    if not task_id_list:
        return [], 0

    query = db.query(AnnotationTask).filter(AnnotationTask.task_id.in_(task_id_list))
    total = query.count()
    tasks = (
        query.order_by(AnnotationTask.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for t in tasks:
        # 统计待审核数量
        pending_count = (
            db.query(Annotation)
            .filter(Annotation.task_id == t.task_id, Annotation.review_status == "pending")
            .count()
        )
        items.append({
            "task_id": t.task_id,
            "name": t.name,
            "status": t.status,
            "schema_id": t.schema_id,
            "pending_count": pending_count,
            "created_by": t.created_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return items, total


def submit_annotation_verdict(
    db: Session,
    annotation_id: int,
    verdict: str,
    reject_reasons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """审核员提交标注审核结果。

    规则：
      - verdict 为 approved 或 rejected
      - rejected 时需提供 reject_reasons
    """
    if verdict not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="verdict 必须为 approved 或 rejected",
        )

    if verdict == "rejected" and (reject_reasons is None or len(reject_reasons) == 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="驳回时必须提供 reject_reasons",
        )

    annotation = Annotation.set_review_result(
        db, annotation_id, verdict, reject_reasons
    )
    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="标注记录不存在"
        )

    return {
        "annotation_id": annotation.annotation_id,
        "review_status": annotation.review_status,
        "reject_reasons": annotation.reject_reasons,
        "message": "审核完成",
    }
