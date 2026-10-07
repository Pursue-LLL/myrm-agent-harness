"""Types and schemas for peak/off-peak cost-aware batch task scheduling.

[INPUT]
Task urgency definitions, provider tariff time-window specifications, and pending batch task descriptors.

[OUTPUT]
Type-safe dispatch decisions, queue telemetry summaries, and cost-saving metrics.

[POS]
Item 122 in topic_06 roadmap: harnesses 1/60 cost dividend during provider off-peak windows.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class CostTimeWindowKind(StrEnum):
    """Cost tier window classification for LLM provider billing."""
    PEAK = "peak"
    OFF_PEAK = "off_peak"
    STANDARD = "standard"


class TaskCostUrgencyPolicy(StrEnum):
    """Urgency policy governing how strictly a task seeks off-peak pricing discounts."""
    REALTIME_INTERACTIVE = "realtime_interactive"  # Execute immediately regardless of window
    NEAR_REALTIME = "near_realtime"                # Allow minute-level buffering
    OFF_PEAK_OPPORTUNISTIC = "off_peak_opportunistic"  # Defer execution until off-peak window


class TaskPayloadKind(StrEnum):
    """Domain categorization for background batch workloads."""
    WIKI_STALE_ARCHIVE = "wiki_stale_archive"
    MEMORY_CRYSTALLIZATION = "memory_crystallization"
    EVAL_RUN = "eval_run"
    OFFLINE_BATCH = "offline_batch"


@dataclass(frozen=True)
class ProviderTimeWindowRule:
    """Tariff time window specification for an LLM provider."""
    provider_id: str
    off_peak_start_minute_utc: int  # Minute of the day (0..1439) in UTC
    off_peak_end_minute_utc: int    # Minute of the day (0..1439) in UTC
    peak_uncached_price_per_m: float
    off_peak_cached_price_per_m: float
    description: str = ""

    @property
    def max_savings_multiplier(self) -> float:
        """Maximum possible cost reduction ratio between peak uncached and off-peak cached."""
        if self.off_peak_cached_price_per_m <= 0:
            return 1.0
        return self.peak_uncached_price_per_m / self.off_peak_cached_price_per_m


@dataclass(frozen=True)
class BatchTaskDescriptor:
    """Descriptor of a task submitted to the cost-aware scheduler."""
    task_id: str
    payload_kind: TaskPayloadKind
    urgency_policy: TaskCostUrgencyPolicy
    target_provider: str = "deepseek"
    estimated_tokens: int = 100_000
    created_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class SchedulerDispatchDecision:
    """Decision indicating whether to execute immediately or defer until an off-peak window."""
    task_id: str
    should_execute_now: bool
    current_window: CostTimeWindowKind
    delay_seconds: int
    reason: str
    savings_multiplier_estimate: float
    evaluated_at_utc: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )


@dataclass(frozen=True)
class SchedulerQueueMetrics:
    """Telemetry rollup of the cost scheduler queue."""
    queued_task_count: int
    deferred_token_count: int
    current_window: CostTimeWindowKind
    estimated_saved_cost_usd_or_cny: float
