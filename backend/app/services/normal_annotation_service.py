"""标注服务 — 标注任务管理 + 标注多版本存储 + 提交审核

所有函数对应设计报告 3.3.1 节 normal_annotation_service。
Model 方法已在第一阶段实现，此层做权限校验 + 状态保护 + 进度统计修复。
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.annotation_task import AnnotationTask
from app.models.data_resource import DataResource
from app.models.label_schema import LabelSchema


# ──── 内部辅助 ────


def _find_task_or_404(db: Session, task_id: int) -> AnnotationTask:
    """查询标注任务，不存在则 404"""
    task = (
        db.query(AnnotationTask)
        .filter(AnnotationTask.task_id == task_id)
        .first()
    )
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"标注任务 task_id={task_id} 不存在",
        )
    return task


def _find_resource_or_404(db: Session, resource_id: int) -> DataResource:
    """查询数据资源，不存在则 404"""
    resource = (
        db.query(DataResource)
        .filter(DataResource.resource_id == resource_id)
        .first()
    )
    if resource is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"数据资源 resource_id={resource_id} 不存在",
        )
    return resource


def _matching_resources_query(db: Session, data_range: dict):
    """根据 data_range 构建资源查询"""
    query = db.query(DataResource)

    if modality := data_range.get("modality"):
        query = query.filter(DataResource.modality == modality)
    if scene := data_range.get("scene"):
        query = query.filter(DataResource.meta_info["scene"].astext == scene)
    if status_val := data_range.get("status"):
        query = query.filter(DataResource.status == status_val)
    if batch_id := data_range.get("batch_id"):
        query = query.filter(DataResource.meta_info["batch_id"].astext == batch_id)
    if owner_id := data_range.get("owner_id"):
        query = query.filter(DataResource.owner_id == owner_id)
    if resource_ids := data_range.get("resource_ids"):
        query = query.filter(DataResource.resource_id.in_(resource_ids))

    return query


def _count_matching_resources(db: Session, data_range: dict) -> int:
    """根据 data_range 筛选条件统计匹配的数据资源总数"""
    return _matching_resources_query(db, data_range or {}).count()


def list_matching_resources(db: Session, data_range: dict) -> list[DataResource]:
    """按 data_range 列出匹配资源（按 id 升序）"""
    return (
        _matching_resources_query(db, data_range or {})
        .order_by(DataResource.resource_id.asc())
        .all()
    )


# ──── 标注任务管理 ────


def create_annotation_task(
    db: Session,
    name: str,
    data_range: dict,
    schema_id: int,
    assignee_ids: list[int],
    created_by: int,
    reviewer_id: int | None = None,
    skip_review: bool = False,
    deadline: str | None = None,
) -> AnnotationTask:
    """创建标注任务。

    校验：
    - schema_id 对应的标签体系存在
    - data_range 至少匹配到 1 条数据

    API: POST /api/annotation/tasks
    """
    # 校验标签体系存在
    schema = (
        db.query(LabelSchema)
        .filter(LabelSchema.schema_id == schema_id)
        .first()
    )
    if schema is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"标签体系 schema_id={schema_id} 不存在",
        )

    # 校验 data_range 能匹配到数据
    match_count = _count_matching_resources(db, data_range)
    if match_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="data_range 筛选条件未匹配到任何数据资源，请调整筛选条件",
        )

    from datetime import datetime as dt

    parsed_deadline = None
    if deadline:
        try:
            parsed_deadline = dt.fromisoformat(deadline)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="deadline 格式错误，需为 ISO 8601 格式",
            ) from None

    return AnnotationTask.create(
        db,
        name=name,
        data_range=data_range,
        schema_id=schema_id,
        assignee_ids=assignee_ids,
        created_by=created_by,
        reviewer_id=reviewer_id,
        skip_review=skip_review,
        status="draft",
        deadline=parsed_deadline,
    )


def list_my_tasks(db: Session, user_id: int) -> list[AnnotationTask]:
    """查询我参与的标注任务（作为标注员或创建者）。

    API: GET /api/annotation/tasks
    """
    # 包含我是 assignee 或我是创建者的任务
    from sqlalchemy import or_

    tasks = (
        db.query(AnnotationTask)
        .filter(
            or_(
                AnnotationTask.assignee_ids.contains([user_id]),
                AnnotationTask.created_by == user_id,
            )
        )
        .order_by(AnnotationTask.created_at.desc())
        .all()
    )
    return tasks


# ──── 标注保存与查询 ────


def save_annotation(
    db: Session,
    task_id: int,
    resource_id: int,
    bboxes: list[dict],
    user_id: int,
) -> Annotation:
    """保存标注（追加写）。

    校验：
    - 任务状态允许编辑（draft / in_progress / rejected）
    - 用户是 assignee 之一
    - 标注框坐标合法性（0~1 范围）

    API: PUT /api/annotation/images/{id}/save
    """
    task = _find_task_or_404(db, task_id)
    _find_resource_or_404(db, resource_id)

    # 状态保护：submitted / approved / reviewing 状态下不可编辑
    if task.status in ("submitted", "reviewing", "completed"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"任务状态为 '{task.status}'，不允许编辑标注",
        )

    if task.status == "draft":
        # 首次标注，将任务状态改为 in_progress
        task.status = "in_progress"
        task.save(db)

    # 权限校验：必须是标注员
    if user_id not in (task.assignee_ids or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你不是该任务的标注员，无权保存标注",
        )

    # 获取最新标注版本
    latest = Annotation.get_latest(db, task_id, resource_id)

    # 如果已提交或被驳回，检查状态
    if latest and latest.review_status == "approved":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="该标注已审核通过，不可修改",
        )

    # 追加写
    annotation = Annotation.save_new_version(
        db,
        task_id=task_id,
        resource_id=resource_id,
        bboxes=bboxes,
        user_id=user_id,
    )

    # 如果是驳回后重新保存，将 review_status 重置为 pending
    if latest and latest.review_status == "rejected":
        annotation.review_status = "pending"
        annotation.save(db)

    return annotation


def get_latest_annotation(
    db: Session,
    task_id: int,
    resource_id: int,
) -> Annotation:
    """获取某图片在指定任务中的最新版本标注。

    API: GET 内部使用
    """
    _find_task_or_404(db, task_id)
    _find_resource_or_404(db, resource_id)

    annotation = Annotation.get_latest(db, task_id, resource_id)
    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"resource_id={resource_id} 在 task_id={task_id} 下尚无标注记录",
        )
    return annotation


def get_annotation_history(
    db: Session,
    task_id: int,
    resource_id: int,
) -> list[Annotation]:
    """按版本降序返回某图片在指定任务中的所有历史版本。

    API: GET /api/annotation/images/{id}/history
    """
    _find_task_or_404(db, task_id)
    _find_resource_or_404(db, resource_id)
    return Annotation.get_history(db, task_id, resource_id)


# ──── 提交审核 ────


def submit_annotation(
    db: Session,
    task_id: int,
    resource_id: int,
    user_id: int,
) -> Annotation:
    """提交单张标注进入审核队列。

    校验：
    - 存在至少一版标注记录
    - 用户是 assignee

    API: POST /api/annotation/images/{id}/submit
    """
    task = _find_task_or_404(db, task_id)
    _find_resource_or_404(db, resource_id)

    if user_id not in (task.assignee_ids or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="你不是该任务的标注员，无权提交标注",
        )

    annotation = Annotation.get_latest(db, task_id, resource_id)
    if annotation is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该资源尚无标注记录，请先保存标注再提交",
        )

    # 如果 skip_review，直接标记为 approved
    if task.skip_review:
        annotation.review_status = "approved"
        annotation.save(db)
        return annotation

    # 标记为 submitted
    annotation.review_status = "submitted"
    annotation.save(db)

    # 同时更新任务状态
    if task.status in ("draft", "in_progress"):
        task.status = "submitted"
        task.save(db)

    return annotation


# ──── 下一张 / 回滚 ────


def get_next_image(db: Session, task_id: int, user_id: int) -> dict:
    """返回任务中下一张待标注图片（优先未提交，否则返回第一张）。

    API: GET /api/annotation/tasks/{id}/next
    """
    task = _find_task_or_404(db, task_id)
    if user_id not in (task.assignee_ids or []) and task.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权访问该标注任务",
        )

    resources = list_matching_resources(db, task.data_range or {})
    if not resources:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务 data_range 未匹配到任何图片",
        )

    submitted_ids = {
        rid
        for (rid,) in db.query(Annotation.resource_id)
        .filter(
            Annotation.task_id == task_id,
            Annotation.review_status.in_(["submitted", "approved", "rejected"]),
        )
        .distinct()
        .all()
    }

    chosen = None
    for r in resources:
        if r.resource_id not in submitted_ids:
            chosen = r
            break
    if chosen is None:
        chosen = resources[0]

    latest = Annotation.get_latest(db, task_id, chosen.resource_id)
    return {
        "task_id": task_id,
        "resource_id": chosen.resource_id,
        "name": chosen.name,
        "modality": chosen.modality,
        "meta_info": chosen.meta_info or {},
        "image_url": f"/api/images/{chosen.resource_id}",
        "thumbnail_url": f"/api/images/{chosen.resource_id}/thumbnail",
        "annotation": (
            {
                "annotation_id": latest.annotation_id,
                "version": latest.version,
                "bboxes": latest.bboxes,
                "review_status": latest.review_status,
            }
            if latest
            else None
        ),
        "remaining": max(0, len(resources) - len(submitted_ids)),
        "total": len(resources),
    }


def rollback_annotation(
    db: Session,
    task_id: int,
    resource_id: int,
    version: int,
    user_id: int,
) -> Annotation:
    """将指定历史版本的 bboxes 另存为新版本（回滚）。

    API: POST /api/annotation/images/{id}/rollback
    """
    task = _find_task_or_404(db, task_id)
    if user_id not in (task.assignee_ids or []) and task.created_by != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="无权回滚该标注",
        )
    history = Annotation.get_history(db, task_id, resource_id)
    target = next((a for a in history if a.version == version), None)
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"找不到版本 version={version}",
        )
    bboxes = target.bboxes if isinstance(target.bboxes, list) else []
    return save_annotation(
        db,
        task_id=task_id,
        resource_id=resource_id,
        bboxes=bboxes,
        user_id=user_id,
    )


# ──── 进度统计 ────


def get_annotation_progress(db: Session, task_id: int) -> dict:
    """标注任务进度统计。

    修复了 Model 层 get_progress 的已知 bug：
    total = data_range 筛选条件匹配的数据资源总数（原为 len(assignee_ids)）

    API: GET /api/annotation/tasks/{id}/progress
    """
    task = _find_task_or_404(db, task_id)

    # total = data_range 匹配的资源数
    total = _count_matching_resources(db, task.data_range or {})

    # 各状态的唯一资源计数
    annotated = (
        db.query(Annotation.resource_id)
        .filter(Annotation.task_id == task_id)
        .distinct()
        .count()
    )

    approved = (
        db.query(Annotation.resource_id)
        .filter(
            Annotation.task_id == task_id,
            Annotation.review_status == "approved",
        )
        .distinct()
        .count()
    )

    rejected = (
        db.query(Annotation.resource_id)
        .filter(
            Annotation.task_id == task_id,
            Annotation.review_status == "rejected",
        )
        .distinct()
        .count()
    )

    return {
        "total": total,
        "annotated": annotated,
        "reviewed": approved + rejected,
        "approved": approved,
        "rejected": rejected,
    }
