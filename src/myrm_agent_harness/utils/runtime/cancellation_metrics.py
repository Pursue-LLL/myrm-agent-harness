"""Cancellation metrics data structures.

Provides monitoring data structures for client disconnect detection and cancellation operations.
Business layer can use these metrics for monitoring and alerting.

Design principle: Framework provides data structure, business layer decides monitoring solution.

[INPUT]
- (none)

[OUTPUT]
- CancellationMetrics: Client disconnect detection and cancellation metrics.

[POS]
Cancellation metrics data structures.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CancellationMetrics:
    """Client disconnect detection and cancellation metrics.

    Tracks disconnect detection operations for monitoring and optimization.
    """

    # Detection operations
    check_count: int = 0
    """Total number of disconnect checks performed"""

    disconnect_detected_count: int = 0
    """Number of times client disconnect was detected"""

    check_total_ms: float = 0.0
    """Total time spent checking disconnect status (milliseconds)"""

    max_check_ms: float = 0.0
    """Maximum single check duration (milliseconds)"""

    # Cancellation operations
    cancel_triggered_count: int = 0
    """Number of times cancellation was triggered"""

    cancel_completed_count: int = 0
    """Number of times cancellation completed successfully"""

    # Resource metrics
    active_monitors: int = 0
    """Current number of active cancellation monitors"""

    def to_dict(self) -> dict[str, float | int]:
        """Export metrics for business layer monitoring.

        Returns:
            Dict containing all metrics
        """
        return {
            # Detection metrics
            "check_count": self.check_count,
            "disconnect_detected_count": self.disconnect_detected_count,
            "disconnect_detection_rate": self.disconnect_detection_rate,
            "check_avg_ms": self.check_avg_ms,
            "check_total_ms": self.check_total_ms,
            "max_check_ms": self.max_check_ms,
            # Cancellation metrics
            "cancel_triggered_count": self.cancel_triggered_count,
            "cancel_completed_count": self.cancel_completed_count,
            "cancel_completion_rate": self.cancel_completion_rate,
            # Resource metrics
            "active_monitors": self.active_monitors,
        }

    @property
    def disconnect_detection_rate(self) -> float:
        """Calculate disconnect detection rate (0.0-1.0)."""
        if self.check_count == 0:
            return 0.0
        return self.disconnect_detected_count / self.check_count

    @property
    def check_avg_ms(self) -> float:
        """Calculate average check time in milliseconds."""
        if self.check_count == 0:
            return 0.0
        return self.check_total_ms / self.check_count

    @property
    def cancel_completion_rate(self) -> float:
        """Calculate cancellation completion rate (0.0-1.0)."""
        if self.cancel_triggered_count == 0:
            return 0.0
        return self.cancel_completed_count / self.cancel_triggered_count
