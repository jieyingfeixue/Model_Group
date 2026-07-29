"""FastAPI application for Auto-labeling-LH web server."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on sys.path BEFORE any src imports
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import HOST, PORT, CORS_ORIGINS, DATASET_ROOT
from .routes.datasets import router as datasets_router
from .routes.frames import router as frames_router
from .routes.sessions import router as sessions_router
from .routes.pipeline import router as pipeline_router
from .routes.annotation import router as annotation_router
from .routes.export import router as export_router
from .routes.browse import router as browse_router

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("web_server")

# ── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Auto-Labeling Web API",
    description="Multi-sensor semi-automatic 3D annotation tool — Web API",
    version="0.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(datasets_router)
app.include_router(frames_router)
app.include_router(sessions_router)
app.include_router(pipeline_router)
app.include_router(annotation_router)
app.include_router(export_router)
app.include_router(browse_router)


# ── Root / health ───────────────────────────────────────────────────────────

@app.get("/api")
async def api_root():
    """API landing page."""
    return {
        "name": "Auto-Labeling Web API",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "datasets":  "GET  /api/datasets?dataset_root=...&profile=lh",
            "sequences": "GET  /api/sequences?dataset_root=...&profile=lh",
            "frames":    "GET  /api/frames?seq_id=...&dataset_root=...&profile=lh",
            "metadata":  "GET  /api/frames/metadata?seq_id=...&frame_id=...&dataset_root=...",
            "image":     "GET  /api/frames/image?seq_id=...&frame_id=...&camera_key=...&dataset_root=...",
            "thumb":     "GET  /api/frames/thumb?seq_id=...&frame_id=...&dataset_root=...",
            "pointcloud":"GET  /api/frames/pointcloud?seq_id=...&frame_id=...&lidar_key=...&dataset_root=...",
            "radar":     "GET  /api/frames/radar?seq_id=...&frame_id=...&radar_key=...&dataset_root=...",
            "calibration":"GET /api/frames/calibration?seq_id=...&frame_id=...&dataset_root=...",
            "detect":    "POST /api/detect",
            "box_from_2d":"POST /api/box-from-2d",
            "sessions":  "GET/POST /api/sessions/",
            "pipeline":  "POST /api/pipeline/run",
            "export":    "POST /api/export",
        },
    }


@app.get("/test", response_class=HTMLResponse)
async def test_page():
    """Minimal test page."""
    test_path = _STATIC_DIR / "test.html"
    if test_path.exists():
        return HTMLResponse(test_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Not found</h1>")

@app.get("/simple", response_class=HTMLResponse)
async def simple_page():
    """Minimal browser page for debugging."""
    sp = _STATIC_DIR / "simple.html"
    if not sp.exists():
        return HTMLResponse("<h1>Not found</h1>", status_code=404)
    html = sp.read_text(encoding="utf-8")
    from .routes.browse import _get_cached_tree
    import json as _json
    try:
        import asyncio
        tree = await asyncio.to_thread(_get_cached_tree, str(DATASET_ROOT))
        html = html.replace("__TREE_JSON__", _json.dumps(tree, ensure_ascii=False))
    except Exception:
        html = html.replace("__TREE_JSON__", "[]")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}


# ── Static file serving ──────────────────────────────────────────────────

_UI_DIR = _project_root / "web_ui" / "dist"
_STATIC_DIR = Path(__file__).resolve().parent / "static"

# Root → home
@app.get("/", response_class=HTMLResponse)
async def root():
    hp = _STATIC_DIR / "home.html"
    if hp.exists(): return HTMLResponse(hp.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Not found</h1>", status_code=404)

# Home page
@app.get("/home", response_class=HTMLResponse)
async def home_page():
    hp = _STATIC_DIR / "home.html"
    if hp.exists(): return HTMLResponse(hp.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Not found</h1>", status_code=404)

# Annotation page
@app.get("/annotate", response_class=HTMLResponse)
async def annotate_page():
    ap = _STATIC_DIR / "annotate.html"
    if not ap.exists(): return HTMLResponse("<h1>Not found</h1>", status_code=404)
    import json as _json
    html = ap.read_text(encoding="utf-8")
    html = html.replace(
        "var R='/data1/LHO/nas/LH_Dataset/LH_data_all_sensor';",
        f"var R={_json.dumps(str(DATASET_ROOT))};",
    )
    # Return the page immediately.  The frontend already knows how to fetch
    # the tree asynchronously from /api/browse/tree.
    html = html.replace("/*TREE_DATA_PLACEHOLDER*/", "var TREE_DATA=null;")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

# Data browser (standalone HTML, no build needed)
@app.get("/browser", response_class=HTMLResponse)
async def image_browser():
    """Dataset image browser page — tree data inlined for instant load."""
    index_path = _STATIC_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Browser page not found</h1>", status_code=404)

    html = index_path.read_text(encoding="utf-8")

    import json
    html = html.replace(
        "var R='/data1/LHO/nas/LH_Dataset/LH_data_all_sensor';",
        f"var R={json.dumps(str(DATASET_ROOT))};",
    )
    html = html.replace(
        "/*TREE_DATA_PLACEHOLDER*/",
        "var TREE_DATA=null;var TREE_READY=false;",
    )

    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )

# React SPA
if _UI_DIR.exists():
    app.mount("/app/assets", StaticFiles(directory=_UI_DIR / "assets"), name="app_assets")

@app.get("/app", response_class=HTMLResponse)
@app.get("/app/{rest:path}")
async def serve_spa(rest: str = ""):
    """Serve the React SPA."""
    if _UI_DIR.exists():
        fpath = _UI_DIR / rest if rest else _UI_DIR / "index.html"
        if fpath.exists() and fpath.is_file():
            suffix = fpath.suffix.lower()
            media_map = {'.js': 'application/javascript', '.css': 'text/css',
                         '.svg': 'image/svg+xml', '.ico': 'image/x-icon'}
            return FileResponse(fpath, media_type=media_map.get(suffix))
        index_path = _UI_DIR / "index.html"
        if index_path.exists():
            return FileResponse(index_path)
    return HTMLResponse("<h1>Frontend not built</h1>", status_code=404)


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    """Entry point: uvicorn web_server.app:app --host 0.0.0.0 --port 8080"""
    import uvicorn
    logger.info("Starting Auto-Labeling Web API on %s:%s", HOST, PORT)
    uvicorn.run("web_server.app:app", host=HOST, port=PORT, reload=False)


if __name__ == "__main__":
    main()
