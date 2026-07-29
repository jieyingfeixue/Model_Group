"""Session CRUD endpoints."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..dependencies import get_or_create_session, list_sessions, get_loader
from ..config import SESSIONS_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


# ── request/response models ────────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    profile_name: str = "lh"
    seq_id: str | None = None
    frame_id: str | None = None


class UpdateBoxesRequest(BaseModel):
    boxes: list[dict]


# ── helpers ─────────────────────────────────────────────────────────────────

def _box_to_dict(b) -> dict:
    return {
        "object_id": b.object_id,
        "class_name": b.class_name,
        "center": b.center.tolist(),
        "dimensions": b.dimensions.tolist(),
        "rotation": b.rotation,
        "score": b.score,
        "source": b.source,
        "track_id": b.track_id,
        "attributes": b.attributes,
    }


def _dict_to_box(d: dict):
    import numpy as np
    from src.core.types import Label3D
    return Label3D(
        object_id=d.get("object_id", uuid.uuid4().hex[:8]),
        class_name=d.get("class_name", ""),
        center=np.array(d.get("center", [0, 0, 0]), dtype=float),
        dimensions=np.array(d.get("dimensions", [1, 1, 1]), dtype=float),
        rotation=d.get("rotation", 0.0),
        score=d.get("score", 1.0),
        source=d.get("source", "manual"),
        track_id=d.get("track_id", -1),
        attributes=d.get("attributes", {}),
    )


def _session_state_to_dict(s, loader=None) -> dict:
    """Serialize session state to JSON-safe dict, optionally loading frame data."""
    result: dict[str, Any] = {
        "session_id": s.state.session_id,
        "profile_name": s.state.profile_name,
        "seq_id": s.state.seq_id,
        "frame_id": s.state.frame_id,
        "stage": s.state.stage,
        "box_count": len(s.state.boxes),
        "boxes": [_box_to_dict(b) for b in s.state.boxes],
        "undo_stack_size": len(s._undo_stack),
        "redo_stack_size": len(s._redo_stack),
    }
    # Load frame metadata if available
    if loader and s.state.seq_id and s.state.frame_id:
        try:
            frame = loader.load_frame(s.state.seq_id, s.state.frame_id)
            result["frame_meta"] = {
                "timestamp": frame.timestamp,
                "cameras": list(frame.images.keys()),
                "pointclouds": list(frame.pointclouds.keys()),
                "radar_tensors": list(frame.radar_tensors.keys()),
            }
        except Exception:
            result["frame_meta"] = None
    return result


# ── endpoints ───────────────────────────────────────────────────────────────

@router.get("/")
async def session_list():
    """List all active sessions."""
    return {"sessions": list_sessions()}


@router.post("/")
async def session_create(req: CreateSessionRequest):
    """Create a new annotation session."""
    s = get_or_create_session()
    s.state.profile_name = req.profile_name
    if req.seq_id:
        s.state.seq_id = req.seq_id
    if req.frame_id:
        s.state.frame_id = req.frame_id
    return {"session_id": s.state.session_id,
            "message": "Session created"}


@router.get("/{session_id}")
async def session_get(
    session_id: str,
    dataset_root: str | None = Query(None),
    profile: str = Query("lh"),
):
    """Get full session state."""
    s = get_or_create_session(session_id)
    loader = None
    if dataset_root and s.state.seq_id and s.state.frame_id:
        try:
            loader = get_loader(dataset_root, profile)
        except Exception:
            pass
    return _session_state_to_dict(s, loader)


@router.put("/{session_id}/boxes")
async def session_update_boxes(session_id: str, req: UpdateBoxesRequest):
    """Replace all boxes in the session."""
    s = get_or_create_session(session_id)
    s.snapshot()  # Save current state for undo
    s.state.boxes = [_dict_to_box(d) for d in req.boxes]
    return {
        "success": True,
        "box_count": len(s.state.boxes),
        "undo_stack_size": len(s._undo_stack),
    }


@router.post("/{session_id}/undo")
async def session_undo(session_id: str):
    """Undo last box change."""
    s = get_or_create_session(session_id)
    ok = s.undo()
    return {
        "success": ok,
        "boxes": [_box_to_dict(b) for b in s.state.boxes],
        "undo_stack_size": len(s._undo_stack),
        "redo_stack_size": len(s._redo_stack),
    }


@router.post("/{session_id}/redo")
async def session_redo(session_id: str):
    """Redo last undo."""
    s = get_or_create_session(session_id)
    ok = s.redo()
    return {
        "success": ok,
        "boxes": [_box_to_dict(b) for b in s.state.boxes],
        "undo_stack_size": len(s._undo_stack),
        "redo_stack_size": len(s._redo_stack),
    }


@router.post("/{session_id}/save")
async def session_save(session_id: str):
    """Persist session to disk."""
    s = get_or_create_session(session_id)
    path = s.save()
    return {"success": True, "path": str(path)}


@router.put("/{session_id}/meta")
async def session_update_meta(
    session_id: str,
    seq_id: str | None = None,
    frame_id: str | None = None,
    stage: str | None = None,
):
    """Update session metadata (seq_id, frame_id, stage)."""
    s = get_or_create_session(session_id)
    if seq_id is not None:
        s.state.seq_id = seq_id
    if frame_id is not None:
        s.state.frame_id = frame_id
    if stage is not None:
        s.state.stage = stage
    return {"success": True}


@router.delete("/{session_id}")
async def session_delete(session_id: str):
    """Delete a session."""
    from ..dependencies import _sessions
    if session_id in _sessions:
        s = _sessions.pop(session_id)
        s.close()
        return {"success": True}
    raise HTTPException(status_code=404, detail="Session not found")


@router.get("/{session_id}/load")
async def session_load_from_file(
    session_id: str,
    path: str = Query(..., description="Path to session JSON file"),
):
    """Load a session from a JSON file."""
    from pathlib import Path
    s = get_or_create_session(session_id)
    s.load(Path(path))
    return {"success": True, "boxes": [_box_to_dict(b) for b in s.state.boxes]}
