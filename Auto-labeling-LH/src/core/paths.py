"""Resolve the project base directory for both dev and frozen (PyInstaller) mode."""

from __future__ import annotations

import sys
from pathlib import Path


def base_path() -> Path:
    """Return the project root directory.

    * **Frozen** (PyInstaller ``--onedir``): ``sys._MEIPASS`` points to the
      temporary extraction folder where bundled data files reside.
    * **Development**: three levels up from ``src/core/paths.py``.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller sets sys._MEIPASS to the temp extraction dir
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.parent


def config_dir() -> Path:
    return base_path() / "config"


def writable_root() -> Path:
    """Return the folder that moves with the portable application."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return base_path()


def local_config_path() -> Path:
    return writable_root() / "config" / "local.yaml"


def profiles_dir() -> Path:
    return base_path() / "profiles"


def resources_dir() -> Path:
    return base_path() / "src" / "ui" / "resources"
