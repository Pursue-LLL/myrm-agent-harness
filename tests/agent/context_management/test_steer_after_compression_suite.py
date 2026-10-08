"""Unit tests for Hermes-WebUI post-compaction worker steering and OOB sanitization suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.steer_after_compression import (
    ActiveWorkerDescriptor,
    HermesWebuiSteerAfterCompressionSuite,
    SanitizedReplayResult,
    SteerDispatchResult,
    SteerMessageKind,
    SteerResolutionStatus,
    WorkerLifecycleState,
)


def test_steer_resolves_active_worker_across_compaction_rotation() -> None:
    """Test steer directives accurately resolve the active worker even after compaction session rotation."""
    suite = HermesWebuiSteerAfterCompressionSuite()
    original_session_id = "sess_hermes_001"
    worker_id = "worker_core_alpha"

    # 1. Register active worker on original session
    worker: ActiveWorkerDescriptor = suite.register_active_worker(
        worker_id=worker_id,
        session_id=original_session_id,
        active_run_id="run_999",
    )
    assert worker.worker_id == worker_id
    assert worker.state == WorkerLifecycleState.RUNNING

    # 2. Steer direct delivery before compaction
    direct_res: SteerDispatchResult = suite.steer_worker(
        session_id=original_session_id,
        message="Prioritize refactoring authentication",
    )
    assert direct_res.delivered is True
    assert direct_res.status == SteerResolutionStatus.RESOLVED_DIRECT
    assert direct_res.worker_id == worker_id
    assert "Prioritize refactoring authentication" in worker.steer_inbox

    # 3. Simulate context compaction causing session id rotation
    compacted_session_id = "sess_hermes_001_compacted_v2"
    suite.notify_compaction_rotation(
        prior_session_id=original_session_id,
        new_session_id=compacted_session_id,
    )

    # 4. Steer using old pre-compaction session ID resolves via alias to active worker
    alias_res: SteerDispatchResult = suite.steer_worker(
        session_id=original_session_id,
        message="Add security audit headers as well",
    )
    assert alias_res.delivered is True
    assert alias_res.status == SteerResolutionStatus.RESOLVED_DIRECT
    assert "Add security audit headers as well" in worker.steer_inbox


def test_emergency_stop_halts_worker_and_persists_oob_event() -> None:
    """Test emergency stop halts execution during preflight/running and logs durable OOB turn."""
    suite = HermesWebuiSteerAfterCompressionSuite()
    session_id = "sess_hermes_002"
    worker_id = "worker_stop_target"

    suite.register_active_worker(
        worker_id=worker_id,
        session_id=session_id,
    )

    # Issue emergency stop
    stop_res: SteerDispatchResult = suite.emergency_stop(
        session_id=session_id,
        reason="Budget threshold exceeded",
    )
    assert stop_res.delivered is True
    assert stop_res.status == SteerResolutionStatus.STOPPED_IN_PREFLIGHT
    assert stop_res.kind == SteerMessageKind.OUT_OF_BAND_STOP

    # Verify worker transitioned to STOPPED state
    worker = suite.get_worker(worker_id)
    assert worker.state == WorkerLifecycleState.STOPPED
    assert any("[STOP]: Budget threshold exceeded" in msg for msg in worker.steer_inbox)

    # Verify durable store has the OOB stop message
    persisted = suite.sanitizer.get_persisted_history(session_id)
    assert len(persisted) == 1
    assert persisted[0].is_oob is True
    assert persisted[0].kind == SteerMessageKind.OUT_OF_BAND_STOP


def test_idempotent_settle_boundary_and_terminal_drain() -> None:
    """Test idempotent settle boundary and prevention of stranded steer directives after teardown."""
    suite = HermesWebuiSteerAfterCompressionSuite()
    session_id = "sess_hermes_003"
    worker_id = "worker_settle_target"

    suite.register_active_worker(
        worker_id=worker_id,
        session_id=session_id,
    )

    # First settle pass
    settled_1 = suite.settle_worker(worker_id=worker_id, final_state=WorkerLifecycleState.SETTLED)
    assert settled_1.state == WorkerLifecycleState.SETTLED
    settle_time_1 = settled_1.settled_at_utc

    # Second settle pass is idempotent
    settled_2 = suite.settle_worker(worker_id=worker_id, final_state=WorkerLifecycleState.SETTLED)
    assert settled_2.settled_at_utc == settle_time_1

    # Steering a settled worker does not strand directives
    stranded_res: SteerDispatchResult = suite.steer_worker(
        session_id=session_id,
        message="Late steer directive that should be rejected",
    )
    assert stranded_res.delivered is False
    assert stranded_res.status == SteerResolutionStatus.WORKER_ALREADY_SETTLED


def test_oob_persistence_preserved_while_replay_sanitized() -> None:
    """Test full durable preservation of OOB turns while achieving 100% clean prompt replay context."""
    suite = HermesWebuiSteerAfterCompressionSuite()
    session_id = "sess_hermes_004"

    # 1. Normal prompt turn
    suite.record_turn(
        session_id=session_id,
        message_id="m1",
        role="user",
        content="Deploy service to staging",
        is_oob=False,
    )
    # 2. Assistant turn
    suite.record_turn(
        session_id=session_id,
        message_id="m2",
        role="assistant",
        content="Starting deployment workflow...",
        is_oob=False,
    )
    # 3. OOB steer turn (e.g. from UI progress bar / steer modal)
    suite.record_turn(
        session_id=session_id,
        message_id="m3_oob",
        role="user",
        content="[OOB] Update progress card to 45%",
        is_oob=True,
        kind=SteerMessageKind.OUT_OF_BAND_STEER,
    )
    # 4. Another in-band turn
    suite.record_turn(
        session_id=session_id,
        message_id="m4",
        role="user",
        content="Run integration verification",
        is_oob=False,
    )

    # Verify durable persistence retains all 4 turns
    persisted = suite.sanitizer.get_persisted_history(session_id)
    assert len(persisted) == 4

    # Verify replay assembly strips the OOB turn
    replay: SanitizedReplayResult = suite.assemble_clean_replay(session_id=session_id)
    assert replay.total_persisted_count == 4
    assert replay.stripped_oob_count == 1
    assert len(replay.sanitized_messages) == 3
    assert all(not m.is_oob for m in replay.sanitized_messages)
    assert replay.is_clean is True
    assert replay.audit_digest is not None
