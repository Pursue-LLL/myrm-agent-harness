"""StorageProvider可观测性指标

职责：
- 记录StorageProvider操作延迟和错误率
- 提供操作级别的可观测性
- 支持Prometheus导出

[INPUT]

[OUTPUT]
- StorageMetricsCollector: 指标收集器
- 操作延迟histogram
- 错误率counter
- 重试次数counter

[POS]
StorageProvider observability layer. Provides operational metrics needed for monitoring and tuning.

"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .storage_resilience import StorageMetrics

logger = logging.getLogger(__name__)


@dataclass
class OperationStats:
    """操作统计"""

    total_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    total_retries: int = 0
    error_types: dict[str, int] = None

    def __post_init__(self) -> None:
        if self.error_types is None:
            self.error_types = {}


class StorageMetricsCollector:
    """StorageProvider指标收集器

    收集并聚合StorageProvider操作的性能和错误指标。

    核心指标：
    - 操作延迟（read/write/delete/list）
    - 成功率和错误率
    - 重试次数
    - 错误类型分布
    """

    def __init__(self) -> None:
        self._stats: dict[str, OperationStats] = defaultdict(OperationStats)

    def record_operation(self, metrics: StorageMetrics) -> None:
        """记录操作指标"""
        stats = self._stats[metrics.operation]

        stats.total_count += 1
        stats.total_duration_ms += metrics.duration_ms
        stats.total_retries += metrics.retry_count

        if metrics.success:
            stats.success_count += 1
        else:
            stats.failure_count += 1
            if metrics.error_type:
                error_key = metrics.error_type.value
                stats.error_types[error_key] = stats.error_types.get(error_key, 0) + 1

    def get_stats(self) -> dict[str, dict[str, object]]:
        """获取聚合统计信息

        Returns:
            {
                "read": {
                    "total_count": 100,
                    "success_rate": 0.98,
                    "avg_duration_ms": 45.2,
                    "total_retries": 5,
                    "error_types": {"network": 2}
                },
                ...
            }
        """
        result = {}

        for operation, stats in self._stats.items():
            success_rate = stats.success_count / stats.total_count if stats.total_count > 0 else 0.0
            avg_duration = stats.total_duration_ms / stats.total_count if stats.total_count > 0 else 0.0

            result[operation] = {
                "total_count": stats.total_count,
                "success_count": stats.success_count,
                "failure_count": stats.failure_count,
                "success_rate": success_rate,
                "avg_duration_ms": avg_duration,
                "total_retries": stats.total_retries,
                "error_types": dict(stats.error_types),
            }

        return result

    def reset(self) -> None:
        """重置所有指标"""
        self._stats.clear()


class MonitoredStorageCallback:
    """带监控的存储回调

    同时记录日志和收集指标。
    """

    def __init__(self, metrics_collector: StorageMetricsCollector):
        self._collector = metrics_collector

    def on_success(self, metrics: StorageMetrics) -> None:
        self._collector.record_operation(metrics)

        if metrics.duration_ms > 1000:
            logger.warning(
                f"Slow storage operation: {metrics.operation} took {metrics.duration_ms:.0f}ms "
                f"(retries={metrics.retry_count})"
            )

    def on_error(self, metrics: StorageMetrics, error: Exception) -> None:
        self._collector.record_operation(metrics)

        logger.error(
            f"Storage operation failed: {metrics.operation}, "
            f"error_type={metrics.error_type}, duration={metrics.duration_ms:.0f}ms, "
            f"retries={metrics.retry_count}, error={error}"
        )

    def on_retry(self, metrics: StorageMetrics, attempt: int, max_attempts: int) -> None:
        logger.warning(
            f"Retrying storage operation: {metrics.operation} "
            f"(attempt {attempt}/{max_attempts}, error_type={metrics.error_type})"
        )


# 全局指标收集器（单例）
_global_storage_metrics: StorageMetricsCollector | None = None


def get_global_storage_metrics() -> StorageMetricsCollector:
    """获取全局存储指标收集器"""
    global _global_storage_metrics
    if _global_storage_metrics is None:
        _global_storage_metrics = StorageMetricsCollector()
    return _global_storage_metrics
