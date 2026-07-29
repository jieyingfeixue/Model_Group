"""WebSocket connection manager for pipeline progress streaming."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    """Track per-task WebSocket connections."""

    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def register(self, task_id: str, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.setdefault(task_id, []).append(ws)
            logger.debug("WS registered for task %s (total: %d)",
                         task_id, len(self._connections[task_id]))

    async def unregister(self, task_id: str, ws: WebSocket) -> None:
        async with self._lock:
            if task_id in self._connections:
                self._connections[task_id] = [
                    c for c in self._connections[task_id] if c is not ws
                ]
                if not self._connections[task_id]:
                    del self._connections[task_id]

    async def send_event(self, task_id: str, event: str, data: Any = None) -> None:
        """Send a JSON event to all WebSockets watching *task_id*."""
        payload = {"event": event, "data": data}
        async with self._lock:
            conns = list(self._connections.get(task_id, []))
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:
                logger.debug("Failed to send to WS for task %s, removing", task_id)
                await self.unregister(task_id, ws)

    async def broadcast(self, event: str, data: Any = None) -> None:
        """Send to ALL connected websockets."""
        payload = {"event": event, "data": data}
        async with self._lock:
            all_ws = [ws for conns in self._connections.values() for ws in conns]
        for ws in all_ws:
            try:
                await ws.send_json(payload)
            except Exception:
                pass


# singleton
ws_manager = WebSocketManager()
