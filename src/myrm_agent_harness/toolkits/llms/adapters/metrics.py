"""Empty Retry Metrics for ChatLiteLLM.


[INPUT]
- dataclasses::dataclass (POS: Python standard library dataclass)

[OUTPUT]
- EmptyRetryMetrics: empty response retry metrics class

[POS]
Empty response retry metrics. Tracks retry count, success count, and total delay for
Sync/Async/Stream modes. Provides instance-level observability data; business layer can
export via .to_dict() for monitoring integration. Follows FRAMEWORK_DESIGN_PRINCIPLES.md
monitoring strategy: framework provides data structures, business layer decides export method.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class EmptyRetryMetrics:
    """Empty response retry metrics (instance-level).

    Tracks retry attempts, successes, and delays for sync/async/stream modes.
    Follows framework monitoring strategy: provide data structure, business layer
    decides export method (Prometheus/logs/API).
    """

    # Retry counts by mode
    sync_retry_count: int = 0
    async_retry_count: int = 0
    stream_retry_count: int = 0

    # Success after retry counts
    sync_success_after_retry: int = 0
    async_success_after_retry: int = 0
    stream_success_after_retry: int = 0

    # Total retry delay
    total_retry_delay_ms: float = 0.0

    def to_dict(self) -> dict[str, float]:
        """Export metrics as dict for business layer."""
        return asdict(self)

    def get_total_retries(self) -> int:
        """Get total retry count across all modes."""
        return self.sync_retry_count + self.async_retry_count + self.stream_retry_count

    def get_total_successes(self) -> int:
        """Get total success count after retries."""
        return self.sync_success_after_retry + self.async_success_after_retry + self.stream_success_after_retry

    def get_success_rate(self) -> float:
        """Calculate overall success rate after retry (0.0-1.0)."""
        total = self.get_total_retries()
        if total == 0:
            return 0.0
        return self.get_total_successes() / total

    def get_avg_retry_delay_ms(self) -> float:
        """Calculate average retry delay in milliseconds."""
        total = self.get_total_retries()
        if total == 0:
            return 0.0
        return self.total_retry_delay_ms / total
