# [INPUT]: FloodActionKind, FloodGuardConfig, FloodGuardDecision, FloodGuardStatus, MultiAgentSearchFloodGuardSuite, PerAgentSlidingWindowTracker, ProgressiveSoftCapGate
# [OUTPUT]: test_multi_agent_search_flood_guard_suite.py
# [POS]: tests/agent/context_management/test_multi_agent_search_flood_guard_suite.py

"""Comprehensive unit tests for MultiAgentSearchFloodGuardSuite.

Verifies:
1. Isolated per-agent sliding windows ensuring parallel subagents do not collide or starve quota.
2. Rolling window timestamp pruning outside window_seconds.
3. Progressive soft-cap tapering multi-query and single-query results to 1 item when threshold exceeded.
4. Hard circuit-breaker block with cooldown countdown upon exceeding block_after.
5. Strict LRU memory eviction maintaining max_tracked_keys ceiling under high concurrency.
6. Unified end-to-end facade orchestration and context reset.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.search_flood_guard import (
    FloodActionKind,
    FloodGuardConfig,
    FloodGuardDecision,
    FloodGuardStatus,
    MultiAgentSearchFloodGuardSuite,
    PerAgentSlidingWindowTracker,
    ProgressiveSoftCapGate,
)


def test_isolated_multi_agent_window_buckets() -> None:
    """Verifies that subagents within the same session maintain strictly independent sliding buckets."""
    tracker = PerAgentSlidingWindowTracker(FloodGuardConfig(window_seconds=60.0))
    t0 = 1000.0

    # Main agent executes 2 searches
    tracker.record_call(session_id="session-alpha", subagent_id=None, timestamp=t0)
    tracker.record_call(session_id="session-alpha", subagent_id=None, timestamp=t0 + 1.0)

    # Subagent-1 executes 4 searches
    for i in range(4):
        tracker.record_call(session_id="session-alpha", subagent_id="subagent-1", timestamp=t0 + i)

    # Subagent-2 executes 1 search
    tracker.record_call(session_id="session-alpha", subagent_id="subagent-2", timestamp=t0 + 2.0)

    # Another session executes 3 searches
    for i in range(3):
        tracker.record_call(session_id="session-beta", subagent_id="subagent-1", timestamp=t0 + i)

    # Verify counts are isolated per key
    assert tracker.get_window_count("session-alpha", None, timestamp=t0 + 5.0) == 2
    assert tracker.get_window_count("session-alpha", "subagent-1", timestamp=t0 + 5.0) == 4
    assert tracker.get_window_count("session-alpha", "subagent-2", timestamp=t0 + 5.0) == 1
    assert tracker.get_window_count("session-beta", "subagent-1", timestamp=t0 + 5.0) == 3


def test_sliding_window_pruning() -> None:
    """Verifies that timestamps outside the window are properly pruned."""
    tracker = PerAgentSlidingWindowTracker(FloodGuardConfig(window_seconds=60.0))
    t0 = 1000.0

    # 3 calls recorded at t0, t0+10, t0+20
    tracker.record_call("sess", "agent-a", timestamp=t0)
    tracker.record_call("sess", "agent-a", timestamp=t0 + 10.0)
    tracker.record_call("sess", "agent-a", timestamp=t0 + 20.0)

    # At t0+30, all 3 calls remain in 60s window
    assert tracker.get_window_count("sess", "agent-a", timestamp=t0 + 30.0) == 3

    # At t0+65, the first call (at t0) has expired (65 > 60), 2 remain
    assert tracker.get_window_count("sess", "agent-a", timestamp=t0 + 65.0) == 2

    # At t0+75, the second call (at t0+10) has expired (65 > 60), but t0+20 remains (55 <= 60)
    count, bucket = tracker.record_call("sess", "agent-a", timestamp=t0 + 75.0)
    # The call at t0+20 and the new call at t0+75 -> 2 calls
    assert count == 2
    assert len(bucket.timestamps) == 2



def test_progressive_soft_cap_tapering() -> None:
    """Verifies progressive tapering to 1 result when frequency exceeds soft_cap_after."""
    config = FloodGuardConfig(
        window_seconds=60.0,
        soft_cap_after=3,
        block_after=6,
        soft_cap_results_limit=1,
    )
    tracker = PerAgentSlidingWindowTracker(config)
    gate = ProgressiveSoftCapGate(tracker, config)
    t0 = 2000.0

    # Calls 1 to 3: within allowed limit
    for i in range(1, 4):
        decision = gate.evaluate_and_record("sess", "sub-1", timestamp=t0 + i)
        assert decision.action == FloodActionKind.ALLOWED
        assert decision.is_blocked is False
        assert decision.allowed_results_per_query is None

    # Call 4: exceeds soft_cap_after (3) -> SOFT_CAPPED
    dec4 = gate.evaluate_and_record("sess", "sub-1", timestamp=t0 + 4.0)
    assert dec4.action == FloodActionKind.SOFT_CAPPED
    assert dec4.is_blocked is False
    assert dec4.allowed_results_per_query == 1
    assert dec4.should_taper_results is True

    # Test flat sequence tapering
    raw_results: tuple[str, ...] = ("doc1", "doc2", "doc3", "doc4", "doc5")
    tapered = gate.apply_soft_cap(raw_results, dec4)
    assert tapered == ("doc1",)

    # Test grouped queries tapering
    raw_grouped = {
        "query_a": ("chunk_a1", "chunk_a2", "chunk_a3"),
        "query_b": ("chunk_b1", "chunk_b2"),
    }
    tapered_grouped = gate.apply_soft_cap_to_grouped(raw_grouped, dec4)
    assert tapered_grouped == {
        "query_a": ("chunk_a1",),
        "query_b": ("chunk_b1",),
    }

    # Verify that an ALLOWED decision does not taper
    dec_allowed = FloodGuardDecision(
        action=FloodActionKind.ALLOWED,
        current_count=2,
        allowed_results_per_query=None,
        retry_after_seconds=0.0,
        reason="ok",
    )
    assert gate.apply_soft_cap(raw_results, dec_allowed) == raw_results
    assert gate.apply_soft_cap_to_grouped(raw_grouped, dec_allowed) == raw_grouped


def test_hard_block_circuit_breaker_and_cooldown() -> None:
    """Verifies that exceeding block_after triggers HARD_BLOCKED and cooldown rejection."""
    config = FloodGuardConfig(
        window_seconds=60.0,
        soft_cap_after=2,
        block_after=4,
        cooldown_seconds=30.0,
    )
    tracker = PerAgentSlidingWindowTracker(config)
    gate = ProgressiveSoftCapGate(tracker, config)
    t0 = 3000.0

    # Calls 1, 2 (ALLOWED), 3, 4 (SOFT_CAPPED)
    for i in range(1, 5):
        gate.evaluate_and_record("sess", "worker", timestamp=t0 + i)

    # Call 5: exceeds block_after (4) -> HARD_BLOCKED
    dec_block = gate.evaluate_and_record("sess", "worker", timestamp=t0 + 5.0)
    assert dec_block.action == FloodActionKind.HARD_BLOCKED
    assert dec_block.is_blocked is True
    assert dec_block.retry_after_seconds == 30.0

    # Call during cooldown period (t0 + 15.0) -> Rejected immediately
    dec_cooldown = gate.evaluate_and_record("sess", "worker", timestamp=t0 + 15.0)
    assert dec_cooldown.action == FloodActionKind.HARD_BLOCKED
    assert dec_cooldown.is_blocked is True
    assert dec_cooldown.retry_after_seconds == pytest.approx(20.0, abs=0.1)

    # Call after cooldown expires (t0 + 36.0) -> Re-evaluated (cooldown recovered, reset history)
    dec_after = gate.evaluate_and_record("sess", "worker", timestamp=t0 + 36.0)
    assert dec_after.action == FloodActionKind.ALLOWED
    assert dec_after.is_blocked is False
    assert dec_after.current_count == 1


def test_lru_eviction_bounded_memory() -> None:
    """Verifies LRU memory boundary pruning when max_tracked_keys is reached."""
    config = FloodGuardConfig(max_tracked_keys=3)
    tracker = PerAgentSlidingWindowTracker(config)

    # Fill capacity with keys A, B, C
    tracker.record_call("sess", "agent-A", timestamp=10.0)
    tracker.record_call("sess", "agent-B", timestamp=11.0)
    tracker.record_call("sess", "agent-C", timestamp=12.0)
    assert tracker.tracked_keys_count == 3

    # Access agent-A to make it most recently used (LRU order: B, C, A)
    tracker.get_window_count("sess", "agent-A", timestamp=13.0)

    # Add new key agent-D -> oldest key (agent-B) must be evicted
    tracker.record_call("sess", "agent-D", timestamp=14.0)
    assert tracker.tracked_keys_count == 3

    # agent-B was evicted, its count should be 0
    assert tracker.get_window_count("sess", "agent-B", timestamp=15.0) == 0
    # agent-A was kept alive
    assert tracker.get_window_count("sess", "agent-A", timestamp=15.0) == 1


def test_facade_end_to_end_orchestration_and_reset() -> None:
    """Verifies high-level facade operations, status inspections, and reset capabilities."""
    suite = MultiAgentSearchFloodGuardSuite(
        FloodGuardConfig(
            window_seconds=60.0,
            soft_cap_after=2,
            block_after=4,
            cooldown_seconds=20.0,
        )
    )
    t0 = 5000.0

    # 1. Initial status inspection
    status0 = suite.get_status("sess-facade", "sub-worker", timestamp=t0)
    assert status0.window_count == 0
    assert status0.is_blocked is False
    assert status0.current_action == FloodActionKind.ALLOWED

    # 2. Sequential calls transitioning from ALLOWED to SOFT_CAPPED
    suite.evaluate_and_record("sess-facade", "sub-worker", timestamp=t0)
    suite.evaluate_and_record("sess-facade", "sub-worker", timestamp=t0 + 1.0)
    dec3 = suite.evaluate_and_record("sess-facade", "sub-worker", timestamp=t0 + 2.0)
    assert dec3.action == FloodActionKind.SOFT_CAPPED

    # 3. Status reflection
    status_mid = suite.get_status("sess-facade", "sub-worker", timestamp=t0 + 3.0)
    assert status_mid.window_count == 3
    assert status_mid.current_action == FloodActionKind.SOFT_CAPPED
    assert suite.get_window_count("sess-facade", "sub-worker", timestamp=t0 + 3.0) == 3

    # 4. Result tapering through facade
    docs: tuple[str, ...] = ("doc_alpha", "doc_beta", "doc_gamma")
    tapered = suite.apply_soft_cap(docs, dec3)
    assert tapered == ("doc_alpha",)

    # 5. Trigger hard block
    suite.evaluate_and_record("sess-facade", "sub-worker", timestamp=t0 + 4.0)
    dec5 = suite.evaluate_and_record("sess-facade", "sub-worker", timestamp=t0 + 5.0)
    assert dec5.action == FloodActionKind.HARD_BLOCKED
    assert dec5.is_blocked is True
    assert suite.get_remaining_cooldown("sess-facade", "sub-worker", timestamp=t0 + 6.0) > 0.0

    # 6. Reset bucket clears block and count
    suite.reset("sess-facade", "sub-worker")
    status_reset = suite.get_status("sess-facade", "sub-worker", timestamp=t0 + 6.0)
    assert status_reset.window_count == 0
    assert status_reset.is_blocked is False
    assert status_reset.current_action == FloodActionKind.ALLOWED
