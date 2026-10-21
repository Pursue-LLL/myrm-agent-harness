"""Unit tests for High-Concurrency Swarm & Adaptive Cloud Offload (Item 60).

[INPUT]
- Harness swarm_offload package classes:
  ResourceWatermarkMonitor, SwarmOffloadDispatcher, OffloadStrategy,
  ExecutionTarget, WorkerState, SwarmTaskDefinition.

[OUTPUT]
- Pytest verification for host resource watermark monitoring, 10-15 concurrency
  swarm fan-out, adaptive cloud offloading, force policies, timeout guards, and
  zero-copy artifact pointers.

[POS]
- myrm-agent-harness/tests/agent/sub_agents/test_swarm_offload.py
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.sub_agents.swarm_offload import (
    ExecutionTarget,
    OffloadStrategy,
    ResourceWatermarkMonitor,
    SwarmOffloadDispatcher,
    SwarmTaskDefinition,
    WorkerState,
)


@pytest.fixture
def mock_normal_monitor() -> ResourceWatermarkMonitor:
    """Monitor simulating normal host load."""
    return ResourceWatermarkMonitor(
        cpu_threshold_percent=80.0,
        memory_threshold_percent=80.0,
        max_recommended_local_workers=4,
        custom_sampler=lambda: (25.0, 45.0),
    )


@pytest.fixture
def mock_overloaded_monitor() -> ResourceWatermarkMonitor:
    """Monitor simulating overloaded host load."""
    return ResourceWatermarkMonitor(
        cpu_threshold_percent=80.0,
        memory_threshold_percent=80.0,
        max_recommended_local_workers=4,
        custom_sampler=lambda: (88.0, 85.0),
    )


def test_watermark_normal_load(mock_normal_monitor: ResourceWatermarkMonitor) -> None:
    """Test that normal host load yields false over_watermark and local recommendation."""
    wm = mock_normal_monitor.sample_watermark()
    assert not wm.is_over_watermark
    assert wm.recommendation == ExecutionTarget.LOCAL_HOST
    assert mock_normal_monitor.evaluate_target() == ExecutionTarget.LOCAL_HOST


def test_watermark_overload_cpu() -> None:
    """Test that high CPU utilization triggers over-watermark and cloud recommendation."""
    monitor = ResourceWatermarkMonitor(
        cpu_threshold_percent=80.0,
        memory_threshold_percent=80.0,
        max_recommended_local_workers=4,
        custom_sampler=lambda: (85.5, 50.0),
    )
    wm = monitor.sample_watermark()
    assert wm.is_over_watermark
    assert wm.recommendation == ExecutionTarget.CLOUD_SANDBOX
    assert monitor.evaluate_target() == ExecutionTarget.CLOUD_SANDBOX


def test_watermark_overload_by_active_workers(mock_normal_monitor: ResourceWatermarkMonitor) -> None:
    """Test that exceeding recommended local worker count triggers cloud offload."""
    for _ in range(4):
        mock_normal_monitor.register_local_worker_start()

    wm = mock_normal_monitor.sample_watermark()
    assert wm.is_over_watermark
    assert wm.recommendation == ExecutionTarget.CLOUD_SANDBOX

    mock_normal_monitor.register_local_worker_finish()
    wm_after = mock_normal_monitor.sample_watermark()
    assert not wm_after.is_over_watermark
    assert wm_after.recommendation == ExecutionTarget.LOCAL_HOST


def test_watermark_peaks_and_reset(mock_normal_monitor: ResourceWatermarkMonitor) -> None:
    """Test peak usage tracking and manual reset."""
    mock_normal_monitor.sample_watermark()
    peak_cpu, peak_mem = mock_normal_monitor.get_peak_usage()
    assert peak_cpu == 25.0
    assert peak_mem == 45.0

    mock_normal_monitor.reset_peaks()
    assert mock_normal_monitor.get_peak_usage() == (0.0, 0.0)


@pytest.mark.anyio
async def test_swarm_dispatcher_adaptive_offloading_12_tasks() -> None:
    """Test that 12 concurrent swarm tasks automatically offload once host capacity is reached."""
    # Custom stateful sampler: increments load as local workers increase
    monitor = ResourceWatermarkMonitor(
        cpu_threshold_percent=80.0,
        memory_threshold_percent=80.0,
        max_recommended_local_workers=3,
        custom_sampler=lambda: (30.0 + monitor._active_local_count * 20.0, 40.0),
    )
    dispatcher = SwarmOffloadDispatcher(
        monitor=monitor,
        default_strategy=OffloadStrategy.ADAPTIVE,
        max_concurrency=15,
    )

    tasks = [
        SwarmTaskDefinition(
            task_id=f"task-batch-{i:02d}",
            title=f"Parallel Hypothesis Verification #{i}",
            command_or_prompt=f"run_hypothesis_check_{i}",
        )
        for i in range(12)
    ]

    summary = await dispatcher.dispatch_swarm_batch(tasks)

    assert summary.total_tasks == 12
    assert summary.completed_count == 12
    assert summary.failed_count == 0
    # Both local workers and cloud offloaded workers should have been used
    assert summary.local_workers_count > 0
    assert summary.cloud_workers_count > 0
    assert summary.local_workers_count + summary.cloud_workers_count == 12

    # Check that cloud workers emitted vault:// artifact pointers
    cloud_workers = [w for w in summary.workers if w.execution_target == ExecutionTarget.CLOUD_SANDBOX]
    for cw in cloud_workers:
        assert cw.artifact_pointer is not None
        assert cw.artifact_pointer.startswith("vault://artifacts/")


@pytest.mark.anyio
async def test_swarm_dispatcher_force_cloud_strategy(mock_normal_monitor: ResourceWatermarkMonitor) -> None:
    """Test that FORCE_CLOUD routes 100% of tasks to cloud sandboxes."""
    dispatcher = SwarmOffloadDispatcher(
        monitor=mock_normal_monitor,
        default_strategy=OffloadStrategy.FORCE_CLOUD,
    )
    tasks = [
        SwarmTaskDefinition(
            task_id=f"cloud-task-{i}",
            title=f"Heavy Cloud Build #{i}",
            command_or_prompt="cargo build --release",
        )
        for i in range(5)
    ]

    summary = await dispatcher.dispatch_swarm_batch(tasks)
    assert summary.total_tasks == 5
    assert summary.cloud_workers_count == 5
    assert summary.local_workers_count == 0


@pytest.mark.anyio
async def test_swarm_dispatcher_force_local_strategy(mock_normal_monitor: ResourceWatermarkMonitor) -> None:
    """Test that FORCE_LOCAL routes tasks to local host."""
    dispatcher = SwarmOffloadDispatcher(
        monitor=mock_normal_monitor,
        default_strategy=OffloadStrategy.FORCE_LOCAL,
    )
    tasks = [
        SwarmTaskDefinition(
            task_id=f"local-task-{i}",
            title=f"Quick Local Lint #{i}",
            command_or_prompt="ruff check .",
        )
        for i in range(4)
    ]

    summary = await dispatcher.dispatch_swarm_batch(tasks)
    assert summary.total_tasks == 4
    assert summary.local_workers_count == 4
    assert summary.cloud_workers_count == 0


@pytest.mark.anyio
async def test_swarm_dispatcher_failure_and_timeout(mock_normal_monitor: ResourceWatermarkMonitor) -> None:
    """Test graceful handling of failed tasks and timed-out workers."""

    async def custom_runner(
        task: SwarmTaskDefinition,
        target: ExecutionTarget,
    ) -> tuple[int, str, str | None]:
        if "timeout" in task.command_or_prompt:
            await asyncio.sleep(0.5)  # Will exceed 0.05s timeout
            return (0, "Should have timed out", None)
        if "error" in task.command_or_prompt:
            return (2, "Segmentation fault in worker process", None)
        return (0, "All good", None)

    dispatcher = SwarmOffloadDispatcher(
        monitor=mock_normal_monitor,
        default_strategy=OffloadStrategy.FORCE_LOCAL,
        worker_runner=custom_runner,
    )

    tasks = [
        SwarmTaskDefinition(
            task_id="task-ok",
            title="Good Task",
            command_or_prompt="run ok",
        ),
        SwarmTaskDefinition(
            task_id="task-err",
            title="Failing Task",
            command_or_prompt="run error",
        ),
        SwarmTaskDefinition(
            task_id="task-slow",
            title="Slow Task",
            command_or_prompt="run timeout",
            timeout_seconds=0.05,
        ),
    ]

    summary = await dispatcher.dispatch_swarm_batch(tasks)
    assert summary.total_tasks == 3
    assert summary.completed_count == 1
    assert summary.failed_count == 2

    # Check individual states
    w_map = {w.task_id: w for w in summary.workers}
    assert w_map["task-ok"].state == WorkerState.COMPLETED
    assert w_map["task-err"].state == WorkerState.FAILED
    assert w_map["task-err"].exit_code == 2
    assert w_map["task-slow"].state == WorkerState.TIMED_OUT
    assert w_map["task-slow"].exit_code == 124
