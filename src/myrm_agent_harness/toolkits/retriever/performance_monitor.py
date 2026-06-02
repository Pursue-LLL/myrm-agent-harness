"""性能监控Tool

 for 监控混合检索 and 重Sort过程 性能Metrics

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

# ConfigureLog
logger = logging.getLogger(__name__)


class PerformanceMonitor:
    """性能监控器"""

    def __init__(self):
        self.metrics = {}
        self.start_time = None

    @asynccontextmanager
    async def track_operation(self, operation_name: str):
        """跟踪操作性能 context manager"""
        start_time = time.time()
        logger.warning(f" BeginExecute {operation_name}")

        try:
            yield
        finally:
            duration = time.time() - start_time
            self.metrics[operation_name] = duration
            logger.warning(f" {operation_name} Complete，耗时: {duration:.4f}秒")

    def get_performance_summary(self) -> dict[str, Any]:
        """Get性能摘要"""
        total_time = sum(self.metrics.values())

        summary = {
            "总耗时": f"{total_time:.4f}秒",
            "操作耗时详情": {k: f"{v:.4f}秒" for k, v in self.metrics.items()},
        }

        return summary

    def log_performance_summary(self):
        """Record性能摘要 to Log"""
        summary = self.get_performance_summary()

        logger.warning("=" * 50)
        logger.warning(" 性能Statistics")
        logger.warning("=" * 50)
        logger.warning(f" 总耗时: {summary['总耗时']}")

        logger.warning(" 操作耗时详情:")
        for op, time_str in summary["操作耗时详情"].items():
            logger.warning(f" - {op}: {time_str}")

        logger.warning("=" * 50)


# Global性能监控Instance
_performance_monitor: PerformanceMonitor | None = None


def get_performance_monitor() -> PerformanceMonitor:
    """GetGlobal性能监控Instance"""
    global _performance_monitor
    if _performance_monitor is None:
        _performance_monitor = PerformanceMonitor()
    return _performance_monitor
