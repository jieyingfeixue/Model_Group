"""FastAPI 应用入口 — 挂载路由、CORS、中间件"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.auth import router as auth_router
from app.api.v1.data import router as data_router
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


@app.get("/api/health", tags=["System"])
def health_check():
    """健康检查端点"""
    return {"status": "ok", "version": settings.APP_VERSION}
