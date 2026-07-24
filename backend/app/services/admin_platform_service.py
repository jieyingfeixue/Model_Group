"""平台管理 Service — 用户管理 / 统计 / 推理审批 / 天梯治理"""

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.infer_task import InferTask
from app.models.eval_result import EvalResult
from app.models.model_registry import Model
from app.core.security import hash_password


def list_users(
    db: Session,
    role: str | None = None,
    is_active: bool | None = None,
    keyword: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """管理员查询用户列表（支持筛选）"""
    query = db.query(User)

    if role:
        query = query.filter(User.role == role)
    if is_active is not None:
        query = query.filter(User.is_active == is_active)
    if keyword:
        query = query.filter(
            User.username.ilike(f"%{keyword}%") | User.email.ilike(f"%{keyword}%")
        )

    total = query.count()
    users = (
        query.order_by(User.user_id)
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for u in users:
        items.append({
            "user_id": u.user_id,
            "username": u.username,
            "email": u.email,
            "role": u.role,
            "is_active": u.is_active,
            "created_at": u.created_at,
            "updated_at": u.updated_at,
        })

    return items, total


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    role: str = "normal",
) -> dict[str, Any]:
    """管理员创建新用户"""
    # 检查用户名重复
    if User.get_by_username(db, username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="用户名已存在",
        )

    # 检查邮箱重复
    if User.get_by_email(db, email):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="邮箱已被注册",
        )

    user = User.create(
        db,
        username=username,
        email=email,
        password_hash=hash_password(password),
        role=role,
    )
    return {
        "user_id": user.user_id,
        "username": user.username,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "created_at": user.created_at,
        "updated_at": user.updated_at,
    }


def set_user_role(
    db: Session, user_id: int, new_role: str
) -> dict[str, Any]:
    """管理员修改用户角色"""
    if new_role not in ("admin", "reviewer", "normal"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="角色必须为 admin / reviewer / normal",
        )

    user = User.set_role(db, user_id, new_role)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在"
        )

    return {
        "user_id": user.user_id,
        "username": user.username,
        "role": user.role,
        "message": f"角色已更新为 {new_role}",
    }


def set_user_status(
    db: Session, user_id: int, is_active: bool
) -> dict[str, Any]:
    """管理员冻结/解冻用户"""
    user = db.query(User).filter(User.user_id == user_id).first()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在"
        )

    user.is_active = is_active
    user.save(db)

    status_text = "激活" if is_active else "冻结"
    return {
        "user_id": user.user_id,
        "username": user.username,
        "is_active": user.is_active,
        "message": f"用户已{status_text}",
    }


# ──── 推理审批 ────

def list_pending_infer_tasks(
    db: Session,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """管理员查看待审批推理任务列表"""
    query = db.query(InferTask).filter(
        InferTask.status.in_(["queued", "pending_approval"])
    )

    total = query.count()
    tasks = (
        query.order_by(InferTask.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for t in tasks:
        items.append({
            "task_id": t.task_id,
            "model_id": t.model_id,
            "dataset_id": t.dataset_id,
            "image_id": t.image_id,
            "status": t.status,
            "created_by": t.created_by,
            "created_at": t.created_at.isoformat() if t.created_at else None,
        })

    return items, total


# ──── 天梯治理 ────

def list_leaderboard_governance(
    db: Session,
    dataset_id: int | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    """管理员天梯治理列表：查看所有评测结果（含非公开）"""
    query = db.query(EvalResult)

    if dataset_id is not None:
        query = query.filter(EvalResult.dataset_id == dataset_id)

    total = query.count()
    results = (
        query.order_by(EvalResult.created_at.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = []
    for r in results:
        model = db.query(Model).filter(Model.model_id == r.model_id).first()
        metrics = r.overall_metrics or {}
        items.append({
            "result_id": r.result_id,
            "model_id": r.model_id,
            "model_name": model.name if model else None,
            "dataset_id": r.dataset_id,
            "mAP50": metrics.get("mAP50"),
            "mAP50_95": metrics.get("mAP50_95"),
            "is_public": r.is_public,
            "is_invalidated": not r.is_public,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })

    return items, total


# ──── 作弊下架 ────

def invalidate_eval_result(
    db: Session, result_id: int, reason: str
) -> dict[str, Any]:
    """管理员将评测结果标记为无效（作弊下架），从排行榜移除"""
    result = db.query(EvalResult).filter(EvalResult.result_id == result_id).first()
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="评测结果不存在"
        )

    # 标记为非公开（从排行榜下架）
    result.is_public = False
    # 在 overall_metrics 中记录下架原因
    metrics = dict(result.overall_metrics) if result.overall_metrics else {}
    metrics["_invalidated"] = True
    metrics["_invalidated_reason"] = reason
    metrics["_invalidated_at"] = datetime.now().isoformat()
    result.overall_metrics = metrics
    result.save(db)

    return {
        "result_id": result.result_id,
        "model_id": result.model_id,
        "message": f"评测结果已下架，原因: {reason}",
    }
