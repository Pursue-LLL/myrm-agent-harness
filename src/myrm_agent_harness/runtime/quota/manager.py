"""Storage quota manager with auto-cleanup and optional load-aware scheduling.

Implements StorageQuotaChecker protocol with:
- Per-session storage tracking
- Auto-cleanup when approaching quota (80% threshold)
- Oldest-first file removal strategy (by modification time)
- Optional MaintenanceScheduler integration to defer cleanup under high load

[INPUT]
- runtime.maintenance.protocols::CapacityDenial, (POS: Maintenance scheduling protocols and data types.)

[OUTPUT]
- SimpleStorageQuotaManager: Storage quota manager with session-level tracking.

[POS]
Storage quota manager with auto-cleanup and optional load-aware scheduling.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from myrm_agent_harness.runtime.maintenance.protocols import (
    CapacityDenial,
    MaintenanceScheduler,
    MaintenanceTaskType,
)

from .protocols import StorageQuotaChecker

logger = logging.getLogger(__name__)


class SimpleStorageQuotaManager(StorageQuotaChecker):
    """Storage quota manager with session-level tracking.

    Features:
    - Per-session quota limits (default: 500MB)
    - Auto-cleanup when reaching 80% threshold
    - Oldest-first file removal (by modification time)
    - Thread-safe with asyncio locks
    - Optional load-aware cleanup: defers auto-cleanup when system is busy
    """

    def __init__(
        self,
        per_session_limit: int = 500 * 1024 * 1024,
        auto_cleanup_threshold: float = 0.8,
        context_root: str = "/persistent/.context",
        scheduler: MaintenanceScheduler | None = None,
    ) -> None:
        self._per_session_limit = per_session_limit
        self._auto_cleanup_threshold = auto_cleanup_threshold
        self._context_root = Path(context_root)
        self._usage_cache: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._scheduler = scheduler
        logger.info(
            "StorageQuotaManager initialized: per_session=%.1fMB, cleanup_threshold=%.0f%%",
            per_session_limit / (1024 * 1024),
            auto_cleanup_threshold * 100,
        )

    async def check_write_allowed(
        self,
        session_id: str,
        write_size_bytes: int,
    ) -> bool:
        """Check if write is allowed within quota limits.

        If approaching quota (>80%), automatically triggers cleanup.

        Args:
            session_id: Session identifier
            write_size_bytes: Size of content to write

        Returns:
            True if write allowed, False if would exceed quota
        """
        async with self._lock:
            current_usage = await self._get_session_usage(session_id)
            new_usage = current_usage + write_size_bytes

            # Check if would exceed quota
            if new_usage > self._per_session_limit:
                logger.warning(
                    "Write rejected: session=%s, current=%.1fMB, write=%.1fMB, limit=%.1fMB",
                    session_id,
                    current_usage / (1024 * 1024),
                    write_size_bytes / (1024 * 1024),
                    self._per_session_limit / (1024 * 1024),
                )
                return False

            usage_ratio = new_usage / self._per_session_limit
            if usage_ratio >= self._auto_cleanup_threshold:
                await self._try_auto_cleanup(session_id, usage_ratio)

            # Update cache
            self._usage_cache[session_id] = new_usage
            return True

    async def get_remaining_quota(self, session_id: str) -> int:
        """Get remaining storage quota in bytes.

        Args:
            session_id: Session identifier

        Returns:
            Remaining quota in bytes
        """
        current_usage = await self._get_session_usage(session_id)
        return max(0, self._per_session_limit - current_usage)

    async def _get_session_usage(self, session_id: str) -> int:
        """Calculate current storage usage for a session.

        Args:
            session_id: Session identifier

        Returns:
            Total storage usage in bytes
        """
        # Check cache first
        if session_id in self._usage_cache:
            return self._usage_cache[session_id]

        # Calculate from filesystem
        session_dir = self._context_root / session_id
        if not session_dir.exists():
            return 0

        total_size = 0
        for subdir in ["compacted", "scratchpad"]:
            subdir_path = session_dir / subdir
            if not subdir_path.exists():
                continue

            for file_path in subdir_path.iterdir():
                if file_path.is_file():
                    try:
                        total_size += file_path.stat().st_size
                    except (OSError, PermissionError):
                        continue

        self._usage_cache[session_id] = total_size
        return total_size

    async def _try_auto_cleanup(self, session_id: str, usage_ratio: float) -> None:
        """Attempt auto-cleanup, respecting the global scheduler if available.

        If a scheduler is configured, requests capacity first. If denied (system busy),
        cleanup is deferred — the write is still allowed, but cleanup will happen later
        when load drops. This prevents cleanup I/O from degrading user-facing latency.
        """
        if self._scheduler:
            result = await self._scheduler.request_capacity(MaintenanceTaskType.STORAGE_CLEANUP)
            if isinstance(result, CapacityDenial):
                logger.info(
                    "Auto-cleanup deferred for session=%s (%.1f%%): %s",
                    session_id,
                    usage_ratio * 100,
                    result.reason,
                )
                return
            try:
                cleaned = await self._auto_cleanup_session(session_id, target_ratio=0.6)
                logger.info("Auto-cleanup completed: session=%s removed=%d files", session_id, cleaned)
            finally:
                await self._scheduler.release_capacity(result)
        else:
            cleaned = await self._auto_cleanup_session(session_id, target_ratio=0.6)
            logger.info("Auto-cleanup completed: session=%s removed=%d files", session_id, cleaned)

    async def _auto_cleanup_session(
        self,
        session_id: str,
        target_ratio: float = 0.6,
    ) -> int:
        """Auto-cleanup session files using oldest-first strategy.

        Removes oldest files (by modification time) until usage drops below target ratio.

        Args:
            session_id: Session identifier
            target_ratio: Target usage ratio after cleanup (default: 0.6 = 60%)

        Returns:
            Number of files removed
        """
        session_dir = self._context_root / session_id
        if not session_dir.exists():
            return 0

        # Collect all files with access times
        files_with_mtime: list[tuple[Path, float]] = []
        for subdir in ["compacted", "scratchpad"]:
            subdir_path = session_dir / subdir
            if not subdir_path.exists():
                continue

            for file_path in subdir_path.iterdir():
                if file_path.is_file():
                    try:
                        stat = file_path.stat()
                        files_with_mtime.append((file_path, stat.st_mtime))
                    except (OSError, PermissionError):
                        continue

        # Sort by mtime (oldest first)
        files_with_mtime.sort(key=lambda x: x[1])

        # Remove files until target ratio reached
        target_usage = int(self._per_session_limit * target_ratio)
        current_usage = await self._get_session_usage(session_id)
        removed_count = 0

        for file_path, _ in files_with_mtime:
            if current_usage <= target_usage:
                break

            try:
                file_size = file_path.stat().st_size
                file_path.unlink()
                current_usage -= file_size
                removed_count += 1
                logger.debug("Auto-cleanup: removed %s", file_path)
            except (OSError, PermissionError):
                continue

        # Update cache
        self._usage_cache[session_id] = current_usage
        return removed_count

    def invalidate_cache(self, session_id: str | None = None) -> None:
        """Invalidate usage cache.

        Args:
            session_id: Specific session to invalidate, or None for all
        """
        if session_id:
            self._usage_cache.pop(session_id, None)
        else:
            self._usage_cache.clear()
