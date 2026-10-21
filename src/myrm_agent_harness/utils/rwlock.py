"""Async read-write lock for concurrent access control.

Allows multiple concurrent readers OR one exclusive writer. Prevents writer
starvation by queuing writers fairly.

Usage:
    lock = RWLock()

    # Multiple readers can hold the lock simultaneously
    async with lock.read():
        data = await read_shared_resource()

    # Writers get exclusive access
    async with lock.write():
        await write_shared_resource(data)

[INPUT]
- (none — standalone utility)

[OUTPUT]
- RWLock: Async read-write lock implementation

[POS]
General-purpose read-write lock concurrency primitive for multi-reader single-writer scenarios.

"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class RWLock:
    """Async read-write lock allowing multiple concurrent readers.

    Multiple readers can hold the lock simultaneously, but writers have
    exclusive access. Prevents writer starvation by queuing writers fairly.
    """

    def __init__(self) -> None:
        self._readers = 0
        self._writers_waiting = 0
        self._writer_active = False
        self._lock = asyncio.Lock()
        self._read_ok = asyncio.Condition(self._lock)
        self._write_ok = asyncio.Condition(self._lock)

    async def read_acquire(self) -> None:
        """Acquire read lock (non-exclusive)."""
        async with self._lock:
            while self._writer_active or self._writers_waiting > 0:
                await self._read_ok.wait()
            self._readers += 1

    async def read_release(self) -> None:
        """Release read lock."""
        async with self._lock:
            self._readers -= 1
            if self._readers == 0:
                self._write_ok.notify()

    async def write_acquire(self) -> None:
        """Acquire write lock (exclusive)."""
        async with self._lock:
            self._writers_waiting += 1
            while self._readers > 0 or self._writer_active:
                await self._write_ok.wait()
            self._writers_waiting -= 1
            self._writer_active = True

    async def write_release(self) -> None:
        """Release write lock."""
        async with self._lock:
            self._writer_active = False
            if self._writers_waiting > 0:
                self._write_ok.notify()
            else:
                self._read_ok.notify_all()

    @asynccontextmanager
    async def read(self) -> AsyncIterator[None]:
        """Context manager for read lock."""
        await self.read_acquire()
        try:
            yield
        finally:
            await self.read_release()

    @asynccontextmanager
    async def write(self) -> AsyncIterator[None]:
        """Context manager for write lock."""
        await self.write_acquire()
        try:
            yield
        finally:
            await self.write_release()
