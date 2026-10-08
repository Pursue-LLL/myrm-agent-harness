# [INPUT]: None
# [OUTPUT]: QueryContextStatus, QueryIntentEntry, ContextEvaluationResult
# [POS]: agent/context_management/stale_query_expire/query_context_types.py

"""Strongly typed contracts for persistent session query context and staleness tracking.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- QueryContextStatus: Lifecycle status of a query context within a persistent session.
- QueryIntentEntry: Atomic record representing an active query context subject to dual TTL/turn expiration.
- ContextEvaluationResult: Outcome of resolving active query context against aging criteria.

[POS]
Strongly typed contracts for persistent session query context and staleness tracking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class QueryContextStatus(str, Enum):
    """Lifecycle status of a query context within a persistent session."""

    ACTIVE = "active"
    EXPIRED_TTL = "expired_ttl"
    EXPIRED_TURN = "expired_turn"
    EXPLICITLY_INVALIDATED = "explicitly_invalidated"


@dataclass(frozen=True)
class QueryIntentEntry:
    """Atomic record representing an active query context subject to dual TTL/turn expiration."""

    query_id: str
    session_id: str
    raw_query: str
    intent_summary: str
    created_turn: int
    created_at_epoch_ms: int
    ttl_ms: int = 120_000  # Default 2 minutes TTL
    max_lifetime_turns: int = 3  # Default 3 turns maximum distance
    metadata: dict[str, str] = field(default_factory=dict)

    def is_turn_expired(self, current_turn: int) -> bool:
        """Check whether query has exceeded allowable turn distance."""
        return (current_turn - self.created_turn) > self.max_lifetime_turns

    def is_time_expired(self, current_time_ms: int) -> bool:
        """Check whether query has exceeded time-to-live threshold."""
        return (current_time_ms - self.created_at_epoch_ms) > self.ttl_ms


@dataclass(frozen=True)
class ContextEvaluationResult:
    """Outcome of resolving active query context against aging criteria."""

    is_valid: bool
    status: QueryContextStatus
    active_query: QueryIntentEntry | None
    invalidation_reason: str | None = None
