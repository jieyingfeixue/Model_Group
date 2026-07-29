"""Export endpoints — KITTI and JSON format."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..dependencies import get_or_create_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportRequest(BaseModel):
    session_id: str
    seq_id: str | None = None
    frame_ids: list[str] | None = None  # None = all frames in session
    format: str = "json"  # "json" | "kitti"
    output_dir: str = "./sessions/exports"


@router.post("/")
async def export_labels(req: ExportRequest):
    """Export annotations to KITTI or JSON format."""
    try:
        from src.export.writer import ExportWriter
        from src.io.label_io import save_labels

        session = get_or_create_session(req.session_id)
        boxes = session.state.boxes

        if not boxes:
            raise HTTPException(status_code=400, detail="No boxes to export")

        output_path = Path(req.output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        seq_id = req.seq_id or session.state.seq_id or "unknown"
        frame_id = session.state.frame_id or "frame_000000"

        fmt = req.format.lower()
        if fmt not in ("json", "kitti"):
            raise HTTPException(status_code=400, detail=f"Unsupported format: {fmt}")

        if fmt == "json":
            out_file = output_path / f"{seq_id.replace('/', '_')}_{frame_id}.json"
            save_labels(boxes, out_file, "json")
        elif fmt == "kitti":
            out_file = output_path / f"{seq_id.replace('/', '_')}_{frame_id}.txt"
            save_labels(boxes, out_file, "kitti")

        return {
            "success": True,
            "path": str(out_file),
            "format": fmt,
            "box_count": len(boxes),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Export failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/formats")
async def list_formats():
    """List supported export formats."""
    return {
        "formats": [
            {"id": "json", "name": "JSON", "description": "JSON array of Label3D objects"},
            {"id": "kitti", "name": "KITTI", "description": "KITTI 3D object detection format"},
        ]
    }
