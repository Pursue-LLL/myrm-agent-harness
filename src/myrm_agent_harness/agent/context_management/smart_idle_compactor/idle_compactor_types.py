"""Data contracts and type definitions for smart idle cache auto-compaction.

Enables opportunistic background pre-compaction before provider KV cache TTL expires,
achieving 90% prefill cost savings at 0.1x cache read rates and sub-second wakeup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IdleCompactionAction(str, Enum):
    """Action decision for opportunistic idle compaction."""

    TRIGGER_OPPORTUNISTIC = "trigger_opportunistic"
    SKIP_SESSION_ACTIVE = "skip_session_active"
    SKIP_BELOW_TOKEN_BUDGET = "skip_below_token_budget"
    SKIP_CACHE_ALREADY_EXPIRED = "skip_cache_already_expired"
    SKIP_TOO_EARLY = "skip_too_early"


class CacheWindowStatus(str, Enum):
    """Lifespan state of upstream cloud provider KV Prompt Cache."""

    HOT_FRESH = "hot_fresh"
    OPPORTUNISTIC_EXPIRING_SOON = "opportunistic_expiring_soon"
    EXPIRED_COLD = "expired_cold"


@dataclass(frozen=True)
class IdleCompactorConfig:
    """Operational parameters governing opportunistic background compaction."""

    min_token_threshold: int = 12000
    cache_ttl_seconds: int = 3600  # standard 1-hour cloud prompt cache TTL
    idle_trigger_min_seconds: int = 1800  # 30 minutes of idle inactivity
    idle_trigger_max_seconds: int = 3000  # 50 minutes upper bound before eviction
    cache_hit_rate_multiplier: float = 0.1  # 0.1x rate for warm cache reads
    full_prefill_multiplier: float = 1.0  # 1.0x full price for cold cache reads


@dataclass(frozen=True)
class IdleCompactionEvaluation:
    """Diagnostic evaluation of session idle duration and prompt cache lifespan."""

    session_id: str
    current_tokens: int
    idle_duration_seconds: float
    cache_status: CacheWindowStatus
    action: IdleCompactionAction
    estimated_hot_compaction_cost_units: float
    estimated_cold_compaction_cost_units: float
    potential_savings_ratio: float
    reason: str

    @property
    def should_compact(self) -> bool:
        """Return True if background pre-compaction is recommended."""
        return self.action == IdleCompactionAction.TRIGGER_OPPORTUNISTIC


@dataclass(frozen=True)
class CompactedCheckpointArchive:
    """Durable snapshot preserving deep conversation history in cold storage."""

    archive_id: str
    session_id: str
    original_message_count: int
    original_tokens: int
    compacted_tokens: int
    checkpoint_summary: str
    timestamp_epoch: float


@dataclass(frozen=True)
class OpportunisticCompactionResult:
    """Execution outcome of opportunistic background pre-compaction."""

    session_id: str
    success: bool
    archive: CompactedCheckpointArchive | None
    pre_tokens: int
    post_tokens: int
    saved_tokens: int
    tokens_compressed_ratio: float
    was_cache_hot_utilized: bool
    cost_units_incurred: float
    cost_units_avoided: float
    duration_ms: float


@dataclass(frozen=True)
class ZeroWaitWakeupEvent:
    """Telemetry recorded when user returns to keyboard and resumes session."""

    session_id: str
    idle_total_seconds: float
    cold_prefill_prevented: bool
    tokens_served_immediately: int
    estimated_time_to_first_token_reduction_ms: float
