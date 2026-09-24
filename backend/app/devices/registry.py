"""
Storm Energy RTU Platform — In-memory device registry.
Caches known device IDs for fast validation in the hot message path.
Refreshed from the database on startup and on device registration.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional, Set

logger = logging.getLogger(__name__)


class DeviceRegistry:
    """Thread-safe in-memory set of known DeviceIds."""

    def __init__(self):
        self._known: Set[str] = set()
        self._lock  = threading.RLock()

    def load_from_db(self, db) -> None:
        from app.database.repository import DeviceRepository
        devices = DeviceRepository.get_all_active(db)
        with self._lock:
            self._known = {d.DeviceId for d in devices}
        logger.info("Device registry loaded: %d active devices", len(self._known))

    def is_known(self, device_id: str) -> bool:
        with self._lock:
            return device_id in self._known

    def register(self, device_id: str) -> None:
        with self._lock:
            self._known.add(device_id)

    def deregister(self, device_id: str) -> None:
        with self._lock:
            self._known.discard(device_id)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._known)


# Module-level singleton
device_registry = DeviceRegistry()
