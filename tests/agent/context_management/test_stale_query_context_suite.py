"""Unit tests for Mateclaw stale query context expiration suite in persistent conversations."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.stale_query_expire import (
    ContextEvaluationResult,
    MateclawStaleQueryContextExpireSuite,
    QueryContextStatus,
    QueryIntentEntry,
)


def test_active_query_valid_within_ttl_and_turns() -> None:
    """Test query intent remains active when turn distance and TTL are both within bounds."""
    suite = MateclawStaleQueryContextExpireSuite()
    session_id = "sess_persistent_001"
    start_time_ms = 1_000_000

    entry: QueryIntentEntry = suite.record_query_intent(
        session_id=session_id,
        raw_query="Why did Docker container exit with code 137?",
        intent_summary="Inspect OOM killer and container exit 137",
        created_turn=2,
        created_at_epoch_ms=start_time_ms,
        ttl_ms=30_000,
        max_lifetime_turns=3,
    )

    assert entry.session_id == session_id
    assert entry.created_turn == 2

    # Query at turn 4 (gap = 2 <= 3) after 10 seconds (10,000ms < 30,000ms)
    res: ContextEvaluationResult = suite.resolve_active_query(
        session_id=session_id,
        current_turn=4,
        current_time_ms=start_time_ms + 10_000,
    )

    assert res.is_valid is True
    assert res.status == QueryContextStatus.ACTIVE
    assert res.active_query is not None
    assert res.active_query.raw_query == "Why did Docker container exit with code 137?"
    assert res.invalidation_reason is None


def test_query_expires_when_turn_distance_exceeded() -> None:
    """Test query intent expires when conversation progresses past allowed turn distance."""
    suite = MateclawStaleQueryContextExpireSuite()
    session_id = "sess_persistent_002"
    start_time_ms = 1_000_000

    suite.record_query_intent(
        session_id=session_id,
        raw_query="Check latency spikes on port 8080",
        intent_summary="Port 8080 latency audit",
        created_turn=1,
        created_at_epoch_ms=start_time_ms,
        ttl_ms=60_000,
        max_lifetime_turns=2,
    )

    # In turn 5 (gap = 4 > 2 max turns), even though only 5 seconds elapsed
    res: ContextEvaluationResult = suite.resolve_active_query(
        session_id=session_id,
        current_turn=5,
        current_time_ms=start_time_ms + 5_000,
    )

    assert res.is_valid is False
    assert res.status == QueryContextStatus.EXPIRED_TURN
    assert res.active_query is None
    assert res.invalidation_reason is not None
    assert "expired by turn distance" in res.invalidation_reason
    assert suite.expired_by_turn_count == 1

    # Verify query was evicted: subsequent check yields no query
    res_after = suite.resolve_active_query(session_id=session_id, current_turn=5)
    assert res_after.is_valid is False
    assert res_after.status == QueryContextStatus.EXPLICITLY_INVALIDATED


def test_query_expires_when_ttl_timeout_exceeded() -> None:
    """Test query intent expires when time elapsed exceeds TTL even within allowed turn count."""
    suite = MateclawStaleQueryContextExpireSuite()
    session_id = "sess_persistent_003"
    start_time_ms = 2_000_000

    suite.record_query_intent(
        session_id=session_id,
        raw_query="Fetch latest PR comments for PR-501",
        intent_summary="PR-501 discussion lookup",
        created_turn=10,
        created_at_epoch_ms=start_time_ms,
        ttl_ms=15_000,  # 15s TTL
        max_lifetime_turns=5,
    )

    # In turn 11 (gap = 1 <= 5), but 25s elapsed (> 15s TTL)
    res: ContextEvaluationResult = suite.resolve_active_query(
        session_id=session_id,
        current_turn=11,
        current_time_ms=start_time_ms + 25_000,
    )

    assert res.is_valid is False
    assert res.status == QueryContextStatus.EXPIRED_TTL
    assert res.active_query is None
    assert res.invalidation_reason is not None
    assert "expired by time-to-live" in res.invalidation_reason
    assert suite.expired_by_ttl_count == 1


def test_explicit_invalidation_and_clean_all_expired() -> None:
    """Test manual invalidation and batch pruning across multiple sessions."""
    suite = MateclawStaleQueryContextExpireSuite()
    start_time = 3_000_000

    suite.record_query_intent("sess_A", "query A", "intent A", created_turn=1, created_at_epoch_ms=start_time, ttl_ms=5_000)
    suite.record_query_intent("sess_B", "query B", "intent B", created_turn=1, created_at_epoch_ms=start_time, ttl_ms=50_000, max_lifetime_turns=2)
    suite.record_query_intent("sess_C", "query C", "intent C", created_turn=1, created_at_epoch_ms=start_time, ttl_ms=50_000, max_lifetime_turns=10)

    # 1. Explicitly invalidate sess_C
    invalidated = suite.invalidate_query("sess_C", reason="User changed topic to deployment")
    assert invalidated is True
    assert suite.explicit_invalidations_count == 1
    assert suite.resolve_active_query("sess_C", current_turn=1).is_valid is False

    # 2. Batch prune: sess_A expires by time (10s > 5s), sess_B expires by turn (turn 5 > 1+2=3)
    evicted_count = suite.clean_all_expired(
        session_turns={"sess_A": 1, "sess_B": 5},
        current_time_ms=start_time + 10_000,
    )
    assert evicted_count == 2
    assert suite.resolve_active_query("sess_A", current_turn=1).is_valid is False
    assert suite.resolve_active_query("sess_B", current_turn=5).is_valid is False
