# [INPUT]: QueryContextStatus, QueryIntentEntry, ContextEvaluationResult
# [OUTPUT]: StaleQueryExpiryEngine
# [POS]: agent/context_management/stale_query_expire/stale_query_expiry_engine.py

"""Engine evaluating query context aging through dual turn-distance and TTL criteria.

[INPUT]
- agent.context_management.stale_query_expire.query_context_types::ContextEvaluationResult,
  QueryContextStatus, QueryIntentEntry (POS: Strongly typed contracts for persistent session query context and
  staleness tracking.)

[OUTPUT]
- StaleQueryExpiryEngine: Evaluates query intent staleness to prevent outdated intent pollution in long
  sessions.

[POS]
Engine evaluating query context aging through dual turn-distance and TTL criteria.
"""

from __future__ import annotations

from .query_context_types import (
    ContextEvaluationResult,
    QueryContextStatus,
    QueryIntentEntry,
)


class StaleQueryExpiryEngine:
    """Evaluates query intent staleness to prevent outdated intent pollution in long sessions."""

    def evaluate_entry(
        self,
        entry: QueryIntentEntry,
        current_turn: int,
        current_time_ms: int,
    ) -> ContextEvaluationResult:
        """Evaluate a query entry against current turn count and timestamp.

        Dual-track invalidation criteria:
        1. Turn distance exceeded: user conversation has progressed beyond topic scope.
        2. TTL exceeded: time threshold lapsed preventing stale tool reuse.
        """
        # 1. Turn-distance invalidation
        if entry.is_turn_expired(current_turn):
            turn_gap = current_turn - entry.created_turn
            return ContextEvaluationResult(
                is_valid=False,
                status=QueryContextStatus.EXPIRED_TURN,
                active_query=None,
                invalidation_reason=(
                    f"Query '{entry.query_id}' expired by turn distance: progressed {turn_gap} turns "
                    f"beyond allowed max {entry.max_lifetime_turns} turns (created turn {entry.created_turn}, "
                    f"current turn {current_turn})."
                ),
            )

        # 2. Time-to-live invalidation
        if entry.is_time_expired(current_time_ms):
            elapsed_ms = current_time_ms - entry.created_at_epoch_ms
            return ContextEvaluationResult(
                is_valid=False,
                status=QueryContextStatus.EXPIRED_TTL,
                active_query=None,
                invalidation_reason=(
                    f"Query '{entry.query_id}' expired by time-to-live: {elapsed_ms}ms elapsed "
                    f"exceeding TTL threshold of {entry.ttl_ms}ms."
                ),
            )

        # Active and valid
        return ContextEvaluationResult(
            is_valid=True,
            status=QueryContextStatus.ACTIVE,
            active_query=entry,
            invalidation_reason=None,
        )
