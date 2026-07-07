"""Performance monitor for hybrid retrieval and reranking pipelines.

[INPUT]
- (none)

[OUTPUT]
- PerformanceMonitor: class — Performance Monitor
- get_performance_monitor: function — get_performance_monitor

[POS]
Provides PerformanceMonitor, get_performance_monitor.
"""

import logging
import time
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """Tracks per-operation latency for retrieval pipelines."""

    def __init__(self) -> None:
        self.metrics: dict[str, float] = {}

    @asynccontextmanager
    async def track_operation(self, operation_name: str):
        """Track operation latency via async context manager."""
        start_time = time.perf_counter()
        logger.debug("Begin %s", operation_name)

        try:
            yield
        finally:
            duration = time.perf_counter() - start_time
            self.metrics[operation_name] = duration
            logger.info("%s completed in %.4fs", operation_name, duration)

    def get_performance_summary(self) -> dict[str, Any]:
        """Return a performance summary dict."""
        total_time = sum(self.metrics.values())
        return {
            "total_time": f"{total_time:.4f}s",
            "operations": {k: f"{v:.4f}s" for k, v in self.metrics.items()},
        }

    def log_performance_summary(self) -> None:
        """Log performance summary at INFO level."""
        summary = self.get_performance_summary()
        logger.info(
            "Performance summary: total=%s | %s",
            summary["total_time"],
            ", ".join(f"{k}={v}" for k, v in summary["operations"].items()),
        )


_performance_monitor: PerformanceMonitor | None = None


def get_performance_monitor() -> PerformanceMonitor:
    """Get the global performance monitor singleton."""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor
