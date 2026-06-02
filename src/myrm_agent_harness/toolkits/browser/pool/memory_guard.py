"""Memory guard for browser pool.

[INPUT]
- asyncio (POS: Python async programming)
- logging::getLogger (POS: Python logging)
- psutil (POS: Python system monitoring)
- .config::MemoryGuardConfig (POS: memory guard config)

[OUTPUT]
- MemoryGuard: memory monitor

[POS]
Memory monitoring module. Checks system memory usage at configured intervals; rejects new Page on the acquire_page path when usage exceeds threshold.
"""

from __future__ import annotations

import asyncio
import logging

try:
    import psutil
except (ImportError, TypeError):
    psutil = None

from .config import MemoryGuardConfig

_logger = logging.getLogger(__name__)


class MemoryGuard:
    """Memory monitor."""

    def __init__(self, config: MemoryGuardConfig) -> None:
        self._enabled = config.enabled and psutil is not None
        self._max_percent = config.max_memory_percent
        self._check_interval = config.check_interval
        self._last_check_time = 0.0
        self._last_memory_percent = 0.0

        if config.enabled and psutil is None:
            _logger.warning("Memory guard enabled but psutil not installed. Install via: uv sync --all-extras")

    async def check_memory(self) -> None:
        """Check memory usage (raises MemoryError if above threshold)."""
        if not self._enabled:
            return

        loop = asyncio.get_event_loop()
        now = loop.time()

        if now - self._last_check_time < self._check_interval:
            if self._last_memory_percent > self._max_percent:
                msg = f"Memory usage {self._last_memory_percent:.1f}% exceeds threshold {self._max_percent}%"
                raise MemoryError(msg)
            return

        memory_percent = psutil.virtual_memory().percent
        self._last_check_time = now
        self._last_memory_percent = memory_percent

        if memory_percent > self._max_percent:
            _logger.error(
                "Memory usage exceeds threshold",
                extra={"memory_percent": memory_percent, "threshold_percent": self._max_percent},
            )
            msg = f"Memory usage {memory_percent:.1f}% exceeds threshold {self._max_percent}%"
            raise MemoryError(msg)
