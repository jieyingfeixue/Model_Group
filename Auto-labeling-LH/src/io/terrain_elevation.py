"""Cached terrain elevation lookup for converting MSL altitude to AGL."""

from __future__ import annotations

import json
import logging
import threading
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

logger = logging.getLogger(__name__)

_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="terrain")
_LOCK = threading.Lock()
_CACHE: dict[str, float] | None = None


def _cache_path() -> Path:
    project_root = Path(__file__).resolve().parents[2]
    path = project_root / "temp" / "terrain_elevation" / "elevation_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_cache() -> dict[str, float]:
    global _CACHE
    with _LOCK:
        if _CACHE is not None:
            return _CACHE
        try:
            raw = json.loads(_cache_path().read_text(encoding="utf-8"))
            _CACHE = {str(key): float(value) for key, value in raw.items()}
        except Exception:
            _CACHE = {}
        return _CACHE


def _lookup_ground_elevation(lat: float, lon: float) -> float | None:
    # Four decimals is roughly 11 m and avoids repeated requests while moving.
    key = f"{float(lat):.4f},{float(lon):.4f}"
    cache = _load_cache()
    with _LOCK:
        cached = cache.get(key)
    if cached is not None:
        return float(cached)

    query = urllib.parse.urlencode({
        "latitude": f"{float(lat):.6f}",
        "longitude": f"{float(lon):.6f}",
    })
    url = f"https://api.open-meteo.com/v1/elevation?{query}"
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "LH-AutoLabeling/1.0"}
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
        values = payload.get("elevation")
        value = float(values[0] if isinstance(values, list) else values)
    except Exception as exc:
        logger.debug("terrain elevation lookup failed at %s: %s", key, exc)
        return None

    with _LOCK:
        cache[key] = value
        try:
            path = _cache_path()
            temporary = path.with_suffix(".tmp")
            temporary.write_text(
                json.dumps(cache, ensure_ascii=True, sort_keys=True),
                encoding="utf-8",
            )
            temporary.replace(path)
        except Exception as exc:
            logger.debug("terrain elevation cache write failed: %s", exc)
    return value


def request_ground_elevation(lat: float, lon: float) -> Future:
    """Return a future resolving to terrain elevation in metres above MSL."""
    return _EXECUTOR.submit(_lookup_ground_elevation, float(lat), float(lon))
