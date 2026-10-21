"""Desktop memory watchdog with multi-level idle compaction.

Monitors desktop process resident set size (RSS), detects user idle periods,
and coordinates soft multi-level garbage collection and cache trimming to
prevent memory bloat in multi-day desktop agent sessions.

[OUTPUT]
- DesktopMemoryWatchdog: Cross-platform RSS monitoring and idle memory compaction.
- get_current_rss_bytes: Utility returning current process RSS in bytes.

[INPUT]
- __future__
- asyncio
- gc
- resource
- sys
- time

[OUTPUT]
- get_current_rss_bytes
- DesktopMemoryWatchdog

[POS]
Desktop memory watchdog with multi-level idle compaction.
"""

from __future__ import annotations

import asyncio
import gc
import resource
import sys
import time

from myrm_agent_harness.runtime.survival.desktop_watchdog_types import (
    MemoryAlertLevel,
    MemoryCompactionReceipt,
)
from myrm_agent_harness.runtime.survival.session_dehydration import (
    SessionContextDehydrator,
)

_DEFAULT_WARNING_RSS: int = 1200 * 1024 * 1024  # 1.2 GB
_DEFAULT_CRITICAL_RSS: int = 1800 * 1024 * 1024  # 1.8 GB
_DEFAULT_EMERGENCY_RSS: int = 2500 * 1024 * 1024  # 2.5 GB


def get_current_rss_bytes() -> int:
    """Return physical resident set size (RSS) of current process in bytes."""
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except Exception:
        pass

    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # macOS reports in bytes; Linux reports in kilobytes
    if sys.platform == "darwin":
        return int(usage)
    return int(usage * 1024)


class DesktopMemoryWatchdog:
    """Monitors desktop RSS watermark and triggers soft idle compaction."""

    def __init__(
        self,
        dehydrator: SessionContextDehydrator | None = None,
        *,
        warning_rss_bytes: int = _DEFAULT_WARNING_RSS,
        critical_rss_bytes: int = _DEFAULT_CRITICAL_RSS,
        emergency_rss_bytes: int = _DEFAULT_EMERGENCY_RSS,
        idle_threshold_seconds: float = 60.0,
    ) -> None:
        self.dehydrator: SessionContextDehydrator = (
            dehydrator or SessionContextDehydrator()
        )
        self.warning_rss_bytes: int = warning_rss_bytes
        self.critical_rss_bytes: int = critical_rss_bytes
        self.emergency_rss_bytes: int = emergency_rss_bytes
        self.idle_threshold_seconds: float = max(0.001, idle_threshold_seconds)

        self._last_user_activity_ts: float = time.time()
        self._lock: asyncio.Lock = asyncio.Lock()

    @property
    def last_activity_timestamp(self) -> float:
        """Return the timestamp of the latest recorded user interaction."""
        return self._last_user_activity_ts

    def mark_user_activity(self, timestamp: float | None = None) -> None:
        """Record an inbound user event to reset the idle timer."""
        self._last_user_activity_ts = (
            timestamp if timestamp is not None else time.time()
        )

    def is_idle(self, now: float | None = None) -> bool:
        """Return True if no user activity occurred within idle_threshold_seconds."""
        current_time = now if now is not None else time.time()
        return (current_time - self._last_user_activity_ts) >= self.idle_threshold_seconds

    def evaluate_memory_pressure(
        self, current_rss: int | None = None
    ) -> MemoryAlertLevel:
        """Classify current process RSS into 4-tier pressure levels."""
        rss = current_rss if current_rss is not None else get_current_rss_bytes()
        if rss >= self.emergency_rss_bytes:
            return "EMERGENCY"
        if rss >= self.critical_rss_bytes:
            return "CRITICAL"
        if rss >= self.warning_rss_bytes:
            return "WARNING"
        return "NORMAL"

    async def trigger_compaction(
        self,
        level: MemoryAlertLevel | None = None,
        *,
        force: bool = False,
        simulated_pre_rss: int | None = None,
        simulated_post_rss: int | None = None,
    ) -> MemoryCompactionReceipt:
        """Execute memory trimming, raw cache eviction, and garbage collection.

        If force=False and level=WARNING, compaction is postponed until is_idle() is True.
        """
        async with self._lock:
            pre_rss = (
                simulated_pre_rss
                if simulated_pre_rss is not None
                else get_current_rss_bytes()
            )
            resolved_level = level or self.evaluate_memory_pressure(pre_rss)

            # Suppress WARNING compaction if user is currently active and not forced
            if resolved_level == "WARNING" and not force and not self.is_idle():
                return MemoryCompactionReceipt(
                    level=resolved_level,
                    pre_rss_bytes=pre_rss,
                    post_rss_bytes=pre_rss,
                    freed_bytes=0,
                    dehydrated_turns_count=0,
                )

            # 1. Evict backing raw turn cache in dehydrator
            cleared_turns = await self.dehydrator.clear_cache()

            # 2. Trigger generational garbage collection
            gc.collect()

            # 3. Best-effort malloc_trim on Linux glibc
            if sys.platform.startswith("linux"):
                try:
                    import ctypes

                    ctypes.CDLL("libc.so.6").malloc_trim(0)
                except Exception:
                    pass

            post_rss = (
                simulated_post_rss
                if simulated_post_rss is not None
                else get_current_rss_bytes()
            )
            freed = max(0, pre_rss - post_rss)

            return MemoryCompactionReceipt(
                level=resolved_level,
                pre_rss_bytes=pre_rss,
                post_rss_bytes=post_rss,
                freed_bytes=freed,
                dehydrated_turns_count=cleared_turns,
            )
