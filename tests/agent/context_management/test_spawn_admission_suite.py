"""Unit tests for spawn name reservation until durable admission suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.agent.context_management.spawn_reservation import (
    AdmissionCommitResult,
    ReservationResult,
    ReservationState,
    SpawnNameReservationEngine,
    SpawnNameReservationUntilAdmissionDurableSuite,
)


def test_successful_spawn_name_reservation_and_admission_commit() -> None:
    """Test standard two-phase lifecycle: reserve -> durable persistence -> commit."""
    suite = SpawnNameReservationUntilAdmissionDurableSuite()
    parent_session_id = "sess_parent_001"
    spawn_name = "subagent-researcher"

    persisted_log: list[str] = []

    def dummy_storage_writer() -> str:
        durable_sess_id = f"sess_child_{spawn_name}_123"
        persisted_log.append(durable_sess_id)
        return durable_sess_id

    result: AdmissionCommitResult = suite.execute_durable_spawn(
        parent_session_id=parent_session_id,
        spawn_name=spawn_name,
        durable_writer=dummy_storage_writer,
        ttl_ms=30_000,
    )

    assert result.success is True
    assert result.durable_id == "sess_child_subagent-researcher_123"
    assert result.committed_at_epoch_ms is not None
    assert len(persisted_log) == 1

    # Verify underlying engine lease is in COMMITTED_DURABLE state
    lease = suite.engine.get_lease(parent_session_id, spawn_name)
    assert lease is not None
    assert lease.state == ReservationState.COMMITTED_DURABLE
    assert lease.durable_id == "sess_child_subagent-researcher_123"


def test_concurrent_name_collision_rejection() -> None:
    """Test concurrent reservation collision is strictly rejected preventing state corruption."""
    engine = SpawnNameReservationEngine()
    parent_session_id = "sess_parent_002"

    # Operation 1 reserves 'Worker-Alpha'
    res1 = engine.reserve_name(
        parent_session_id=parent_session_id,
        spawn_name="Worker-Alpha",
        ttl_ms=30_000,
        reservation_token="token_op_1",
    )
    assert res1.success is True
    assert res1.lease is not None

    # Operation 2 tries to reserve 'worker-alpha' (case-insensitive clash)
    res2 = engine.reserve_name(
        parent_session_id=parent_session_id,
        spawn_name="worker-alpha",
        ttl_ms=30_000,
        reservation_token="token_op_2",
    )
    assert res2.success is False
    assert res2.lease is None
    assert res2.rejection_reason is not None
    assert "currently held by active reservation" in res2.rejection_reason

    # Clean release from operation 1
    released = engine.release_reservation(res1.lease.reservation_id, "token_op_1")
    assert released is True

    # Now operation 2 can successfully reserve
    res3 = engine.reserve_name(
        parent_session_id=parent_session_id,
        spawn_name="worker-alpha",
        ttl_ms=30_000,
        reservation_token="token_op_2",
    )
    assert res3.success is True


def test_idempotent_reservation_with_same_token() -> None:
    """Test idempotent retry with the exact same reservation token succeeds."""
    engine = SpawnNameReservationEngine()
    parent_session_id = "sess_parent_003"
    shared_token = "idempotent_token_999"

    res_initial = engine.reserve_name(
        parent_session_id=parent_session_id,
        spawn_name="planner-node",
        ttl_ms=10_000,
        reservation_token=shared_token,
    )
    assert res_initial.success is True
    assert res_initial.is_idempotent_replay is False

    # Retry before expiry with identical token
    res_retry = engine.reserve_name(
        parent_session_id=parent_session_id,
        spawn_name="planner-node",
        ttl_ms=10_000,
        reservation_token=shared_token,
    )
    assert res_retry.success is True
    assert res_retry.is_idempotent_replay is True
    assert res_retry.lease is not None
    assert res_retry.lease.reservation_id == res_initial.lease.reservation_id


def test_ttl_expiry_and_failure_rollback() -> None:
    """Test automatic rollback on storage exception and manual TTL expiry eviction."""
    suite = SpawnNameReservationUntilAdmissionDurableSuite()
    parent_session_id = "sess_parent_004"
    spawn_name = "fragile-worker"

    # Simulate storage failure during durable_writer
    def failing_storage_writer() -> str:
        raise IOError("Disk full or database lock timeout")

    fail_res = suite.execute_durable_spawn(
        parent_session_id=parent_session_id,
        spawn_name=spawn_name,
        durable_writer=failing_storage_writer,
    )

    assert fail_res.success is False
    assert fail_res.error_detail is not None
    assert "safely rolled back" in fail_res.error_detail

    # The reservation should have been automatically rolled back
    assert suite.engine.get_lease(parent_session_id, spawn_name) is None

    # Test TTL expiry simulation
    fake_time_start = 1_000_000
    res = suite.engine.reserve_name(
        parent_session_id=parent_session_id,
        spawn_name="transient-worker",
        ttl_ms=5_000,
        current_time_ms=fake_time_start,
    )
    assert res.success is True
    assert res.lease is not None

    # Fast forward 6 seconds: lease is expired
    fake_time_expired = fake_time_start + 6_000
    cleaned = suite.engine.clean_expired_leases(current_time_ms=fake_time_expired)
    assert cleaned == 1
    assert suite.engine.get_lease(parent_session_id, "transient-worker") is None
