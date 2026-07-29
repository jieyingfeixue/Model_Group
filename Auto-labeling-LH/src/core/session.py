"""Session management with auto-save and undo/redo."""

from __future__ import annotations

import copy
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from .types import Label3D, Operation, SessionState


class Session:
    """Manages annotation state for a single sequence with auto-save and undo."""

    def __init__(self, config: dict[str, Any], save_dir: Path | None = None):
        self.config = config
        self.state = SessionState()
        self._undo_stack: list[list[Label3D]] = []
        self._redo_stack: list[list[Label3D]] = []
        self._max_undo = config.get("app", {}).get("undo_history_limit", 50)
        self._last_save = time.time()
        self._save_interval = config.get("app", {}).get("auto_save_interval_sec", 60)
        self._save_dir = save_dir or Path("./sessions")
        self._db: sqlite3.Connection | None = None

    # ---- undo / redo -------------------------------------------------------

    def snapshot(self) -> None:
        """Save current boxes for undo."""
        self._undo_stack.append([b.copy() for b in self.state.boxes])
        if len(self._undo_stack) > self._max_undo:
            self._undo_stack.pop(0)
        self._redo_stack.clear()

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append([b.copy() for b in self.state.boxes])
        self.state.boxes = self._undo_stack.pop()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append([b.copy() for b in self.state.boxes])
        self.state.boxes = self._redo_stack.pop()
        return True

    # ---- Phase 4: Operation-based undo history ---------------------------

    def apply_operation(self, op: "Operation") -> None:
        """Record an Operation into the session history deque.

        The Operation carries ``before`` and ``after`` snapshots so it can be
        replayed or reversed at any time without rerunning the pipeline.
        """
        self.state.operations.append(op)

    def undo_operation(self) -> "Operation | None":
        """Pop the latest operation and restore its ``before`` state.

        Returns the operation (for logging), or None if the stack is empty.
        """
        if not self.state.operations:
            return None
        op = self.state.operations[-1]
        # Restore state.boxes to the before snapshot
        self.state.boxes = [b.copy() for b in op.before]
        # Remove from deque (we used [-1] so we pop from right)
        try:
            self.state.operations.pop()
        except Exception:
            pass
        return op

    def last_operation(self) -> "Operation | None":
        """Return the most recent operation without removing it."""
        if not self.state.operations:
            return None
        return self.state.operations[-1]

    # ---- persistence -------------------------------------------------------

    def save_if_due(self) -> None:
        """Auto-save if interval has elapsed."""
        if time.time() - self._last_save >= self._save_interval:
            self.save()

    def save(self) -> Path:
        """Save session state to a JSON file + SQLite."""
        self._save_dir.mkdir(parents=True, exist_ok=True)
        path = self._save_dir / f"{self.state.session_id}.json"
        data = {
            "session_id": self.state.session_id,
            "profile_name": self.state.profile_name,
            "seq_id": self.state.seq_id,
            "frame_id": self.state.frame_id,
            "stage": self.state.stage,
            "boxes": [_box_to_dict(b) for b in self.state.boxes],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._last_save = time.time()
        self._save_to_db(data)
        return path

    def load(self, path: Path) -> None:
        """Restore session from JSON."""
        data = json.loads(path.read_text(encoding="utf-8"))
        self.state.session_id = data["session_id"]
        self.state.profile_name = data.get("profile_name", "")
        self.state.seq_id = data.get("seq_id", "")
        self.state.frame_id = data.get("frame_id", "")
        self.state.stage = data.get("stage", "init")
        self.state.boxes = [_dict_to_box(d) for d in data.get("boxes", [])]

    def _save_to_db(self, data: dict) -> None:
        """Persist to SQLite for crash recovery."""
        if self._db is None:
            db_path = self._save_dir / "sessions.db"
            self._db = sqlite3.connect(str(db_path))
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS sessions "
                "(session_id TEXT PRIMARY KEY, data TEXT, updated_at REAL)"
            )
        self._db.execute(
            "INSERT OR REPLACE INTO sessions VALUES (?, ?, ?)",
            (data["session_id"], json.dumps(data, ensure_ascii=False), time.time()),
        )
        self._db.commit()

    def close(self) -> None:
        if self._db:
            self._db.close()
            self._db = None


# ---- helpers ---------------------------------------------------------------

def _box_to_dict(b: Label3D) -> dict:
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


def _dict_to_box(d: dict) -> Label3D:
    import numpy as np

    return Label3D(
        object_id=d["object_id"],
        class_name=d["class_name"],
        center=np.array(d["center"], dtype=float),
        dimensions=np.array(d["dimensions"], dtype=float),
        rotation=d.get("rotation", 0.0),
        score=d.get("score", 1.0),
        source=d.get("source", "manual"),
        track_id=d.get("track_id", -1),
        attributes=d.get("attributes", {}),
    )
