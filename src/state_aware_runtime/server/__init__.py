"""
State-Aware Durable Runtime — Production Real-Time Server.

Provides a high-concurrency, distributed async gateway and WebSocket
multiplexer for millions of concurrent users.
"""

from __future__ import annotations

__all__ = ["app"]

try:
    from state_aware_runtime.server.app import app
except ImportError:
    app = None  # type: ignore
