"""Unit tests for SubagentHeartbeatTracker and ZombieCleanupSupervisor.

Tests benchmarked against Nous community multi-agent runtime reliability invariants:
1. Heartbeat pulse registration, progress note updating, and tiered health evaluation.
2. Healthy subagent completing execution under active heartbeat maintenance.
3. Unresponsive zombie subagent hard-terminated by watchdog with cleanup hook execution.
4. Watchdog diagnostic markdown report rendering.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.runtime.subagent_watchdog import (
    SubagentHealthState,
    SubagentHeartbeatTracker,
    TimeoutLadderConfig,
    ZombieCleanupSupervisor,
)


def test_subagent_heartbeat_tracker_progression() -> None:
    """Test tiered health evaluation based on simulated elapsed time since last pulse."""
    ladder = TimeoutLadderConfig(
        warning_threshold_s=1.0,
        soft_cancel_threshold_s=2.0,
        hard_terminate_threshold_s=3.0,
    )
    tracker = SubagentHeartbeatTracker(default_ladder=ladder)
    subagent_id = "sub_test_01"

    t0 = 1000.0
    tracker.register(subagent_id, ladder, initial_time=t0)

    # 1. Immediate check at t0: HEALTHY
    state, elapsed = tracker.evaluate_health(subagent_id, current_time=t0 + 0.5)
    assert state == SubagentHealthState.HEALTHY
    assert round(elapsed, 2) == 0.5

    # 2. Check at t0 + 1.2s: WARNING
    state, _ = tracker.evaluate_health(subagent_id, current_time=t0 + 1.2)
    assert state == SubagentHealthState.WARNING

    # 3. Check at t0 + 2.5s: SOFT_CANCELING
    state, _ = tracker.evaluate_health(subagent_id, current_time=t0 + 2.5)
    assert state == SubagentHealthState.SOFT_CANCELING

    # 4. Check at t0 + 3.5s: TERMINATED
    state, _ = tracker.evaluate_health(subagent_id, current_time=t0 + 3.5)
    assert state == SubagentHealthState.TERMINATED

    # 5. Pulse updates vitality
    tracker.pulse(subagent_id, note="Still processing")
    assert tracker.get_pulse_count(subagent_id) == 1

    tracker.unregister(subagent_id)
    assert tracker.get_pulse_count(subagent_id) == 0


@pytest.mark.asyncio
async def test_zombie_cleanup_supervisor_healthy_flow() -> None:
    """Test healthy subagent emitting periodic pulses completes successfully."""
    tracker = SubagentHeartbeatTracker()
    supervisor = ZombieCleanupSupervisor(tracker)

    ladder = TimeoutLadderConfig(
        warning_threshold_s=0.2,
        soft_cancel_threshold_s=0.4,
        hard_terminate_threshold_s=0.6,
    )

    async def healthy_worker() -> str:
        for i in range(3):
            tracker.pulse("sub_healthy", note=f"Step {i}")
            await asyncio.sleep(0.05)
        return "Task Completed"

    state, result, receipt = await supervisor.supervise_task(
        subagent_id="sub_healthy",
        parent_session_id="parent_sess_01",
        coro=healthy_worker(),
        custom_ladder=ladder,
        check_interval_s=0.02,
    )

    assert state == SubagentHealthState.HEALTHY
    assert result == "Task Completed"
    assert receipt.zombie_killed is False
    assert receipt.total_pulses >= 3

    md = supervisor.render_watchdog_markdown(receipt)
    assert "### 🛡️ 子智能体心跳看门狗与僵尸清退审计卡片" in md
    assert "> [!NOTE]" in md


@pytest.mark.asyncio
async def test_zombie_cleanup_supervisor_terminates_zombie_and_calls_hook() -> None:
    """Test unresponsive zombie worker is forcibly reaped and cleanup hook is invoked."""
    tracker = SubagentHeartbeatTracker()
    supervisor = ZombieCleanupSupervisor(tracker)

    # Tight thresholds for rapid test execution
    ladder = TimeoutLadderConfig(
        warning_threshold_s=0.03,
        soft_cancel_threshold_s=0.06,
        hard_terminate_threshold_s=0.10,
    )

    hook_called = False

    def on_zombie_kill() -> None:
        nonlocal hook_called
        hook_called = True

    async def uncooperative_zombie_worker() -> str:
        # Initial pulse, then simulate stuck worker that ignores CancelledError
        tracker.pulse("sub_zombie", note="Starting")
        while True:
            try:
                await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                # Stubborn zombie ignores soft cancel signal until hard killed
                await asyncio.sleep(0.01)

    state, result, receipt = await supervisor.supervise_task(
        subagent_id="sub_zombie",
        parent_session_id="parent_sess_02",
        coro=uncooperative_zombie_worker(),
        cleanup_hook=on_zombie_kill,
        custom_ladder=ladder,
        check_interval_s=0.02,
    )

    assert state == SubagentHealthState.TERMINATED
    assert result == ""
    assert receipt.zombie_killed is True
    assert hook_called is True
    assert "unresponsive zombie" in receipt.degraded_error_summary

    md = supervisor.render_watchdog_markdown(receipt)
    assert "> [!CAUTION]" in md
    assert "子智能体僵尸硬清退告警" in md


@pytest.mark.asyncio
async def test_zombie_cleanup_supervisor_soft_canceling_cooperative() -> None:
    """Test cooperative worker cleanly handles soft cancel when heartbeat warning triggers."""
    tracker = SubagentHeartbeatTracker()
    supervisor = ZombieCleanupSupervisor(tracker)

    ladder = TimeoutLadderConfig(
        warning_threshold_s=0.03,
        soft_cancel_threshold_s=0.06,
        hard_terminate_threshold_s=0.20,
    )

    async def cooperative_worker() -> str:
        tracker.pulse("sub_coop", note="Starting")
        # Sleeps longer than soft_cancel_threshold_s, but cleanly accepts CancelledError
        await asyncio.sleep(0.5)
        return "Not Reached"

    state, result, receipt = await supervisor.supervise_task(
        subagent_id="sub_coop",
        parent_session_id="parent_sess_03",
        coro=cooperative_worker(),
        custom_ladder=ladder,
        check_interval_s=0.02,
    )

    assert state == SubagentHealthState.SOFT_CANCELING
    assert result == ""
    assert receipt.zombie_killed is False
    assert "cancelled due to heartbeat warning" in receipt.degraded_error_summary
