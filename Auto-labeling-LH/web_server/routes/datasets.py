"""Dataset, sequence, and frame listing endpoints.

NOTE: seq_id and frame_id may contain "/" characters, so they are passed as
query parameters instead of path parameters.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from ..dependencies import get_loader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["datasets"])


@router.get("/datasets")
async def list_datasets(
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
):
    """List available datasets under *dataset_root*."""
    try:
        loader = get_loader(dataset_root, profile)
        sequences = loader.list_sequences()
        return {
            "dataset_root": dataset_root,
            "profile": profile,
            "sequences": sequences,
            "count": len(sequences),
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Failed to list datasets")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sequences")
async def list_sequences(
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
):
    """List all sequences (grouped hierarchically) under *dataset_root*."""
    try:
        loader = get_loader(dataset_root, profile)
        seqs = loader.list_sequences()

        # Build hierarchical grouping: date → capture → part → segment
        tree: dict[str, Any] = {}
        for seq in seqs:
            parts = seq.split("/")
            date_key = parts[0] if len(parts) > 0 else "unknown"
            capture_key = parts[1] if len(parts) > 1 else "unknown"
            part_key = parts[2] if len(parts) > 2 else "unknown"
            segment_key = parts[3] if len(parts) > 3 else seq

            tree.setdefault(date_key, {})\
                .setdefault(capture_key, {})\
                .setdefault(part_key, [])\
                .append({"segment_id": segment_key, "full_path": seq})

        return {
            "dataset_root": dataset_root,
            "profile": profile,
            "tree": tree,
            "flat": seqs,
            "count": len(seqs),
        }
    except Exception as e:
        logger.exception("Failed to list sequences")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/frames")
async def list_frames(
    seq_id: str = Query(..., description="Sequence ID (may contain /)"),
    dataset_root: str = Query(..., description="Dataset root path"),
    profile: str = Query("lh", description="Sensor profile name"),
    page: int = Query(1, ge=1),
    per_page: int = Query(200, ge=1, le=1000),
):
    """List frames for a sequence with pagination."""
    try:
        loader = get_loader(dataset_root, profile)
        frames = loader.list_frames(seq_id)
        total = len(frames)
        start = (page - 1) * per_page
        end = start + per_page
        page_frames = frames[start:end]

        return {
            "seq_id": seq_id,
            "frames": page_frames,
            "total": total,
            "page": page,
            "per_page": per_page,
            "has_more": end < total,
        }
    except Exception as e:
        logger.exception("Failed to list frames for %s", seq_id)
        raise HTTPException(status_code=500, detail=str(e))
