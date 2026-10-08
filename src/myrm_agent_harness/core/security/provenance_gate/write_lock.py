"""Serialized write lock manager preventing concurrent write races using WeakValueDictionary.

[INPUT]
- lock_key (e.g. f"{session_id}:{entity_id}" or session_id)

[OUTPUT]
- SerializedWriteLockManager: provides async lock acquisition with auto-reclaiming WeakValueDictionary.

[POS]
Harness core concurrency & security module inspired by Anthropic Commerce Agents (_cart_locks / Serialized Write Locking).
"""

from __future__ import annotations

import asyncio
import threading
import weakref
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class SerializedWriteLockManager:
    """Manages ephemeral per-session and per-entity asyncio locks backed by WeakValueDictionary."""

    def __init__(self) -> None:
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
        self._mutex = threading.Lock()

    def get_lock(self, key: str) -> asyncio.Lock:
        """Get or create an asyncio.Lock for the specified resource key."""
        with self._mutex:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
            return lock

    @asynccontextmanager
    async def acquire(self, key: str) -> AsyncIterator[asyncio.Lock]:
        """Async context manager to serialize concurrent mutations on the same resource key."""
        lock = self.get_lock(key)
        await lock.acquire()
        try:
            yield lock
        finally:
            lock.release()

    def active_lock_count(self) -> int:
        """Number of active locks currently retained in memory."""
        with self._mutex:
            return len(self._locks)
