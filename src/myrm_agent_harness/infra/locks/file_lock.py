"""Unified file-based locking with metrics.

Provides file-based locks using fcntl to prevent race conditions when multiple
asyncio tasks within the same sandbox access the same resources concurrently.

**Use Case**: Coordinates multiple asyncio tasks in the same process to prevent
duplicate processing or data corruption.

**Important**: This is for intra-sandbox coordination (multiple asyncio tasks
in same process), NOT for cross-sandbox locking (sandboxes are isolated).

Lock is automatically released on process crash (OS guarantee).

[INPUT]

[OUTPUT]
- FileLock: File-based lock context manager with metrics
- LockMetrics: Lock performance metrics
- acquire_file_lock: Convenience function for common use cases

[POS]
Unified file locking implementation. Provides fcntl-based locks for coordinating
multiple asyncio tasks within the same sandbox process, with built-in metrics
for monitoring lock contention and performance.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from myrm_agent_harness.utils import os_compat as fcntl

logger = logging.getLogger(__name__)


@dataclass
class LockMetrics:
    """Lock performance metrics for monitoring and tuning.

    Tracks lock acquisition success/failure rates and timing to identify
    contention issues and performance bottlenecks.

    Attributes:
        lock_attempts: Total number of lock acquisition attempts
        lock_acquired: Number of successful lock acquisitions
        lock_failed: Number of failed acquisitions (already locked)
        lock_errors: Number of errors during lock operations
        total_wait_time_ms: Cumulative time spent waiting for locks (ms)
        max_wait_time_ms: Maximum single lock wait time (ms)
    """

    lock_attempts: int = 0
    lock_acquired: int = 0
    lock_failed: int = 0
    lock_errors: int = 0
    total_wait_time_ms: float = 0.0
    max_wait_time_ms: float = 0.0

    def record_attempt(self) -> None:
        """Record a lock acquisition attempt."""
        self.lock_attempts += 1

    def record_acquired(self, wait_time_ms: float) -> None:
        """Record successful lock acquisition.

        Args:
            wait_time_ms: Time spent waiting for the lock (milliseconds)
        """
        self.lock_acquired += 1
        self.total_wait_time_ms += wait_time_ms
        self.max_wait_time_ms = max(self.max_wait_time_ms, wait_time_ms)

    def record_failed(self) -> None:
        """Record failed lock acquisition (already locked)."""
        self.lock_failed += 1

    def record_error(self) -> None:
        """Record error during lock operation."""
        self.lock_errors += 1

    @property
    def avg_wait_time_ms(self) -> float:
        """Average lock wait time in milliseconds."""
        if self.lock_acquired == 0:
            return 0.0
        return self.total_wait_time_ms / self.lock_acquired

    @property
    def success_rate(self) -> float:
        """Lock acquisition success rate (0.0 - 1.0)."""
        if self.lock_attempts == 0:
            return 0.0
        return self.lock_acquired / self.lock_attempts

    def to_dict(self) -> dict[str, float]:
        """Export metrics as dictionary for logging/monitoring."""
        return {
            "lock_attempts": self.lock_attempts,
            "lock_acquired": self.lock_acquired,
            "lock_failed": self.lock_failed,
            "lock_errors": self.lock_errors,
            "total_wait_time_ms": self.total_wait_time_ms,
            "max_wait_time_ms": self.max_wait_time_ms,
            "avg_wait_time_ms": self.avg_wait_time_ms,
            "success_rate": self.success_rate,
        }


class FileLock:
    """File-based lock with metrics tracking.

    Provides fcntl-based locking for coordinating multiple asyncio tasks
    within the same sandbox process. Supports both blocking and non-blocking
    modes, shared and exclusive locks, with built-in metrics collection.

    **Concurrency Model**:
    - Type: asyncio Task coordination (NOT multiprocessing/threading)
    - Scope: Same process, multiple concurrent asyncio tasks
    - Isolation: Each sandbox has independent filesystem
    - Auto-release: Lock released on process crash (OS guarantee)

    **Lock Modes**:
    - Exclusive (LOCK_EX): Write lock, blocks all other locks
    - Shared (LOCK_SH): Read lock, allows other shared locks

    **Blocking Modes**:
    - Non-blocking: Returns immediately if lock unavailable
    - Blocking: Waits until lock becomes available (not recommended for asyncio)

    Attributes:
        lock_dir: Directory for lock files
        metrics: Lock performance metrics
    """

    def __init__(
        self,
        lock_dir: Path,
        *,
        enable_metrics: bool = True,
    ) -> None:
        """Initialize FileLock.

        Args:
            lock_dir: Directory for storing lock files
            enable_metrics: Whether to collect performance metrics
        """
        self.lock_dir = lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)
        self._enable_metrics = enable_metrics
        self.metrics = LockMetrics() if enable_metrics else None

    @asynccontextmanager
    async def acquire(
        self,
        resource_id: str,
        *,
        mode: Literal["exclusive", "shared"] = "exclusive",
        blocking: bool = False,
    ) -> AsyncIterator[bool]:
        """Acquire file lock for resource.

        Args:
            resource_id: Unique identifier for the resource to lock
            mode: Lock mode - "exclusive" for write, "shared" for read
            blocking: If False, returns immediately if lock unavailable.
                     If True, waits for lock (not recommended for asyncio).

        Yields:
            True if lock acquired successfully, False if already locked
            (only when blocking=False)

        Example:
            >>> lock = FileLock(Path("/tmp/locks"))
            >>> async with lock.acquire("resource-123") as acquired:
            ...     if acquired:
            ...         # Process resource
            ...         pass
            ...     else:
            ...         # Already locked by another task
            ...         pass
        """
        lock_file = self.lock_dir / f"{resource_id}.lock"
        start_time = time.perf_counter()

        if self.metrics:
            self.metrics.record_attempt()

        file_handle = None
        lock_acquired = False

        try:
            # Open lock file
            file_handle = open(lock_file, "w", encoding="utf-8")  # noqa: SIM115

            # Determine lock flags
            lock_flags = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
            if not blocking:
                lock_flags |= fcntl.LOCK_NB

            try:
                # Acquire lock
                fcntl.flock(file_handle.fileno(), lock_flags)
                lock_acquired = True

                wait_time_ms = (time.perf_counter() - start_time) * 1000
                if self.metrics:
                    self.metrics.record_acquired(wait_time_ms)

                logger.debug(f"Acquired {mode} lock for resource: {resource_id} (wait: {wait_time_ms:.2f}ms)")
                yield True

            except BlockingIOError:
                # Lock already held by another task
                if self.metrics:
                    self.metrics.record_failed()

                logger.debug(f"Resource already locked: {resource_id}")
                yield False

        except Exception as e:
            if self.metrics:
                self.metrics.record_error()

            logger.error(f"Error acquiring lock for {resource_id}: {e}")
            yield False

        finally:
            # Release lock and cleanup
            if lock_acquired and file_handle:
                try:
                    fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
                except Exception as e:
                    logger.warning(f"Failed to release lock for {resource_id}: {e}")

            if file_handle:
                try:
                    file_handle.close()
                except Exception as e:
                    logger.warning(f"Failed to close lock file for {resource_id}: {e}")

            # Clean up lock file
            if lock_acquired:
                try:
                    if lock_file.exists():
                        lock_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to remove lock file for {resource_id}: {e}")

    def get_metrics(self) -> dict[str, float] | None:
        """Get current lock metrics.

        Returns:
            Metrics dictionary, or None if metrics disabled
        """
        if self.metrics:
            return self.metrics.to_dict()
        return None

    def reset_metrics(self) -> None:
        """Reset metrics counters."""
        if self.metrics:
            self.metrics = LockMetrics()


# Convenience function for backward compatibility
@asynccontextmanager
async def acquire_file_lock(
    resource_id: str,
    lock_dir: Path,
    *,
    mode: Literal["exclusive", "shared"] = "exclusive",
    blocking: bool = False,
) -> AsyncIterator[bool]:
    """Convenience function for acquiring file locks.

    This is a simplified API for common use cases. For advanced usage
    (metrics collection, reusable lock objects), use FileLock class directly.

    Args:
        resource_id: Unique identifier for the resource to lock
        lock_dir: Directory for storing lock files
        mode: Lock mode - "exclusive" for write, "shared" for read
        blocking: If False, returns immediately if lock unavailable

    Yields:
        True if lock acquired successfully, False if already locked

    Example:
        >>> async with acquire_file_lock("msg-123", Path("/tmp/locks")) as locked:
        ...     if locked:
        ...         # Process message
        ...         pass
    """
    lock = FileLock(lock_dir, enable_metrics=False)
    async with lock.acquire(resource_id, mode=mode, blocking=blocking) as acquired:
        yield acquired
