"""Shared FastAPI dependencies — singleton loader and session registry."""

from __future__ import annotations

import logging
from pathlib import Path

from src.core.session import Session
from src.core.config import load_profile
from src.io.frame_loader import FrameLoader
from src.io.sensor_profile import sensor_profile_from_dict

from .config import DATASET_ROOT, SESSIONS_DIR, get_app_config

logger = logging.getLogger(__name__)

# ── module-level singletons (lazy) ──────────────────────────────────────────

_loader: FrameLoader | None = None
_loader_dataset_root: str | None = None
_loader_profile_name: str | None = None

_sessions: dict[str, Session] = {}  # session_id → Session


def get_loader(dataset_root: str, profile_name: str) -> FrameLoader:
    """Return (or re-create) the shared FrameLoader singleton."""
    global _loader, _loader_dataset_root, _loader_profile_name
    requested_root = Path(dataset_root or DATASET_ROOT).expanduser().absolute()
    configured_root = DATASET_ROOT.absolute()
    if requested_root != configured_root:
        raise ValueError("Dataset root is outside the configured offline dataset")
    dataset_root = str(requested_root)
    if (_loader is None or _loader_dataset_root != dataset_root
            or _loader_profile_name != profile_name):
        profile = sensor_profile_from_dict(load_profile(profile_name))
        _loader = FrameLoader(profile, Path(dataset_root))
        _loader_dataset_root = dataset_root
        _loader_profile_name = profile_name
        logger.info("Created FrameLoader for %s (%s)", dataset_root, profile_name)
    return _loader


def get_or_create_session(session_id: str | None = None,
                          config: dict | None = None) -> Session:
    """Return existing session or create a new one."""
    if session_id and session_id in _sessions:
        return _sessions[session_id]
    cfg = config or get_app_config()
    s = Session(cfg, save_dir=SESSIONS_DIR)
    if session_id:
        s.state.session_id = session_id
    _sessions[s.state.session_id] = s
    return s


def list_sessions() -> list[dict]:
    """List all active sessions."""
    result = []
    for sid, s in _sessions.items():
        result.append({
            "session_id": s.state.session_id,
            "profile_name": s.state.profile_name,
            "seq_id": s.state.seq_id,
            "frame_id": s.state.frame_id,
            "stage": s.state.stage,
            "box_count": len(s.state.boxes),
        })
    return result
