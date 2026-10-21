"""[INPUT] Rate limit events, failure signals, and completed request notices.
[OUTPUT] In-memory thread-safe metrics tracker with split source and provider attributions.
[POS] myrm_agent_harness.observability.rate_limit_split.tracker

Thread-safe tracker that manages unlabelled request counters and partitioned rate limit /
failure dictionaries. Pre-seeds zero values to avoid empty series vectors in monitoring.
"""

from collections import deque
import threading

from .models import (
    DEFAULT_UNKNOWN_MODEL,
    DEFAULT_UNKNOWN_PROVIDER,
    FailureEvent,
    RateLimitEvent,
    RateLimitMetricsSnapshot,
    RateLimitSource,
)


class RateLimitSplitTracker:
    """Thread-safe collector for rate limits and provider failures.

    Maintains total unlabelled counters to prevent metric drift, while partitioning
    429 events into 'myrm' vs 'upstream' and request failures by provider identifier.
    """

    def __init__(self, max_recent_events: int = 100) -> None:
        """Initialize counters and seeded category maps."""
        self._lock = threading.Lock()
        self._max_recent_events = max(10, max_recent_events)

        self._total_requests: int = 0
        self._total_completed: int = 0
        self._total_rate_limited: int = 0
        self._rate_limited_by_source: dict[str, int] = {
            RateLimitSource.MYRM.value: 0,
            RateLimitSource.UPSTREAM.value: 0,
        }
        self._total_failed: int = 0
        self._failed_by_provider: dict[str, int] = {
            DEFAULT_UNKNOWN_PROVIDER: 0,
        }
        self._recent_rate_limit_events: deque[RateLimitEvent] = deque(maxlen=self._max_recent_events)
        self._recent_failure_events: deque[FailureEvent] = deque(maxlen=self._max_recent_events)

    def record_completed(self, provider: str | None = None, model: str | None = None) -> None:
        """Record a completed, non-rate-limited and non-failed request."""
        _ = (provider, model)
        with self._lock:
            self._total_requests += 1
            self._total_completed += 1

    def record_rate_limit(
        self,
        source: RateLimitSource | str,
        provider: str | None = None,
        model: str | None = None,
        reason: str | None = None,
    ) -> RateLimitEvent:
        """Record a 429 rate limit occurrence.

        Splits between internal governor ('myrm') and external provider ('upstream').
        The unlabelled total is incremented synchronously.
        """
        source_enum: RateLimitSource
        if isinstance(source, RateLimitSource):
            source_enum = source
        else:
            normalized = source.strip().lower()
            if normalized in (RateLimitSource.MYRM.value, "internal", "local", "governor"):
                source_enum = RateLimitSource.MYRM
            else:
                source_enum = RateLimitSource.UPSTREAM

        resolved_provider = provider.strip() if provider and provider.strip() else DEFAULT_UNKNOWN_PROVIDER
        resolved_model = model.strip() if model and model.strip() else DEFAULT_UNKNOWN_MODEL
        resolved_reason = reason.strip() if reason and reason.strip() else ""

        event = RateLimitEvent(
            source=source_enum,
            provider=resolved_provider,
            model=resolved_model,
            reason=resolved_reason,
        )

        with self._lock:
            self._total_requests += 1
            self._total_rate_limited += 1
            key = source_enum.value
            self._rate_limited_by_source[key] = self._rate_limited_by_source.get(key, 0) + 1
            self._recent_rate_limit_events.append(event)

        return event

    def record_failure(
        self,
        provider: str | None = None,
        model: str | None = None,
        error_code: str | None = None,
        reason: str | None = None,
    ) -> FailureEvent:
        """Record an upstream API call failure (non-429).

        Attributes failure counts to the specific provider name while preserving
        the unlabelled total_failed counter.
        """
        resolved_provider = provider.strip() if provider and provider.strip() else DEFAULT_UNKNOWN_PROVIDER
        resolved_model = model.strip() if model and model.strip() else DEFAULT_UNKNOWN_MODEL
        resolved_code = error_code.strip() if error_code and error_code.strip() else "API_ERROR"
        resolved_reason = reason.strip() if reason and reason.strip() else ""

        event = FailureEvent(
            provider=resolved_provider,
            model=resolved_model,
            error_code=resolved_code,
            reason=resolved_reason,
        )

        with self._lock:
            self._total_requests += 1
            self._total_failed += 1
            self._failed_by_provider[resolved_provider] = self._failed_by_provider.get(resolved_provider, 0) + 1
            self._recent_failure_events.append(event)

        return event

    def get_snapshot(self) -> RateLimitMetricsSnapshot:
        """Produce an immutable snapshot of current counters and recent events."""
        with self._lock:
            split_sum = sum(self._rate_limited_by_source.values())
            consistent = split_sum == self._total_rate_limited

            return RateLimitMetricsSnapshot(
                total_requests=self._total_requests,
                total_completed=self._total_completed,
                total_rate_limited=self._total_rate_limited,
                rate_limited_by_source=dict(self._rate_limited_by_source),
                total_failed=self._total_failed,
                failed_by_provider=dict(self._failed_by_provider),
                recent_rate_limit_events=tuple(self._recent_rate_limit_events),
                recent_failure_events=tuple(self._recent_failure_events),
                totals_consistent=consistent,
            )

    def reset(self) -> None:
        """Reset counters while preserving pre-seeded zero buckets."""
        with self._lock:
            self._total_requests = 0
            self._total_completed = 0
            self._total_rate_limited = 0
            self._rate_limited_by_source = {
                RateLimitSource.MYRM.value: 0,
                RateLimitSource.UPSTREAM.value: 0,
            }
            self._total_failed = 0
            self._failed_by_provider = {
                DEFAULT_UNKNOWN_PROVIDER: 0,
            }
            self._recent_rate_limit_events.clear()
            self._recent_failure_events.clear()


# Default process-level singleton instance for runtime and API consumers
_default_tracker: RateLimitSplitTracker | None = None
_tracker_init_lock = threading.Lock()


def get_default_rate_limit_tracker() -> RateLimitSplitTracker:
    """Obtain or initialize the global default RateLimitSplitTracker."""
    global _default_tracker
    if _default_tracker is None:
        with _tracker_init_lock:
            if _default_tracker is None:
                _default_tracker = RateLimitSplitTracker()
    return _default_tracker
