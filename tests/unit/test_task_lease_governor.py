"""Unit tests for TaskLeaseGovernor and CascadeTerminationExecutor.

[POS]
Validates in-flight task micro-lease management, reverse resource indexing,
execution-time lease assertions, and 3-level cascade termination upon security revocation.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from myrm_agent_harness.agent.security.lease import (
    LeaseTicket,
    RevocationEvent,
    RevocationSubjectType,
    RevocationTerminatedError,
    TaskLeaseGovernor,
)


@pytest.fixture(autouse=True)
def reset_governor() -> None:
    """Reset singleton governor before each test."""
    TaskLeaseGovernor.reset_instance()


@pytest.mark.asyncio
async def test_acquire_and_renew_lease_success() -> None:
    """Ensure task can acquire and renew valid micro-leases."""
    governor = TaskLeaseGovernor.get_instance()
    task_id = "task-001"
    resources = {"credential:vault_key_1", "resource:db_prod"}

    ticket = governor.acquire_lease(task_id=task_id, bound_resources=resources, ttl_seconds=10.0)
    assert ticket.task_id == task_id
    assert ticket.bound_resources == frozenset(resources)
    assert not ticket.is_expired

    # Assert lease is valid
    governor.assert_lease_valid(task_id)

    # Renew lease
    renewed = governor.renew_lease(task_id, ttl_seconds=20.0)
    assert renewed is True
    governor.assert_lease_valid(task_id)


@pytest.mark.asyncio
async def test_lease_not_found_or_expired_raises_revocation_error() -> None:
    """Ensure non-existent or expired leases raise RevocationTerminatedError."""
    governor = TaskLeaseGovernor.get_instance()

    # 1. Unregistered task
    with pytest.raises(RevocationTerminatedError) as exc_info:
        governor.assert_lease_valid("non_existent_task")
    assert "No active lease ticket held" in str(exc_info.value)

    # 2. Expired lease
    task_id = "task-expired"
    governor.acquire_lease(task_id=task_id, bound_resources={"res:1"}, ttl_seconds=-1.0)
    with pytest.raises(RevocationTerminatedError) as exc_info2:
        governor.assert_lease_valid(task_id)
    assert "Task lease expired" in str(exc_info2.value)


@pytest.mark.asyncio
async def test_revocation_broadcast_cascade_kills_in_flight_task() -> None:
    """Ensure revocation broadcast cancels asyncio.Task, executes scrub hooks, and clears leases."""
    governor = TaskLeaseGovernor.get_instance()
    task_id = "task-in-flight"
    credential_id = "cred:github_pat_123"

    governor.acquire_lease(task_id=task_id, bound_resources={credential_id}, ttl_seconds=30.0)

    # Create dummy in-flight task that sleeps
    async def dummy_in_flight_work() -> None:
        await asyncio.sleep(10.0)

    loop_task = asyncio.create_task(dummy_in_flight_work())

    scrub_called = False

    def on_scrub() -> None:
        nonlocal scrub_called
        scrub_called = True

    governor.register_task(
        task_id=task_id,
        asyncio_task=loop_task,
        scrub_hooks=[on_scrub],
    )

    # Trigger revocation for the bound credential
    revocation_event = RevocationEvent(
        subject_type=RevocationSubjectType.CREDENTIAL,
        subject_id=credential_id,
        reason="Compromised token detected",
    )

    terminated_count = await governor.revoke_subject(revocation_event)
    assert terminated_count == 1

    # Verify task was cancelled
    assert loop_task.cancelled() or loop_task.cancelling() > 0

    # Verify scrub hook was executed
    assert scrub_called is True

    # Verify lease was revoked
    with pytest.raises(RevocationTerminatedError):
        governor.assert_lease_valid(task_id)


@pytest.mark.asyncio
async def test_release_task_cleans_up_indexes() -> None:
    """Ensure release_task properly removes leases and reverse indexes to prevent memory leaks."""
    governor = TaskLeaseGovernor.get_instance()
    task_id = "task-to-release"
    res_id = "resource:shared_table"

    governor.acquire_lease(task_id=task_id, bound_resources={res_id}, ttl_seconds=30.0)
    assert res_id in governor._resource_index
    assert task_id in governor._resource_index[res_id]

    governor.release_task(task_id)
    assert task_id not in governor._leases
    assert res_id not in governor._resource_index
