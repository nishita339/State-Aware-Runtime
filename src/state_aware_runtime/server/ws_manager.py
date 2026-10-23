"""
Real-Time WebSocket Connection Multiplexer.

Manages persistent WebSocket connections for millions of real-time subscribers
streaming step-level telemetry, contract verdicts, drift updates, and state diffs.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any
from fastapi import WebSocket

logger = logging.getLogger(__name__)

__all__ = ["WebSocketManager"]


class WebSocketManager:
    """High-throughput async WebSocket multiplexer with session partitioning."""

    def __init__(self) -> None:
        # session_id -> list of active WebSockets
        self._active_connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._lock = asyncio.Lock()
        self._total_broadcasts: int = 0

    @property
    def total_connections(self) -> int:
        return sum(len(conns) for conns in self._active_connections.values())

    @property
    def total_broadcasts(self) -> int:
        return self._total_broadcasts

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept and register a new client connection for a session."""
        await websocket.accept()
        async with self._lock:
            self._active_connections[session_id].append(websocket)
        logger.info(
            "WS client connected to session %s (total session clients: %d)",
            session_id,
            len(self._active_connections[session_id]),
        )

    async def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Unregister a disconnected client."""
        async with self._lock:
            if session_id in self._active_connections:
                if websocket in self._active_connections[session_id]:
                    self._active_connections[session_id].remove(websocket)
                if not self._active_connections[session_id]:
                    del self._active_connections[session_id]
        logger.info("WS client disconnected from session %s", session_id)

    async def broadcast_to_session(self, session_id: str, message: dict[str, Any]) -> int:
        """
        Broadcast a JSON payload to all active clients subscribed to session_id.
        Handles slow consumers and disconnected sockets gracefully.
        """
        async with self._lock:
            connections = list(self._active_connections.get(session_id, []))

        if not connections:
            return 0

        data_text = json.dumps(message, default=str)
        dead_connections: list[WebSocket] = []
        sent_count = 0

        for ws in connections:
            try:
                await ws.send_text(data_text)
                sent_count += 1
            except Exception as e:
                logger.debug("Failed sending WS frame, queuing removal: %s", e)
                dead_connections.append(ws)

        if dead_connections:
            async with self._lock:
                for dead in dead_connections:
                    if session_id in self._active_connections:
                        if dead in self._active_connections[session_id]:
                            self._active_connections[session_id].remove(dead)

        self._total_broadcasts += sent_count
        return sent_count

    async def broadcast_global(self, message: dict[str, Any]) -> int:
        """Broadcast a global system-wide event (e.g. system maintenance)."""
        async with self._lock:
            all_sockets = [
                ws for sockets in self._active_connections.values() for ws in sockets
            ]

        data_text = json.dumps(message, default=str)
        sent = 0
        for ws in all_sockets:
            try:
                await ws.send_text(data_text)
                sent += 1
            except Exception:
                pass
        return sent
