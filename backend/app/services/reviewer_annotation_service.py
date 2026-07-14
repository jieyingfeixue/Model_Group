"""标注审核 Service — 待审核任务池 / 认领 / 抽检 / 逐张审核 / 结束审核

设计报告 3.3.2 节 reviewer_annotation_service。
抽样结果暂存于 annotation_task.review_info JSONB 字段。
"""

import random

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.annotation import Annotation
from app.models.annotation_task import AnnotationTask
from app.models.data_resource import DataResource
from app.models.dataset import Dataset
from app.utils.quality_check import (
    check_bbox_bounds,
    check_bbox_area,
    check_bbox_aspect_ratio,
    check_duplicate_bboxes,
    check_depth_range,
)

# T01-T10 驳回模板（设计报告 3.3.2 节）
_REJECT_CODES = {"T01", "T02", "T03", "T04", "T05", "T06", "T07", "T08", "T09", "T10"}

_REJECT_LABELS = {
    "T01": "检测框位置偏移，未完全包围目标",
    "T02": "检测框尺寸不准确（过大/过小）",
    "T03": "目标类别标注错误",
    "T04": "漏标：图片中存在未标注的障碍物",
    "T05": "多标：将非障碍物区域误标为目标",
    "T06": "深度值明显偏差（与实际距离不符）",
    "T07": "遮挡程度标注错误",
    "T08": "截断程度标注错误",
    "T09": "标注框坐标越界（超出图片范围）",
    "T10": "图片质量不可标注（过曝/模糊/全黑）",
}


# ──── 内部辅助 ────


def _find_task_or_404(db: Session, task_id: int) -> AnnotationTask:
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


def _find_annotation_or_404(db: Session, annotation_id: int) -> Annotation:
    ann = (
        db.query(Annotation)
        .filter(Annotation.annotation_id == annotation_id)
        .first()
    )
    if ann is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"标注记录 annotation_id={annotation_id} 不存在",
        )
    return ann


def _get_sample_ids(task: AnnotationTask) -> list[int]:
    """从 review_notes 中读取抽样 ID 列表"""
    notes = task.review_info or {}
    return notes.get("sample_ids", [])


# ──── 业务函数 ────


def get_pending_annotation_tasks(
    db: Session,
    page: int = 1,
    size: int = 20,
) -> tuple[list[AnnotationTask], int]:
    """查看待审核标注任务。返回所有 status='submitted' 的任务。

    API: GET /api/review/annotation-tasks
    """
    query = db.query(AnnotationTask).filter(AnnotationTask.status == "submitted")
    total = query.count()
    tasks = (
        query.order_by(AnnotationTask.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return tasks, total


def claim_annotation_review(
    db: Session,
    task_id: int,
    reviewer_id: int,
) -> AnnotationTask:
    """认领标注审核。锁定任务，同一时间只能由一个审核员操作。

    校验：reviewer_id 不在 assignee_ids 中（不可审自己标的图）。

    API: POST /api/review/annotation-tasks/{id}/claim
    """
    task = _find_task_or_404(db, task_id)

    if task.status != "submitted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"任务状态为 '{task.status}'，只有 'submitted' 状态可被认领",
        )

    if reviewer_id in (task.assignee_ids or []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="不能审核自己参与标注的任务",
        )

    task.status = "reviewing"
    task.reviewer_id = reviewer_id
    task.save(db)
    return task


def setup_sampling(
    db: Session,
    task_id: int,
    reviewer_id: int,
    ratio: float = 0.2,
    mode: str = "random",
    manual_ids: list[int] | None = None,
) -> dict:
    """配置抽检。

    ratio: 10%-100%（默认 20%）
    mode: 'random' — 按比例随机抽样；'manual' — 前端传入 annotation_id 列表
    抽样结果写入 task.review_info.sample_ids

    API: POST /api/review/annotation-tasks/{id}/sample
    """
    task = _find_task_or_404(db, task_id)

    if task.reviewer_id != reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有当前认领人可配置抽检",
        )

    if not (0.1 <= ratio <= 1.0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="抽检比例必须在 10%~100% 之间",
        )

    # 获取任务下所有标注（按最新版本去重）
    annotations = Annotation.get_by_task(db, task_id)
    total = len(annotations)

    if total == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该任务尚无标注记录",
        )

    if mode == "manual" and manual_ids:
        # 手动模式：校验传入的 ID 是否都属于该任务
        valid_ids = {a.annotation_id for a in annotations}
        sample_ids = [aid for aid in manual_ids if aid in valid_ids]
        if not sample_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="传入的 annotation_id 都不属于该任务",
            )
    else:
        # 随机模式
        sample_count = max(1, int(total * ratio))
        all_ids = [a.annotation_id for a in annotations]
        sample_ids = random.sample(all_ids, sample_count)

    # 暂存到 review_notes
    notes = dict(task.review_info) if task.review_info else {}
    notes["sample_ids"] = sample_ids
    notes["sample_ratio"] = ratio
    notes["sample_mode"] = mode
    task.review_info = notes
    task.save(db)

    return {
        "total": total,
        "sampled_count": len(sample_ids),
        "sample_ids": sample_ids,
        "ratio": ratio,
        "mode": mode,
    }


def review_annotation(
    db: Session,
    annotation_id: int,
    action: str,
    reject_codes: list[str] | None = None,
    note: str | None = None,
) -> Annotation:
    """审核单张标注。

    action: 'approved' / 'rejected'
    rejected 时至少选择一项 T01-T10 驳回原因，可选附带说明文本。

    API: POST /api/review/annotations/{id}/verdict
    """
    ann = _find_annotation_or_404(db, annotation_id)

    if action not in ("approved", "rejected"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"action 必须为 'approved' 或 'rejected'",
        )

    if action == "rejected":
        if not reject_codes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="驳回时必须至少选择一项 T01-T10 驳回原因",
            )
        invalid = [c for c in reject_codes if c not in _REJECT_CODES]
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的驳回原因代码: {invalid}，有效值为 T01-T10",
            )
        ann.review_status = "rejected"
        ann.reject_reasons = [
            {"code": c, "desc": _REJECT_LABELS.get(c, ""), "note": note or ""}
            for c in reject_codes
        ]
    else:
        ann.review_status = "approved"
        ann.reject_reasons = None

    ann.save(db)
    return ann


def get_sampling_result(
    db: Session,
    task_id: int,
) -> dict:
    """查看抽检结果摘要。

    返回：
    {total, passed, pass_rate, rejected, reject_rate,
     rejection_distribution: {T01: 5, T02: 3, ...}}

    API: GET /api/review/annotation-tasks/{id}/summary
    """
    task = _find_task_or_404(db, task_id)
    sample_ids = _get_sample_ids(task)

    if not sample_ids:
        return {
            "total": 0,
            "sampled": 0,
            "passed": 0,
            "pass_rate": 0.0,
            "rejected": 0,
            "reject_rate": 0.0,
            "rejection_distribution": {},
            "pending": 0,
        }

    # 查询抽样标注的审核结果
    sampled_anns = (
        db.query(Annotation)
        .filter(Annotation.annotation_id.in_(sample_ids))
        .all()
    )

    total = len(sample_ids)
    passed = sum(1 for a in sampled_anns if a.review_status == "approved")
    rejected = sum(1 for a in sampled_anns if a.review_status == "rejected")
    pending = total - passed - rejected

    # 驳回原因分布
    distribution: dict[str, int] = {}
    for a in sampled_anns:
        if a.review_status == "rejected" and a.reject_reasons:
            for reason in a.reject_reasons:
                code = reason.get("code", "")
                if code:
                    distribution[code] = distribution.get(code, 0) + 1

    return {
        "total": total,
        "sampled": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total > 0 else 0.0,
        "rejected": rejected,
        "reject_rate": round(rejected / total, 4) if total > 0 else 0.0,
        "rejection_distribution": distribution,
        "pending": pending,
    }


def finalize_review(
    db: Session,
    task_id: int,
    reviewer_id: int,
    action: str,
    new_ratio: float | None = None,
) -> AnnotationTask:
    """结束审核。

    action:
    - 'dismiss_only': 仅驳回问题图，其余（抽检通过 + 未抽中）全部 approved → task completed
    - 'expand': 扩大审核范围 → 按 new_ratio 重新抽样
    - 'reject_all': 全部驳回 → 所有标注 review_status='rejected' → task completed

    API: POST /api/review/annotation-tasks/{id}/finalize
    """
    task = _find_task_or_404(db, task_id)

    if task.reviewer_id != reviewer_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="只有当前认领人可结束审核",
        )

    if action == "expand":
        if new_ratio is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="expand 模式需要传入 new_ratio 参数",
            )
        # 重新抽样
        return setup_sampling(
            db, task_id, reviewer_id, ratio=new_ratio, mode="random"
        )

    if action == "dismiss_only":
        # 抽检通过的 + 所有未抽中的 → approved
        sample_ids = _get_sample_ids(task)
        sample_set = set(sample_ids)

        all_annotations = Annotation.get_by_task(db, task_id)
        for ann in all_annotations:
            if ann.annotation_id in sample_set:
                # 抽样范围内的：已审核的保持，未审核的（pending）补批为 approved
                if ann.review_status == "pending":
                    ann.review_status = "approved"
                    ann.save(db)
            else:
                # 未抽中的：自动 approve
                ann.review_status = "approved"
                ann.save(db)

    elif action == "reject_all":
        all_annotations = Annotation.get_by_task(db, task_id)
        for ann in all_annotations:
            ann.review_status = "rejected"
            if not ann.reject_reasons:
                ann.reject_reasons = [
                    {"code": "T99", "desc": "审核员全部驳回", "note": ""}
                ]
            ann.save(db)

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"action 必须为 'dismiss_only' / 'expand' / 'reject_all'",
        )

    # dismiss_only 和 reject_all 结束审核
    if action in ("dismiss_only", "reject_all"):
        task.status = "completed"
        task.save(db)

    return task


# ═══════════════════════════════════════════════════════════════════════════════
# 质量检查辅助 + 审核员绩效统计
# ═══════════════════════════════════════════════════════════════════════════════


def run_quality_check(db: Session, task_id: int) -> dict:
    """运行质量检查。汇总三类检测结果：

    1. 漏标检测 — 基线模型预推理 IoU < 0.1 区域 → 黄色虚线框提示
       → Phase 3 实现（推理结果缓存 Redis TTL 24h）
    2. 误标检测 — 调用规则引擎 5 项自动扫描
    3. 一致性检查 — 多人标注同一图片时框级 IoU 匹配率 < 80%
       → Phase 3 实现（需多人标注数据）

    API: GET /api/review/annotation-tasks/{id}/quality-check
    """
    _find_task_or_404(db, task_id)

    annotations = Annotation.get_by_task(db, task_id)
    if not annotations:
        return {
            "task_id": task_id,
            "missing_labels": [],
            "missing_labels_note": "待第三阶段集成基线模型预推理（推理结果缓存 Redis TTL 24h）",
            "error_labels": [],
            "error_labels_summary": {"total_annotations": 0, "total_bboxes": 0, "issues_found": 0},
            "inconsistency": [],
        }

    all_issues: list[dict] = []
    total_bboxes = 0

    for ann in annotations:
        bboxes = ann.bboxes or []
        if not bboxes:
            continue

        resource = (
            db.query(DataResource)
            .filter(DataResource.resource_id == ann.resource_id)
            .first()
        )
        meta = resource.meta_info if resource else {}
        img_w = meta.get("width", 1920)
        img_h = meta.get("height", 1080)

        total_bboxes += len(bboxes)

        for issue in check_bbox_bounds(bboxes, img_w, img_h):
            issue["annotation_id"] = ann.annotation_id
            issue["resource_id"] = ann.resource_id
            all_issues.append(issue)

        for issue in check_bbox_area(bboxes, img_w, img_h):
            issue["annotation_id"] = ann.annotation_id
            issue["resource_id"] = ann.resource_id
            all_issues.append(issue)

        for issue in check_bbox_aspect_ratio(bboxes):
            issue["annotation_id"] = ann.annotation_id
            issue["resource_id"] = ann.resource_id
            all_issues.append(issue)

        for issue in check_duplicate_bboxes(bboxes):
            issue["annotation_id"] = ann.annotation_id
            issue["resource_id"] = ann.resource_id
            all_issues.append(issue)

        for issue in check_depth_range(bboxes):
            issue["annotation_id"] = ann.annotation_id
            issue["resource_id"] = ann.resource_id
            all_issues.append(issue)

    return {
        "task_id": task_id,
        "missing_labels": [],
        "missing_labels_note": "待第三阶段集成基线模型预推理（推理结果缓存 Redis TTL 24h）",
        "inconsistency": [],
        "error_labels": all_issues,
        "error_labels_summary": {
            "total_annotations": len(annotations),
            "total_bboxes": total_bboxes,
            "issues_found": len(all_issues),
        },
    }


def get_reviewer_stats(db: Session, reviewer_id: int) -> dict:
    """审核员绩效统计。两个独立维度：

    1. 数据集审核统计：审核总数 / 通过数 / 驳回数 / 通过率
    2. 标注审核统计：审核图片总数 / 通过率 / 驳回原因分布

    API: GET /api/review/stats
    """
    # 数据集审核统计
    ds_reviewed = (
        db.query(Dataset)
        .filter(
            Dataset.reviewer_id == reviewer_id,
            Dataset.review_status.in_(["approved", "rejected"]),
        )
        .all()
    )
    ds_total = len(ds_reviewed)
    ds_approved = sum(1 for d in ds_reviewed if d.review_status == "approved")
    ds_rejected = ds_total - ds_approved

    # 标注审核统计
    reviewed_tasks = (
        db.query(AnnotationTask)
        .filter(AnnotationTask.reviewer_id == reviewer_id)
        .all()
    )
    task_ids = [t.task_id for t in reviewed_tasks]

    anno_total = 0
    anno_approved = 0
    anno_rejected = 0
    anno_distribution: dict[str, int] = {}

    if task_ids:
        reviewed_anns = (
            db.query(Annotation)
            .filter(
                Annotation.task_id.in_(task_ids),
                Annotation.review_status.in_(["approved", "rejected"]),
            )
            .all()
        )
        anno_total = len(reviewed_anns)
        for a in reviewed_anns:
            if a.review_status == "approved":
                anno_approved += 1
            else:
                anno_rejected += 1
                if a.reject_reasons:
                    for r in a.reject_reasons:
                        code = r.get("code", "")
                        if code:
                            anno_distribution[code] = anno_distribution.get(code, 0) + 1

    return {
        "dataset_review": {
            "total": ds_total,
            "approved": ds_approved,
            "rejected": ds_rejected,
            "approval_rate": round(ds_approved / ds_total, 4) if ds_total > 0 else 0.0,
        },
        "annotation_review": {
            "total": anno_total,
            "approved": anno_approved,
            "rejected": anno_rejected,
            "approval_rate": round(anno_approved / anno_total, 4) if anno_total > 0 else 0.0,
            "rejection_distribution": anno_distribution,
        },
    }
