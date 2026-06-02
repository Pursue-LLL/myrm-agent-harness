"""Filter performance statistics and monitoring.

[INPUT]
- (none)

[OUTPUT]
- FilterStats: Performance statistics for message filters.
- measure_filter_time: Context manager for measuring filter execution time.

[POS]
Filter performance statistics and monitoring.
"""

import logging
import time
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class FilterStats:
    """Performance statistics for message filters.

    Tracks execution time and provides alerting when filters exceed
    performance thresholds.
    """

    threshold_ms: float = 100.0  # Warning threshold
    critical_ms: float = 500.0  # Critical threshold

    # Statistics
    total_calls: int = 0
    total_time_ms: float = 0.0
    slowest_time_ms: float = 0.0
    slowest_filter: str = ""

    # Per-filter stats
    filter_stats: dict[str, dict[str, float]] = field(default_factory=dict)

    def track(self, filter_name: str, elapsed_ms: float) -> None:
        """Track a filter execution.

        Args:
            filter_name: Name of the filter
            elapsed_ms: Execution time in milliseconds
        """
        self.total_calls += 1
        self.total_time_ms += elapsed_ms

        # Update slowest
        if elapsed_ms > self.slowest_time_ms:
            self.slowest_time_ms = elapsed_ms
            self.slowest_filter = filter_name

        # Update per-filter stats
        if filter_name not in self.filter_stats:
            self.filter_stats[filter_name] = {"calls": 0, "total_ms": 0.0, "max_ms": 0.0}

        stats = self.filter_stats[filter_name]
        stats["calls"] += 1
        stats["total_ms"] += elapsed_ms
        stats["max_ms"] = max(stats["max_ms"], elapsed_ms)

        # Check thresholds and alert
        if elapsed_ms > self.critical_ms:
            logger.error(
                "Filter %s critically slow: %.2fms (threshold: %.2fms)",
                filter_name,
                elapsed_ms,
                self.critical_ms,
                extra={"filter": filter_name, "elapsed_ms": elapsed_ms, "severity": "critical"},
            )
        elif elapsed_ms > self.threshold_ms:
            logger.warning(
                "Filter %s slow: %.2fms (threshold: %.2fms)",
                filter_name,
                elapsed_ms,
                self.threshold_ms,
                extra={"filter": filter_name, "elapsed_ms": elapsed_ms, "severity": "warning"},
            )

    def get_average_ms(self) -> float:
        """Get average execution time across all filters.

        Returns:
            Average execution time in milliseconds
        """
        if self.total_calls == 0:
            return 0.0
        return self.total_time_ms / self.total_calls

    def get_filter_average(self, filter_name: str) -> float:
        """Get average execution time for a specific filter.

        Args:
            filter_name: Name of the filter

        Returns:
            Average execution time in milliseconds
        """
        if filter_name not in self.filter_stats:
            return 0.0

        stats = self.filter_stats[filter_name]
        if stats["calls"] == 0:
            return 0.0

        return stats["total_ms"] / stats["calls"]

    def get_summary(self) -> dict[str, object]:
        """Get a summary of all statistics.

        Returns:
            Dictionary containing all stats
        """
        return {
            "total_calls": self.total_calls,
            "total_time_ms": round(self.total_time_ms, 2),
            "average_ms": round(self.get_average_ms(), 2),
            "slowest_time_ms": round(self.slowest_time_ms, 2),
            "slowest_filter": self.slowest_filter,
            "filter_stats": {
                name: {
                    "calls": stats["calls"],
                    "total_ms": round(stats["total_ms"], 2),
                    "average_ms": round(stats["total_ms"] / stats["calls"], 2) if stats["calls"] > 0 else 0.0,
                    "max_ms": round(stats["max_ms"], 2),
                }
                for name, stats in self.filter_stats.items()
            },
        }

    def reset(self) -> None:
        """Reset all statistics."""
        self.total_calls = 0
        self.total_time_ms = 0.0
        self.slowest_time_ms = 0.0
        self.slowest_filter = ""
        self.filter_stats.clear()


def measure_filter_time(filter_name: str, stats: FilterStats | None = None):
    """Context manager for measuring filter execution time.

    Args:
        filter_name: Name of the filter being measured
        stats: Optional FilterStats instance to track to

    Example:
        >>> stats = FilterStats()
        >>> with measure_filter_time("PIIRedactionFilter", stats):
        ...     # Filter logic here
        ...     pass
    """

    class _FilterTimer:
        def __init__(self, name: str, tracker: FilterStats | None):
            self.name = name
            self.tracker = tracker
            self.start_time = 0.0

        def __enter__(self):
            self.start_time = time.perf_counter()
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            elapsed_ms = (time.perf_counter() - self.start_time) * 1000
            if self.tracker:
                self.tracker.track(self.name, elapsed_ms)

    return _FilterTimer(filter_name, stats)
