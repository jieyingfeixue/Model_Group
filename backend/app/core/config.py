"""应用配置 — 通过 pydantic-settings 从 .env 读取环境变量"""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ──── PostgreSQL ────
    DATABASE_URL: str = "postgresql://postgres:your_password@localhost:5432/detection_platform"

    # ──── JWT ────
    SECRET_KEY: str = "change-me-to-a-random-secret-string"
    ACCESS_TOKEN_EXPIRE_HOURS: int = 24
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # ──── Redis ────
    REDIS_URL: str = "redis://localhost:6379/0"

    # ──── MinIO ────
    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin"
    MINIO_BUCKET: str = "detection-platform"
    MINIO_SECURE: bool = False

    # ──── 训练执行（Zhang · Phase2）────
    # docker：Celery 拉起 detection-train:demo 容器；local：同机 subprocess 跑 demo_trainer
    TRAIN_EXECUTOR: str = "docker"
    TRAIN_IMAGE: str = "detection-train:demo"
    TRAIN_JOBS_DIR: str = "data/train_jobs"
    # Docker Desktop 绑定挂载须填宿主机绝对路径；空则 docker 失败时回退 local
    TRAIN_HOST_JOBS_DIR: str = ""
    TRAIN_MAX_PARALLEL: int = 1
    TRAIN_TIMEOUT_SEC: int = 3600
    TRAIN_SLOT_KEY: str = "train:global_slot"

    # ──── App ────
    APP_TITLE: str = "目标检测数据与算法评测平台"
    APP_VERSION: str = "3.0.0-rc"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
