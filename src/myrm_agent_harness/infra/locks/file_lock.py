"""Unified file-based locking for intra-sandbox concurrency coordination.

Provides fcntl-based locks to prevent race conditions when multiple asyncio
tasks within the same sandbox access the same resources concurrently.

**Use Case**: Coordinates multiple asyncio tasks in the same process to prevent
duplicate processing or data corruption.

**Important**: This is for intra-sandbox coordination (multiple asyncio tasks
in same process), NOT for cross-sandbox locking (sandboxes are isolated) and
NOT for cross-process locking (the server layer covers that with the
``filelock`` library).

Lock is automatically released on process crash (OS guarantee).

[INPUT]
- utils.os_compat (POS: Cross-platform OS compatibility layer)

[OUTPUT]
- FileLock: File-based lock context manager
- acquire_file_lock: Convenience function for common use cases

[POS]
Unified file locking implementation. Provides fcntl-based locks for coordinating
multiple asyncio tasks within the same sandbox process.
"""

from __future__ import annotations

import hashlib
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from myrm_agent_harness.utils import os_compat as fcntl

logger = logging.getLogger(__name__)

# A caller-supplied resource id is sanitized before it becomes part of a lock
# file name, so it can never escape ``lock_dir`` via path separators or ``..``
# segments. ``.`` is intentionally excluded: keys never need it (UUIDs use
# ``-``), and keeping it out prevents hidden lock files and ``..``-like names.
_LOCK_KEY_MAX_LENGTH = 128
_LOCK_KEY_SAFE_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
)
_LOCK_MODES = frozenset(("exclusive", "shared"))


def _sanitize_lock_key(resource_id: str) -> str:
    """Return a filesystem-safe lock file stem for the given resource id.

    Replaces every character outside the safe set with ``_`` and bounds the
    result's length, keeping a readable prefix while guaranteeing the key can
    never escape the lock directory.
    """
    sanitized = "".join(c if c in _LOCK_KEY_SAFE_CHARS else "_" for c in resource_id)
    if len(sanitized) > _LOCK_KEY_MAX_LENGTH:
        digest = hashlib.sha256(resource_id.encode("utf-8")).hexdigest()[:8]
        sanitized = f"{sanitized[: _LOCK_KEY_MAX_LENGTH - 9]}-{digest}"
    return sanitized or "_"


class FileLock:
    """File-based lock for coordinating asyncio tasks in the same process.

    **Concurrency Model**:
    - Type: asyncio Task coordination (NOT multiprocessing/threading)
    - Scope: Same process, multiple concurrent asyncio tasks
    - Isolation: Each sandbox has independent filesystem
    - Auto-release: Lock released on process crash (OS guarantee)

    **Lock Modes**:
    - Exclusive (LOCK_EX): Write lock, blocks all other locks
    - Shared (LOCK_SH): Read lock, allows other shared locks

    **Blocking Mode**:
    - ``blocking=False`` (default): Returns immediately if the lock is held.
      Callers retry with their own backoff when they need to wait.
    - ``blocking=True``: Rejected with :class:`TypeError`. Synchronous
      ``fcntl.flock`` would freeze the asyncio event loop, so waiting is the
      caller's responsibility.

    Attributes:
        lock_dir: Directory for lock files
    """

    def __init__(self, lock_dir: Path) -> None:
        """Initialize FileLock.

        Args:
            lock_dir: Directory for storing lock files
        """
        self.lock_dir = lock_dir
        self.lock_dir.mkdir(parents=True, exist_ok=True)

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
            blocking: Must be False. Passing True raises TypeError because a
                synchronous blocking flock would freeze the asyncio loop.

        Yields:
            True if lock acquired successfully, False if already locked

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
        if blocking:
            raise TypeError(
                "FileLock blocking=True is unsupported: synchronous fcntl.flock "
                "would freeze the asyncio event loop. Use blocking=False and "
                "retry with your own backoff, or serialize with asyncio.Lock."
            )
        if mode not in _LOCK_MODES:
            raise ValueError(
                f"FileLock mode={mode!r} is unsupported; use 'exclusive' or 'shared'."
            )

        lock_file = self.lock_dir / f"{_sanitize_lock_key(resource_id)}.lock"

        # Open with O_NOFOLLOW: a symlink planted in the lock directory is
        # rejected instead of followed, so it can never be truncated as an
        # empty lock file. Following a symlink could destroy whatever it points
        # at (e.g. ``~/.env``) — a real data-loss path for a framework-level
        # public API. ``0o600`` keeps the lock file private to the sandbox.
        open_flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            open_flags |= os.O_NOFOLLOW
        try:
            lock_fd = os.open(lock_file, open_flags, 0o600)
            file_handle = os.fdopen(lock_fd, "w", encoding="utf-8")
        except OSError as e:
            logger.warning("Failed to open lock file for %s: %s", resource_id, e)
            yield False
            return

        lock_acquired = False
        try:
            lock_flags = fcntl.LOCK_EX if mode == "exclusive" else fcntl.LOCK_SH
            lock_flags |= fcntl.LOCK_NB

            try:
                fcntl.flock(file_handle.fileno(), lock_flags)
            except BlockingIOError:
                logger.debug("Resource already locked: %s", resource_id)
                yield False
                return

            lock_acquired = True
            logger.debug("Acquired %s lock for resource: %s", mode, resource_id)
            yield True
        finally:
            if lock_acquired:
                try:
                    fcntl.flock(file_handle.fileno(), fcntl.LOCK_UN)
                except OSError as e:
                    logger.warning("Failed to release lock for %s: %s", resource_id, e)
            try:
                file_handle.close()
            except OSError as e:
                logger.warning("Failed to close lock file for %s: %s", resource_id, e)
            if lock_acquired:
                try:
                    if lock_file.exists():
                        lock_file.unlink()
                except OSError as e:
                    logger.warning("Failed to remove lock file for %s: %s", resource_id, e)


@asynccontextmanager
async def acquire_file_lock(
    resource_id: str,
    lock_dir: Path,
    *,
    mode: Literal["exclusive", "shared"] = "exclusive",
    blocking: bool = False,
) -> AsyncIterator[bool]:
    """Convenience function for acquiring file locks.

    Args:
        resource_id: Unique identifier for the resource to lock
        lock_dir: Directory for storing lock files
        mode: Lock mode - "exclusive" for write, "shared" for read
        blocking: Must be False (see :meth:`FileLock.acquire`)

    Yields:
        True if lock acquired successfully, False if already locked

    Example:
        >>> async with acquire_file_lock("msg-123", Path("/tmp/locks")) as locked:
        ...     if locked:
        ...         # Process message
        ...         pass
    """
    lock = FileLock(lock_dir)
    async with lock.acquire(resource_id, mode=mode, blocking=blocking) as acquired:
        yield acquired
