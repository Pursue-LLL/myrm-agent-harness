"""Background task: periodically clean up orphaned context files.

Prevents storage leaks by scanning and removing expired .context directories.

Directory structure:
- sandboxes_root/                            (parent of all workspaces)
  └── user_{user_id}_chat_{chat_id}/        (single workspace)
      └── .context/                          (context root)
          └── {chat_id}/                     (session context)
              └── compacted_*.txt            (offloaded files)

Schedule:
- Runs immediately on start
- Repeats every interval (default: 24 hours)
- Stops gracefully on shutdown

[INPUT]
- (none)

[OUTPUT]
- ContextCleanupScheduler: Manages periodic cleanup of orphaned context files.

[POS]
Background task: periodically clean up orphaned context files.
"""

import asyncio
import contextlib
import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ContextCleanupScheduler:
    """Manages periodic cleanup of orphaned context files.

    Encapsulates the cleanup loop lifecycle without global state,
    making it testable and reusable.

    Usage:
        scheduler = ContextCleanupScheduler(sandboxes_root)
        scheduler.start()
        # ... later ...
        await scheduler.stop()
    """

    def __init__(
        self,
        sandboxes_root: str | Path,
        interval_hours: int = 24,
        max_age_days: int = 7,
    ) -> None:
        self._sandboxes_root = Path(sandboxes_root)
        self._interval_hours = interval_hours
        self._max_age_days = max_age_days
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event = asyncio.Event()

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        """Start the background cleanup task.

        No-op if already running.
        """
        if self.is_running:
            logger.warning("Context cleanup task already running")
            return

        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop())
        logger.info("Context cleanup task created")

    async def stop(self, timeout: float = 5.0) -> None:
        """Stop the background cleanup task gracefully.

        Args:
            timeout: Maximum seconds to wait for graceful shutdown
        """
        self._stop_event.set()

        if self._task is not None and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
                logger.info("Context cleanup task stopped gracefully")
            except TimeoutError:
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task
                logger.warning("Context cleanup task cancelled (timeout)")
        else:
            logger.debug("Context cleanup task not running")

        self._task = None

    async def _loop(self) -> None:
        """Cleanup loop: run immediately, then repeat at interval."""
        logger.info(
            "Context cleanup task started (interval: %dh, max_age: %dd)",
            self._interval_hours,
            self._max_age_days,
        )

        await self._run_cleanup()

        interval_seconds = self._interval_hours * 3600

        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval_seconds)
                break
            except TimeoutError:
                await self._run_cleanup()

        logger.info("Context cleanup task stopped")

    async def _run_cleanup(self) -> None:
        """Execute one cleanup pass over all workspace context directories."""
        if not self._sandboxes_root.exists():
            logger.debug("Sandboxes root not found: %s", self._sandboxes_root)
            return

        cleaned_count = 0
        max_age_seconds = self._max_age_days * 86400

        try:
            for user_dir in self._sandboxes_root.iterdir():
                if not user_dir.is_dir():
                    continue

                for session_dir in user_dir.iterdir():
                    if not session_dir.is_dir():
                        continue

                    context_dir = session_dir / ".context"
                    if not context_dir.exists():
                        continue

                    for chat_context_dir in context_dir.iterdir():
                        if not chat_context_dir.is_dir():
                            continue

                        try:
                            mtime = chat_context_dir.stat().st_mtime
                            age_seconds = time.time() - mtime
                            age_days = age_seconds / 86400

                            if age_seconds > max_age_seconds:
                                shutil.rmtree(chat_context_dir)
                                cleaned_count += 1
                                logger.info(
                                    "CONTEXT_CLEANUP_ORPHAN path=%s age_days=%.1f",
                                    chat_context_dir.relative_to(self._sandboxes_root),
                                    age_days,
                                )
                        except Exception as exc:
                            logger.warning("Failed to cleanup %s: %s", chat_context_dir, exc)

            if cleaned_count > 0:
                logger.info("Context cleanup completed: %d sessions cleaned", cleaned_count)
            else:
                logger.debug("Context cleanup: no orphaned files found")

        except Exception as exc:
            logger.error("Context cleanup failed: %s", exc)
