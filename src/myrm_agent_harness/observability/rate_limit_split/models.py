"""[INPUT] Rate limit and failure event attributes.
[OUTPUT] Immutable data structures for split rate limit metrics and event payloads.
[POS] myrm_agent_harness.observability.rate_limit_split.models

Defines the core data models for splitting 429 rate limit events into local (myrm)
vs remote (upstream) sources, and attributing failure causes to specific model providers
while keeping unlabelled totals invariant for metric consistency.
"""

from dataclasses import dataclass, field
from enum import Enum
import time


class RateLimitSource(str, Enum):
    """Origin of a 429 rate limit rejection."""

    MYRM = "myrm"
    UPSTREAM = "upstream"


RATE_LIMIT_SOURCES: tuple[str, str] = (RateLimitSource.MYRM.value, RateLimitSource.UPSTREAM.value)
DEFAULT_UNKNOWN_PROVIDER: str = "unknown"
DEFAULT_UNKNOWN_MODEL: str = "unknown"


@dataclass(frozen=True)
class RateLimitEvent:
    """Detailed record of a single rate limit rejection."""

    source: RateLimitSource
    provider: str
    model: str
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    reason: str = ""

    def to_dict(self) -> dict[str, str | int]:
        """Convert to JSON-serializable dictionary."""
        return {
            "source": self.source.value,
            "provider": self.provider,
            "model": self.model,
            "timestamp_ms": self.timestamp_ms,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class FailureEvent:
    """Detailed record of a non-429 provider request failure."""

    provider: str
    model: str
    error_code: str
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    reason: str = ""

    def to_dict(self) -> dict[str, str | int]:
        """Convert to JSON-serializable dictionary."""
        return {
            "provider": self.provider,
            "model": self.model,
            "error_code": self.error_code,
            "timestamp_ms": self.timestamp_ms,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RateLimitMetricsSnapshot:
    """Snapshot of rate limit and failure attribution metrics.

    Guarantees:
    1. Unlabelled totals (total_rate_limited, total_failed) remain invariant and monotonic.
    2. Split mappings contain pre-seeded default buckets to prevent Prometheus vector drop.
    3. totals_consistent confirms sum(rate_limited_by_source) == total_rate_limited.
    """

    total_requests: int
    total_completed: int
    total_rate_limited: int
    rate_limited_by_source: dict[str, int]
    total_failed: int
    failed_by_provider: dict[str, int]
    recent_rate_limit_events: tuple[RateLimitEvent, ...] = field(default_factory=tuple)
    recent_failure_events: tuple[FailureEvent, ...] = field(default_factory=tuple)
    totals_consistent: bool = True

    def to_dict(self) -> dict[str, int | bool | dict[str, int] | list[dict[str, str | int]]]:
        """Serialize the snapshot to a dictionary."""
        return {
            "total_requests": self.total_requests,
            "total_completed": self.total_completed,
            "total_rate_limited": self.total_rate_limited,
            "rate_limited_by_source": dict(self.rate_limited_by_source),
            "total_failed": self.total_failed,
            "failed_by_provider": dict(self.failed_by_provider),
            "totals_consistent": self.totals_consistent,
            "recent_rate_limit_events": [e.to_dict() for e in self.recent_rate_limit_events],
            "recent_failure_events": [e.to_dict() for e in self.recent_failure_events],
        }
