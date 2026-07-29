"""Tests for session management."""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from src.core.types import Label3D
from src.core.session import Session


def test_undo_redo():
    session = Session({"app": {"undo_history_limit": 10}})
    box = Label3D(object_id="b1", class_name="car", center=np.array([1.0, 0.0, 0.0]))
    session.state.boxes = [box]
    session.snapshot()
    session.state.boxes = []

    assert session.undo()
    assert len(session.state.boxes) == 1
    assert session.state.boxes[0].object_id == "b1"

    assert session.redo()
    assert len(session.state.boxes) == 0


def test_save_load():
    with tempfile.TemporaryDirectory() as tmpdir:
        session = Session({"app": {}}, save_dir=Path(tmpdir))
        session.state.seq_id = "1"
        session.state.frame_id = "042"
        session.state.boxes = [
            Label3D(object_id="b1", class_name="car", center=np.array([5.0, 3.0, 1.0]),
                    dimensions=np.array([4.0, 1.8, 1.5]))
        ]
        path = session.save()

        session2 = Session({"app": {}}, save_dir=Path(tmpdir))
        session2.load(path)
        assert session2.state.seq_id == "1"
        assert session2.state.frame_id == "042"
        assert len(session2.state.boxes) == 1
        assert session2.state.boxes[0].class_name == "car"
        session.close()
        session2.close()


def test_save_if_due():
    session = Session({"app": {"auto_save_interval_sec": 0}})
    # Should not raise
    session.save_if_due()
    session.close()
