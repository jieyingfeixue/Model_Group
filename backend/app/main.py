"""FastAPI 应用入口 — 挂载路由、CORS、中间件"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.admin import router as admin_router
from app.api.v1.admin_labels import router as admin_labels_router
from app.api.v1.annotations import router as annotation_router
from app.api.v1.auth import router as auth_router
from app.api.v1.data import router as data_router
from app.api.v1.datasets import router as datasets_router
from app.api.v1.eval import router as eval_router
from app.api.v1.infer import router as infer_router
from app.api.v1.models import router as models_router
from app.api.v1.review import router as review_router
from app.api.v1.train import router as train_router
from app.core.config import settings

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ──── CORS 中间件 ────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──── 路由注册 ────
app.include_router(auth_router, prefix="/api")
app.include_router(data_router, prefix="/api")
# Phase1: 数据集管理 / 标注 / 审核
app.include_router(admin_labels_router, prefix="/api")
app.include_router(annotation_router, prefix="/api")
app.include_router(datasets_router, prefix="/api")
app.include_router(review_router, prefix="/api")
# Phase2/3: 模型管理 / 训练 / 推理 / 评测
app.include_router(models_router, prefix="/api")
app.include_router(train_router, prefix="/api")
app.include_router(infer_router, prefix="/api")
app.include_router(eval_router, prefix="/api")
app.include_router(admin_router, prefix="/api")


@app.get("/api/health", tags=["System"])
def health_check():
    """健康检查端点"""
    return {"status": "ok", "version": settings.APP_VERSION}
