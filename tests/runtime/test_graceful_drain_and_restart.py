"""Unit tests for multi-service graceful drain and session-preserving restart suite.

Verifies:
- Task registration, in-flight counting, and leaf task continuation during drain.
- Rejection of new root tasks once drain is initiated (ServiceDrainingError).
- Drain notice broadcast to registered client-facing listeners.
- Bounded drain waiting with timeout handling.
- Independent process and health endpoint verification (verified, relaunch_attempted, failed).
- Full restart cycle execution with success settlement.
- Automatic rollback protection and service drain cancellation when launch/verify fails.
"""

from __future__ import annotations

import asyncio
import os

import pytest

from myrm_agent_harness.runtime.drain_and_restart import (
    CleanRestartStateMachine,
    DrainNotice,
    GracefulDrainCoordinator,
    RestartVerifier,
    ServiceDrainingError,
)


@pytest.mark.asyncio
async def test_task_tracking_and_drain_barrier() -> None:
    coordinator = GracefulDrainCoordinator("gateway_service")
    assert coordinator.state == "RUNNING"
    assert coordinator.in_flight_count == 0

    # Normal tracking of root and leaf tasks
    async with coordinator.track_task("root-1", "agent_run"):
        assert coordinator.in_flight_count == 1
        async with coordinator.track_task("leaf-1", "tool_call", is_leaf=True):
            assert coordinator.in_flight_count == 2
        assert coordinator.in_flight_count == 1
    assert coordinator.in_flight_count == 0

    # Initiate drain
    await coordinator.initiate_drain("scheduled_maintenance", drain_budget_seconds=10.0)
    assert coordinator.state == "DRAINED"

    # New root task must be rejected
    with pytest.raises(ServiceDrainingError):
        async with coordinator.track_task("root-rejected", "agent_run", is_leaf=False):
            pass

    # Cancel drain restores normal operation (rollback)
    await coordinator.cancel_drain()
    assert coordinator.state == "RUNNING"
    async with coordinator.track_task("root-allowed", "agent_run"):
        assert coordinator.in_flight_count == 1


@pytest.mark.asyncio
async def test_drain_notice_broadcast_and_leaf_continuation() -> None:
    coordinator = GracefulDrainCoordinator("api_service")
    received_notices: list[DrainNotice] = []

    async def _on_drain(notice: DrainNotice) -> None:
        received_notices.append(notice)

    coordinator.register_drain_listener(_on_drain)

    # Start long-running task
    task_started = asyncio.Event()
    task_finish = asyncio.Event()

    async def _worker() -> None:
        async with coordinator.track_task("long-task-1"):
            task_started.set()
            await task_finish.wait()

    worker_coro = asyncio.create_task(_worker())
    await task_started.wait()

    # Initiate drain while task is active
    notice = await coordinator.initiate_drain("rolling_update", drain_budget_seconds=5.0)
    assert coordinator.state == "DRAINING"
    assert len(received_notices) == 1
    assert received_notices[0].notice_id == notice.notice_id
    assert received_notices[0].in_flight_count == 1

    # While draining, leaf subtask of ongoing task is allowed
    async with coordinator.track_task("leaf-substep", "write_tool", is_leaf=True):
        assert coordinator.in_flight_count == 2

    # Finish worker task
    task_finish.set()
    await worker_coro
    assert coordinator.in_flight_count == 0
    assert coordinator.state == "DRAINED"


@pytest.mark.asyncio
async def test_drain_wait_timeout() -> None:
    coordinator = GracefulDrainCoordinator("worker_service")
    task_hang = asyncio.Event()

    async def _hung_worker() -> None:
        async with coordinator.track_task("hung-task"):
            await task_hang.wait()

    hang_task = asyncio.create_task(_hung_worker())
    await asyncio.sleep(0.01)

    await coordinator.initiate_drain("timeout_test", drain_budget_seconds=0.05)
    # Drain wait should timeout cleanly and return False without hanging
    clean = await coordinator.wait_for_drain(timeout_seconds=0.05)
    assert not clean

    # Cleanup hung task
    task_hang.set()
    await hang_task


@pytest.mark.asyncio
async def test_restart_verifier_outcomes() -> None:
    verifier = RestartVerifier()
    current_pid = os.getpid()

    # 1. PID liveness probe
    assert verifier.is_pid_alive(current_pid)
    assert not verifier.is_pid_alive(-99999)

    # 2. No probe configured -> relaunch_attempted
    outcome_no_probe, _ = await verifier.verify_generation(current_pid, probe_callback=None)
    assert outcome_no_probe == "relaunch_attempted"

    # 3. Healthy probe with matched version -> verified
    async def _healthy_probe(_pid: int) -> tuple[bool, str | None]:
        return True, "v2.5.0"

    outcome_ok, _ = await verifier.verify_generation(
        current_pid,
        probe_callback=_healthy_probe,
        expected_version="v2.5.0",
        timeout_seconds=0.5,
    )
    assert outcome_ok == "verified"

    # 4. Version mismatch -> failed
    outcome_mismatch, reason = await verifier.verify_generation(
        current_pid,
        probe_callback=_healthy_probe,
        expected_version="v2.6.0",
        timeout_seconds=0.5,
    )
    assert outcome_mismatch == "failed"
    assert reason is not None
    assert "Version mismatch" in reason

    # 5. Unhealthy probe -> failed
    async def _failing_probe(_pid: int) -> tuple[bool, str | None]:
        return False, None

    outcome_fail, _ = await verifier.verify_generation(
        current_pid,
        probe_callback=_failing_probe,
        timeout_seconds=0.1,
        probe_interval=0.02,
    )
    assert outcome_fail == "failed"


@pytest.mark.asyncio
async def test_restart_state_machine_successful_cycle() -> None:
    coordinator = GracefulDrainCoordinator("gateway")
    sm = CleanRestartStateMachine(coordinator=coordinator)
    current_pid = os.getpid()

    decommissioned_pids: list[int] = []

    async def _fake_launcher() -> int:
        return current_pid

    async def _healthy_probe(_pid: int) -> tuple[bool, str | None]:
        return True, "v3.0.0"

    async def _decommission(pid: int) -> None:
        decommissioned_pids.append(pid)

    receipt = await sm.execute_restart_cycle(
        reason="deploy_v3",
        drain_budget_seconds=2.0,
        expected_version="v3.0.0",
        launcher=_fake_launcher,
        health_probe=_healthy_probe,
        decommission_old=_decommission,
        current_pid=current_pid,
    )

    assert receipt.outcome == "verified"
    assert receipt.state == "VERIFIED"
    assert receipt.expected_version == "v3.0.0"
    assert receipt.error is None
    assert receipt.new_pid == current_pid


@pytest.mark.asyncio
async def test_restart_state_machine_launch_failure_and_rollback() -> None:
    coordinator = GracefulDrainCoordinator("gateway")
    sm = CleanRestartStateMachine(coordinator=coordinator)

    async def _crashing_launcher() -> int:
        raise RuntimeError("spawn failed: executable missing")

    receipt = await sm.execute_restart_cycle(
        reason="broken_deploy",
        drain_budget_seconds=2.0,
        expected_version="v3.1.0",
        launcher=_crashing_launcher,
    )

    assert receipt.outcome == "failed"
    assert receipt.state == "FAILED"
    assert receipt.error is not None
    assert "spawn failed" in receipt.error
    # Rollback must have cancelled drain and restored RUNNING state
    assert coordinator.state == "RUNNING"


@pytest.mark.asyncio
async def test_restart_state_machine_verify_failure_and_rollback() -> None:
    coordinator = GracefulDrainCoordinator("gateway")
    sm = CleanRestartStateMachine(coordinator=coordinator)

    async def _fake_launcher() -> int:
        return os.getpid()

    async def _unhealthy_probe(_pid: int) -> tuple[bool, str | None]:
        return False, "unhealthy_state"

    receipt = await sm.execute_restart_cycle(
        reason="failing_probe_deploy",
        drain_budget_seconds=2.0,
        expected_version="v3.2.0",
        launcher=_fake_launcher,
        health_probe=_unhealthy_probe,
        verification_timeout=0.1,
    )

    assert receipt.outcome == "failed"
    assert receipt.state == "FAILED"
    assert receipt.error is not None
    # Rollback must restore RUNNING state
    assert coordinator.state == "RUNNING"
