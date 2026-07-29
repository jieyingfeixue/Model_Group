"""Auto-pipeline endpoint + WebSocket progress streaming."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

from ..dependencies import get_loader, get_or_create_session
from ..websocket_manager import ws_manager
from ..config import PIPELINE_TIMEOUT
from ..config import DATASET_ROOT

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])

# In-memory task registry: task_id → status / result
_task_results: dict[str, dict[str, Any]] = {}


class PipelineRunRequest(BaseModel):
    seq_id: str
    frame_id: str
    session_id: str | None = None
    dataset_root: str = str(DATASET_ROOT)
    profile: str = "lh"
    stages: list[str] | None = None  # None = all stages


@router.post("/run")
async def pipeline_run(req: PipelineRunRequest):
    """Start the auto-annotation pipeline for a frame. Returns a task_id for WebSocket progress."""
    from src.core.config import load_config
    from src.core.pipeline import AutoPipeline

    task_id = uuid.uuid4().hex[:12]
    _task_results[task_id] = {
        "status": "queued",
        "progress": {"stage": "init", "percentage": 0},
        "result": None,
    }

    # Launch as background task
    asyncio.create_task(
        _run_pipeline(task_id, req)
    )

    return {
        "task_id": task_id,
        "status": "queued",
        "ws_url": f"ws://.../api/ws/pipeline/{task_id}",
    }


async def _run_pipeline(task_id: str, req: PipelineRunRequest) -> None:
    """Background task: execute pipeline and emit progress via WebSocket."""
    try:
        from src.core.config import load_config
        from src.core.pipeline import AutoPipeline

        _task_results[task_id]["status"] = "running"

        # NAS reads are blocking and must not stall FastAPI's event loop.
        loader = get_loader(req.dataset_root, req.profile)
        frame = await asyncio.to_thread(loader.load_frame, req.seq_id, req.frame_id)
        logger.info("Pipeline %s: frame loaded", task_id)

        # Progress callbacks execute in the worker thread; publish updates on
        # the server event loop safely.
        server_loop = asyncio.get_running_loop()

        def progress_callback(stage: str, pct: int) -> None:
            def publish() -> None:
                _task_results[task_id]["progress"] = {
                    "stage": stage, "percentage": pct,
                }
                asyncio.create_task(
                    ws_manager.send_event(
                        task_id, "progress", {"stage": stage, "percentage": pct}
                    )
                )

            server_loop.call_soon_threadsafe(publish)

        # Model construction and the async pipeline both run in one worker
        # thread, preserving the existing async Agent interfaces.
        config = load_config()

        def run_pipeline_worker():
            pipeline = AutoPipeline(config)
            return asyncio.run(pipeline.run(frame, progress=progress_callback))

        await ws_manager.send_event(task_id, "progress", {"stage": "init", "percentage": 0})

        state = await asyncio.wait_for(
            asyncio.to_thread(run_pipeline_worker),
            timeout=PIPELINE_TIMEOUT,
        )

        # Serialize boxes
        from src.core.session import _box_to_dict as box_to_dict
        boxes_data = [box_to_dict(b) for b in state.boxes]

        result = {
            "seq_id": state.seq_id,
            "frame_id": state.frame_id,
            "stage": state.stage,
            "boxes": boxes_data,
            "box_count": len(boxes_data),
        }

        _task_results[task_id] = {
            "status": "completed",
            "progress": {"stage": "agent", "percentage": 100},
            "result": result,
        }

        # Update session if provided
        if req.session_id:
            try:
                sess = get_or_create_session(req.session_id)
                sess.snapshot()
                sess.state.boxes = state.boxes
                sess.state.stage = state.stage
                logger.info("Pipeline %s: session updated", task_id)
            except Exception as e:
                logger.warning("Failed to update session: %s", e)

        await ws_manager.send_event(task_id, "completed", result)
        logger.info("Pipeline %s: completed (%d boxes)", task_id, len(boxes_data))

    except asyncio.TimeoutError:
        _task_results[task_id] = {"status": "error", "progress": {}, "result": None}
        await ws_manager.send_event(task_id, "error", {"message": "Pipeline timed out"})
        logger.error("Pipeline %s: timed out after %ds", task_id, PIPELINE_TIMEOUT)
    except Exception as e:
        logger.exception("Pipeline %s failed", task_id)
        _task_results[task_id] = {"status": "error", "progress": {}, "result": None}
        await ws_manager.send_event(task_id, "error", {"message": str(e)})


@router.get("/status/{task_id}")
async def pipeline_status(task_id: str):
    """Get current pipeline task status."""
    if task_id not in _task_results:
        raise HTTPException(status_code=404, detail="Task not found")
    return _task_results[task_id]


@router.websocket("/ws/pipeline/{task_id}")
async def pipeline_websocket(ws: WebSocket, task_id: str):
    """WebSocket endpoint for pipeline progress streaming."""
    await ws.accept()
    await ws_manager.register(task_id, ws)

    # Send current state if already running/completed
    if task_id in _task_results:
        tr = _task_results[task_id]
        await ws.send_json({"event": "status", "data": tr})
        if tr["status"] == "completed" and tr["result"]:
            await ws.send_json({"event": "completed", "data": tr["result"]})

    try:
        while True:
            data = await ws.receive_json()
            if data.get("command") == "cancel":
                if task_id in _task_results:
                    _task_results[task_id]["status"] = "cancelled"
                await ws_manager.send_event(task_id, "cancelled", {"message": "User cancelled"})
                break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        await ws_manager.unregister(task_id, ws)
