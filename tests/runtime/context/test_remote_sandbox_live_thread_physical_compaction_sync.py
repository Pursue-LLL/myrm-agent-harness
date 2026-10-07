"""Unit tests for remote sandbox live thread physical compaction synchronization.

Validates host-to-remote wire protocol, monotonic sequence binding, physical in-memory
thread replacement, token reduction verification, and drift compensation reconciliation.
"""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.context.live_thread_compaction_types import (
    CompactionSyncStatus,
    LiveThreadCompactionSignal,
)
from myrm_agent_harness.runtime.context.remote_live_thread_compaction_coordinator import (
    RemoteLiveThreadCompactionCoordinator,
)
from myrm_agent_harness.runtime.context.remote_thread_actor_endpoint import (
    RemoteThreadActorEndpoint,
)


@pytest.mark.asyncio
async def test_endpoint_interaction_accumulation_and_snapshot() -> None:
    """Validate that conversation turns accumulate physically and tokens increase."""
    endpoint = RemoteThreadActorEndpoint(thread_id="th_sandbox_001")

    for i in range(10):
        tokens = endpoint.append_interaction(
            user_turn=f"Task step {i}: run query and compute statistics",
            assistant_turn=f"Execution result {i}: processed batch successfully with status 200",
        )
        assert tokens > 0

    snapshot = endpoint.get_snapshot()
    assert snapshot.thread_id == "th_sandbox_001"
    assert snapshot.total_turns == 20
    assert snapshot.is_compacted is False
    assert snapshot.last_applied_sequence == 0
    assert snapshot.active_token_count > 200


@pytest.mark.asyncio
async def test_physical_compaction_sync_success_and_token_plummet() -> None:
    """Validate physical message replacement, dramatic token reduction, and alignment."""
    coordinator = RemoteLiveThreadCompactionCoordinator()
    endpoint = RemoteThreadActorEndpoint(thread_id="th_sandbox_002")

    # Accumulate 15 long conversational turns
    for i in range(15):
        endpoint.append_interaction(
            user_turn=f"Long detailed user input payload {i} requesting analysis of system components",
            assistant_turn=f"Verbose multi-line execution logs for step {i} containing intermediate diagnostics",
        )

    before_tokens = endpoint.active_token_count
    assert before_tokens > 500

    summary = "System components 0-13 analyzed. All intermediate tests passed."
    retained_tail = (
        "user: Long detailed user input payload 14 requesting analysis of system components",
        "assistant: Verbose multi-line execution logs for step 14 containing intermediate diagnostics",
    )

    result = coordinator.dispatch_compaction(
        session_id="sess_live_100",
        thread_id="th_sandbox_002",
        endpoint=endpoint,
        summary=summary,
        retained_tail_turns=retained_tail,
    )

    assert result.status == CompactionSyncStatus.SUCCESS
    assert result.thread_id == "th_sandbox_002"
    assert result.sequence_number == 1
    assert result.after_token_count < before_tokens
    assert result.compression_ratio > 0.60
    assert result.drift_percentage <= 0.05
    assert result.applied_summary == summary

    # Verify physical remote in-memory thread was replaced
    snapshot = endpoint.get_snapshot()
    assert snapshot.is_compacted is True
    assert snapshot.total_turns == 3  # [COMPACTED_SUMMARY] + 2 tail messages
    assert snapshot.history_messages[0].startswith("[COMPACTED_SUMMARY]")
    assert snapshot.history_messages[1] == retained_tail[0]
    assert snapshot.history_messages[2] == retained_tail[1]


@pytest.mark.asyncio
async def test_stale_or_out_of_order_sequence_rejection() -> None:
    """Ensure remote thread strictly rejects stale or duplicate sequence signals."""
    coordinator = RemoteLiveThreadCompactionCoordinator()
    endpoint = RemoteThreadActorEndpoint(thread_id="th_sandbox_003")

    endpoint.append_interaction("query 1", "response 1")
    endpoint.append_interaction("query 2", "response 2")

    # First compaction at sequence 1
    res1 = coordinator.dispatch_compaction(
        session_id="sess_live_101",
        thread_id="th_sandbox_003",
        endpoint=endpoint,
        summary="Summary 1",
        retained_tail_turns=("assistant: response 2",),
    )
    assert res1.status == CompactionSyncStatus.SUCCESS
    assert res1.sequence_number == 1

    # Attempt to dispatch a stale signal with sequence_number = 1
    stale_signal = LiveThreadCompactionSignal(
        session_id="sess_live_101",
        thread_id="th_sandbox_003",
        sequence_number=1,  # Stale: already applied 1
        compacted_summary="Stale summary attempt",
        retained_tail_turns=(),
        target_token_budget=50,
        timestamp=0.0,
    )

    res_stale = endpoint.apply_physical_compaction(stale_signal)
    assert res_stale.status == CompactionSyncStatus.REJECTED_STALE
    assert "Stale sequence 1 <= 1" in (res_stale.error_message or "")

    # Physical thread retains previous state
    snapshot = endpoint.get_snapshot()
    assert snapshot.last_applied_sequence == 1


@pytest.mark.asyncio
async def test_drift_compensation_and_reconciliation() -> None:
    """Validate automatic adaptive reconciliation when initial target budget drifts."""
    coordinator = RemoteLiveThreadCompactionCoordinator(drift_tolerance=0.05)
    endpoint = RemoteThreadActorEndpoint(thread_id="th_sandbox_004")

    for i in range(8):
        endpoint.append_interaction(f"prompt {i}", f"long trace answer {i}")

    summary = "Compact milestone summary"
    tail = ("prompt 7", "long trace answer 7")

    # Deliberately provide an artificially distorted target budget to trigger drift
    result = coordinator.dispatch_compaction(
        session_id="sess_live_102",
        thread_id="th_sandbox_004",
        endpoint=endpoint,
        summary=summary,
        retained_tail_turns=tail,
        target_token_budget=10,  # Unrealistic target causing >5% drift
    )

    # Coordinator compensates drift and returns reconciled status
    assert result.status == CompactionSyncStatus.SUCCESS
    assert result.drift_percentage == 0.0

    history = coordinator.get_audit_history("th_sandbox_004")
    assert len(history) == 1
    assert history[0].after_token_count == endpoint.active_token_count
