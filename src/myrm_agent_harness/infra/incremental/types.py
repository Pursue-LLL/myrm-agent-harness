"""Domain types for incremental monitoring.

Pure data definitions — no I/O, safe to import anywhere.

[INPUT]
- (none)

[OUTPUT]
- MonitorConfig: Configuration for incremental monitoring.
- MonitorState: Persistent state for a single monitor instance.

[POS]
Domain types for incremental monitoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

MonitorType = Literal["set", "hash"]
ResetReason = Literal["manual", "command_change", "prompt_change", "monitor_type_change", "ttl_expired"]


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    """Configuration for incremental monitoring.

    ``monitor_type`` determines which monitor implementation to use:
    - "set": SetMonitor (line-delimited items, set difference)
    - "hash": HashMonitor (content hash comparison)

    ``ttl_days`` controls automatic cleanup of old baseline data.
    After this many days, the baseline is reset to prevent unbounded growth.
    """

    monitor_type: MonitorType = "set"
    ttl_days: int = 30
    enabled: bool = True


@dataclass(slots=True)
class MonitorState:
    """Persistent state for a single monitor instance.

    ``data`` contains monitor-specific state:
    - SetMonitor: {"seen": ["url1", "url2", ...]}
    - HashMonitor: {"last_hash": "abc123"}

    ``updated_at`` is used for TTL expiration checks.
    ``failure_count`` tracks consecutive monitoring failures for alerting.
    ``last_reset_at`` and ``last_reset_reason`` track baseline reset history for user visibility.
    """

    job_id: str
    monitor_type: MonitorType
    data: dict[str, object]
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    ttl_days: int = 30
    failure_count: int = 0
    last_failure_at: datetime | None = None
    last_reset_at: datetime | None = None
    last_reset_reason: ResetReason | None = None

    def is_expired(self) -> bool:
        """Check if this state has exceeded its TTL."""
        age_days = (datetime.now(UTC) - self.updated_at).days
        return age_days > self.ttl_days

    def should_alert_failure(self, threshold: int = 3) -> bool:
        """Check if consecutive failures exceed alert threshold."""
        return self.failure_count >= threshold
