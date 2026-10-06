# [POS]: tests/agent/context_management/test_agent_handoff.py
# [INPUT]: AgentHandoffEngine, types, state machine, store
# [OUTPUT]: Unit test suite for cross-agent typed handoff and exactly-once claim
"""Unit tests for typed cross-agent handoff protocol, CAS exactly-once claim, and finalization."""

from __future__ import annotations

import concurrent.futures
from pathlib import Path

import pytest

from myrm_agent_harness.agent.context_management.handoff import (
    AgentHandoffEngine,
    AgentHandoffStore,
    FailedApproachRecord,
    FinalizeSessionRequest,
    HandoffAlreadyClaimedError,
    HandoffAlreadyCompletedError,
    HandoffInvalidTransitionError,
    HandoffNotFoundError,
    HandoffStatus,
    HandoffTargetMismatchError,
    ImplicitConstraintRecord,
    SessionFinalizationError,
)


@pytest.fixture
def temp_storage(tmp_path: Path) -> Path:
    storage = tmp_path / "handoffs"
    storage.mkdir(parents=True, exist_ok=True)
    return storage


def test_session_finalizer_and_durable_storage(temp_storage: Path) -> None:
    """Verify session finalization persists 6-dimension handoff spec to disk."""
    engine = AgentHandoffEngine(storage_dir=temp_storage)

    req = FinalizeSessionRequest(
        session_id="sess-001",
        source_profile_id="architect-agent",
        target_profile_id="coder-agent",
        active_goal="Implement WebSocket reconnection logic",
        failed_approaches=[
            FailedApproachRecord(
                approach_name="Naive setTimeout",
                rejected_reason="Causes socket storm on server restart",
                evidence_snippet="Error: 503 Service Unavailable",
                attempted_by_profile_id="architect-agent",
            )
        ],
        implicit_constraints=[
            ImplicitConstraintRecord(
                scope="networking",
                constraint_rule="Exponential backoff with jitter required",
                rationale="Prevents thundering herd problem",
            )
        ],
        errors_and_fixes=["Max retries exceeded -> add circuit breaker"],
        pending_asks=["Confirm maximum retry ceiling with product owner"],
        next_actions=["Write reconnect unit tests", "Deploy proxy canary"],
    )

    res = engine.finalize_session(req)
    assert res.session_id == "sess-001"
    assert res.status == HandoffStatus.PENDING
    assert Path(res.persisted_path).exists()

    # Query from engine
    spec = engine.get_handoff(res.handoff_id)
    assert spec is not None
    assert spec.handoff_id == res.handoff_id
    assert spec.source_profile_id == "architect-agent"
    assert spec.target_profile_id == "coder-agent"
    assert len(spec.failed_approaches) == 1
    assert spec.failed_approaches[0].approach_name == "Naive setTimeout"
    assert len(spec.implicit_constraints) == 1
    assert spec.errors_and_fixes == ["Max retries exceeded -> add circuit breaker"]


def test_invalid_finalization_request(temp_storage: Path) -> None:
    """Ensure invalid whitespace parameters raise SessionFinalizationError."""
    engine = AgentHandoffEngine(storage_dir=temp_storage)

    with pytest.raises(SessionFinalizationError):
        engine.finalize_session(
            FinalizeSessionRequest(
                session_id="   ",
                source_profile_id="coder",
                active_goal="do work",
            )
        )


def test_atomic_claim_and_target_mismatch(temp_storage: Path) -> None:
    """Verify profile target enforcement and successful CAS claim."""
    engine = AgentHandoffEngine(storage_dir=temp_storage)

    res = engine.finalize_session(
        FinalizeSessionRequest(
            session_id="sess-alpha",
            source_profile_id="profiler",
            target_profile_id="optimizer",
            active_goal="Reduce memory footprint",
        )
    )

    # Attempt claim by wrong profile -> Target mismatch
    with pytest.raises(HandoffTargetMismatchError):
        engine.claim_handoff(
            handoff_id=res.handoff_id,
            claimer_profile_id="tester",
            claimer_session_id="sess-beta",
        )

    # Successful claim by designated target profile
    receipt = engine.claim_handoff(
        handoff_id=res.handoff_id,
        claimer_profile_id="optimizer",
        claimer_session_id="sess-beta",
    )
    assert receipt.handoff_id == res.handoff_id
    assert receipt.claimed_by_profile_id == "optimizer"
    assert receipt.claimed_by_session_id == "sess-beta"
    assert receipt.handoff_spec.status == HandoffStatus.CLAIMED


def test_concurrent_duplicate_claim_fails(temp_storage: Path) -> None:
    """Verify exactly-once claim semantics under concurrent race condition."""
    engine = AgentHandoffEngine(storage_dir=temp_storage)

    res = engine.finalize_session(
        FinalizeSessionRequest(
            session_id="sess-parent",
            source_profile_id="planner",
            target_profile_id=None,  # Open to any agent
            active_goal="Execute subtask batch",
        )
    )

    success_count = 0
    failure_count = 0

    def try_claim(worker_idx: int) -> bool:
        try:
            engine.claim_handoff(
                handoff_id=res.handoff_id,
                claimer_profile_id=f"worker-{worker_idx}",
                claimer_session_id=f"sess-worker-{worker_idx}",
            )
            return True
        except HandoffAlreadyClaimedError:
            return False

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(try_claim, i) for i in range(10)]
        for fut in concurrent.futures.as_completed(futures):
            if fut.result():
                success_count += 1
            else:
                failure_count += 1

    assert success_count == 1
    assert failure_count == 9

    # Further attempt directly raises HandoffAlreadyClaimedError
    with pytest.raises(HandoffAlreadyClaimedError):
        engine.claim_handoff(
            handoff_id=res.handoff_id,
            claimer_profile_id="late-worker",
            claimer_session_id="sess-late",
        )


def test_completion_and_cancellation_lifecycle(temp_storage: Path) -> None:
    """Verify completion and cancellation lifecycle invariants."""
    engine = AgentHandoffEngine(storage_dir=temp_storage)

    res = engine.finalize_session(
        FinalizeSessionRequest(
            session_id="sess-a",
            source_profile_id="agent-a",
            active_goal="Build feature X",
        )
    )

    # Claim
    engine.claim_handoff(
        handoff_id=res.handoff_id,
        claimer_profile_id="agent-b",
        claimer_session_id="sess-b",
    )

    # Unauthorized session cannot complete
    with pytest.raises(HandoffInvalidTransitionError):
        engine.complete_handoff(
            handoff_id=res.handoff_id,
            completing_session_id="sess-unauthorized",
        )

    # Claimer completes
    completed = engine.complete_handoff(
        handoff_id=res.handoff_id,
        completing_session_id="sess-b",
    )
    assert completed.status == HandoffStatus.COMPLETED
    assert completed.completed_at is not None

    # Completed handoff cannot be cancelled
    with pytest.raises(HandoffAlreadyCompletedError):
        engine.cancel_handoff(
            handoff_id=res.handoff_id,
            cancelling_session_id="sess-b",
            reason="Aborting",
        )


def test_disk_hydration_upon_restart(temp_storage: Path) -> None:
    """Verify newly instantiated store restores historical records from disk."""
    engine1 = AgentHandoffEngine(storage_dir=temp_storage)
    res = engine1.finalize_session(
        FinalizeSessionRequest(
            session_id="sess-persist",
            source_profile_id="persister",
            active_goal="Check disk hydration",
        )
    )

    # Instantiate fresh store pointing to same directory
    store2 = AgentHandoffStore(storage_dir=temp_storage)
    restored = store2.get(res.handoff_id)
    assert restored is not None
    assert restored.session_id == "sess-persist"
    assert restored.status == HandoffStatus.PENDING

    # Test list_pending
    pending = store2.list_pending()
    assert len(pending) == 1
    assert pending[0].handoff_id == res.handoff_id


def test_nonexistent_handoff_operations(temp_storage: Path) -> None:
    """Ensure operations on nonexistent handoff IDs fail gracefully."""
    engine = AgentHandoffEngine(storage_dir=temp_storage)
    assert engine.get_handoff("nonexistent-id") is None

    with pytest.raises(HandoffNotFoundError):
        engine.claim_handoff(
            handoff_id="nonexistent-id",
            claimer_profile_id="agent",
            claimer_session_id="sess",
        )
