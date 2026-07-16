"""Celery 应用实例 — Broker / Result Backend 复用 REDIS_URL"""

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "detection_platform",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.train_tasks",
        "app.tasks.infer_tasks",
        "app.tasks.eval_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
)

# 显式导入任务模块，确保 tasks.*.run 注册到 Celery
celery_app.autodiscover_tasks(["app.tasks"], force=True)
import app.tasks.train_tasks  # noqa: E402,F401
import app.tasks.infer_tasks  # noqa: E402,F401
import app.tasks.eval_tasks  # noqa: E402,F401
