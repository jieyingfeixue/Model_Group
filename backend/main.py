from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.routers import data, datasets, images, resources

app = FastAPI(
    title="Model Group Image Compatibility Demo",
    description="图片访问兼容层 Demo：统一 /api/data 与 /api/images 接口，屏蔽底层存储差异。",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router, prefix=settings.api_prefix)
app.include_router(datasets.router, prefix=settings.api_prefix)
app.include_router(resources.router, prefix=settings.api_prefix)
app.include_router(images.router, prefix=settings.api_prefix)

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.is_dir():
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")


@app.get("/")
def index():
    index_file = frontend_dir / "index.html"
    if index_file.is_file():
        return FileResponse(index_file)
    return {"message": "Image compatibility demo is running.", "docs": "/docs"}


@app.get("/health")
def health():
    return {"status": "ok", "storage_mode": settings.image_storage_mode}
