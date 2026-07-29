"""Configuration loader and manager."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from src.core.paths import config_dir, local_config_path, profiles_dir

_DEFAULT_CONFIG = config_dir() / "default.yaml"
_PROFILES_DIR = profiles_dir()
_RUNTIME_OVERRIDES: dict[str, Any] = {}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load YAML configuration, merging defaults with overrides."""
    cfg = _load_yaml(_DEFAULT_CONFIG)
    local_path = local_config_path()
    if local_path.exists():
        cfg = _deep_merge(cfg, _load_yaml(local_path))
    if path is not None:
        overrides = _load_yaml(Path(path))
        cfg = _deep_merge(cfg, overrides)
    if _RUNTIME_OVERRIDES:
        cfg = _deep_merge(cfg, _RUNTIME_OVERRIDES)
    # Resolve env-var references (e.g. api_key_env → actual key)
    _resolve_env_vars(cfg)
    return cfg


def set_runtime_overrides(overrides: dict[str, Any]) -> None:
    """Replace process-local configuration overrides."""
    global _RUNTIME_OVERRIDES
    _RUNTIME_OVERRIDES = dict(overrides or {})


def load_profile(name: str) -> dict[str, Any]:
    """Load a sensor profile YAML by name."""
    path = _PROFILES_DIR / f"{name}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Profile '{name}' not found at {path}")
    return _load_yaml(path)


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge *override* into *base*."""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def _resolve_env_vars(cfg: dict) -> None:
    """Replace ``api_key_env`` entries with values from the environment."""
    for _key, val in cfg.items():
        if isinstance(val, dict):
            if "api_key_env" in val:
                env_name = val["api_key_env"]
                val["api_key"] = os.environ.get(env_name, "")
            if "password_env" in val:
                env_name = val["password_env"]
                val["password"] = os.environ.get(
                    env_name, val.get("password", "")
                )
            _resolve_env_vars(val)
