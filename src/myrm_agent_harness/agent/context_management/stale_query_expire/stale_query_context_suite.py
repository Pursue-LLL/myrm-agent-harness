# [INPUT]: QueryContextStatus, QueryIntentEntry, ContextEvaluationResult, StaleQueryExpiryEngine
# [OUTPUT]: MateclawStaleQueryContextExpireSuite
# [POS]: agent/context_management/stale_query_expire/stale_query_context_suite.py

"""End-to-end suite orchestrating query context expiration in persistent long-running sessions.

[INPUT]
- agent.context_management.stale_query_expire.query_context_types::ContextEvaluationResult,
  QueryContextStatus, QueryIntentEntry (POS: Strongly typed contracts for persistent session query context and
  staleness tracking.)
- agent.context_management.stale_query_expire.stale_query_expiry_engine::StaleQueryExpiryEngine (POS: Engine
  evaluating query context aging through dual turn-distance and TTL criteria.)

[OUTPUT]
- MateclawStaleQueryContextExpireSuite: Industrial-grade suite preventing stale query intent pollution across
  persistent conversations.

[POS]
End-to-end suite orchestrating query context expiration in persistent long-running sessions.
"""

from __future__ import annotations

import time
import uuid

from .query_context_types import (
    ContextEvaluationResult,
    QueryContextStatus,
    QueryIntentEntry,
)
from .stale_query_expiry_engine import StaleQueryExpiryEngine


class MateclawStaleQueryContextExpireSuite:
    """Industrial-grade suite preventing stale query intent pollution across persistent conversations."""

    def __init__(self, engine: StaleQueryExpiryEngine | None = None) -> None:
        """Initialize stale query context expiration suite."""
        self._engine: StaleQueryExpiryEngine = engine or StaleQueryExpiryEngine()
        self._session_queries: dict[str, QueryIntentEntry] = {}
        self._expired_by_turn_count: int = 0
        self._expired_by_ttl_count: int = 0
        self._explicit_invalidations_count: int = 0

    @property
    def expired_by_turn_count(self) -> int:
        """Return total count of queries invalidated due to turn distance."""
        return self._expired_by_turn_count

    @property
    def expired_by_ttl_count(self) -> int:
        """Return total count of queries invalidated due to TTL timeout."""
        return self._expired_by_ttl_count

    @property
    def explicit_invalidations_count(self) -> int:
        """Return total count of explicitly invalidated queries."""
        return self._explicit_invalidations_count

    def record_query_intent(
        self,
        session_id: str,
        raw_query: str,
        intent_summary: str,
        created_turn: int,
        created_at_epoch_ms: int | None = None,
        ttl_ms: int = 120_000,
        max_lifetime_turns: int = 3,
        metadata: dict[str, str] | None = None,
    ) -> QueryIntentEntry:
        """Record or overwrite the active query intent for a given session."""
        now_ms = created_at_epoch_ms if created_at_epoch_ms is not None else int(time.time() * 1000)
        query_id = f"query_{uuid.uuid4().hex[:10]}"

        entry = QueryIntentEntry(
            query_id=query_id,
            session_id=session_id,
            raw_query=raw_query.strip(),
            intent_summary=intent_summary.strip(),
            created_turn=created_turn,
            created_at_epoch_ms=now_ms,
            ttl_ms=ttl_ms,
            max_lifetime_turns=max_lifetime_turns,
            metadata=dict(metadata or {}),
        )

        self._session_queries[session_id] = entry
        return entry

    def resolve_active_query(
        self,
        session_id: str,
        current_turn: int,
        current_time_ms: int | None = None,
    ) -> ContextEvaluationResult:
        """Resolve active query context, automatically evicting expired entries."""
        entry = self._session_queries.get(session_id)
        if entry is None:
            return ContextEvaluationResult(
                is_valid=False,
                status=QueryContextStatus.EXPLICITLY_INVALIDATED,
                active_query=None,
                invalidation_reason=f"No query context currently registered for session '{session_id}'.",
            )

        now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
        eval_result = self._engine.evaluate_entry(entry, current_turn=current_turn, current_time_ms=now_ms)

        if not eval_result.is_valid:
            # Evict expired entry from registry to prevent stale intent pollution
            self._session_queries.pop(session_id, None)
            if eval_result.status == QueryContextStatus.EXPIRED_TURN:
                self._expired_by_turn_count += 1
            elif eval_result.status == QueryContextStatus.EXPIRED_TTL:
                self._expired_by_ttl_count += 1

        return eval_result

    def invalidate_query(self, session_id: str, reason: str = "Topic shift or explicit reset") -> bool:
        """Explicitly invalidate and evict active query context for a session."""
        if session_id in self._session_queries:
            self._session_queries.pop(session_id, None)
            self._explicit_invalidations_count += 1
            return True
        return False

    def clean_all_expired(
        self,
        session_turns: dict[str, int],
        current_time_ms: int | None = None,
    ) -> int:
        """Batch prune expired query contexts across all registered sessions."""
        now_ms = current_time_ms if current_time_ms is not None else int(time.time() * 1000)
        evicted = 0

        sessions = list(self._session_queries.keys())
        for sess_id in sessions:
            current_turn = session_turns.get(sess_id, 0)
            result = self.resolve_active_query(sess_id, current_turn=current_turn, current_time_ms=now_ms)
            if not result.is_valid:
                evicted += 1

        return evicted
