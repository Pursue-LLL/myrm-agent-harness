# [INPUT]: None
# [OUTPUT]: FloodActionKind, FloodGuardConfig, FloodGuardDecision, FloodGuardStatus, SlidingWindowBucket
# [POS]: agent/context_management/search_flood_guard/flood_guard_types.py

"""Domain models and contracts for multi-agent per-context search flood guard and progressive soft-cap.

[INPUT]
- None (Self-contained domain models for search flow control and progressive rate limiting).

[OUTPUT]
- FloodActionKind: Enumeration of flow control decisions (ALLOWED, SOFT_CAPPED, HARD_BLOCKED).
- FloodGuardDecision: Comprehensive verdict returned prior to or during query execution.
- FloodGuardStatus: Current rate status snapshot for an agent context.
- SlidingWindowBucket: State container tracking timestamped invocation events per agent context.
- FloodGuardConfig: Configuration governing sliding window duration, soft/hard caps, and LRU limits.

[POS]
Domain contract layer for multi-agent search flood guard in context management.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


class FloodActionKind(str, Enum):
    """Flow control disposition for a search invocation."""

    ALLOWED = "allowed"          # Below softCapAfter: full search results returned
    SOFT_CAPPED = "soft_capped"  # Between softCapAfter and blockAfter: taper to 1 result per query
    HARD_BLOCKED = "hard_blocked"# Above blockAfter: reject search with cooldown countdown


@dataclass(frozen=True)
class FloodGuardConfig:
    """Settings controlling per-agent rate limiting windows, thresholds, and memory ceilings."""

    window_seconds: float = 60.0
    soft_cap_after: int = 4
    block_after: int = 8
    cooldown_seconds: float = 30.0
    max_tracked_keys: int = 4096
    soft_cap_results_limit: int = 1


@dataclass(frozen=True)
class FloodGuardDecision:
    """Verdict detailing flow control action, current window count, and cooldown."""

    action: FloodActionKind
    current_count: int
    allowed_results_per_query: int | None
    retry_after_seconds: float
    reason: str
    is_blocked: bool = False

    @property
    def should_taper_results(self) -> bool:
        return self.action == FloodActionKind.SOFT_CAPPED


@dataclass
class SlidingWindowBucket:
    """Mutable timestamp queue for a specific agent context key."""

    key: str
    timestamps: list[float] = field(default_factory=list)
    last_accessed: float = 0.0
    blocked_until: float = 0.0


@dataclass(frozen=True)
class FloodGuardStatus:
    """Current rate status snapshot for an agent context."""

    session_id: str
    subagent_id: str | None
    tracking_key: str
    window_count: int
    is_blocked: bool
    remaining_cooldown: float
    current_action: FloodActionKind

