"""
Storm Energy RTU Platform — TCP connection registry.
Tracks active connections for health reporting.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from typing import Dict

logger = logging.getLogger(__name__)


class TCPConnectionRegistry:
    """Thread-safe registry of active TCP connections."""

    def __init__(self):
        self._connections: Dict[str, asyncio.StreamWriter] = {}
        self._lock = threading.Lock()

    def add(self, peer: str, writer: asyncio.StreamWriter) -> None:
        with self._lock:
            self._connections[peer] = writer
        logger.debug("TCP registry: +%s (%d total)", peer, self.count)

    def remove(self, peer: str) -> None:
        with self._lock:
            self._connections.pop(peer, None)
        logger.debug("TCP registry: -%s (%d total)", peer, self.count)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._connections)

    @property
    def peers(self) -> list[str]:
        with self._lock:
            return list(self._connections.keys())
