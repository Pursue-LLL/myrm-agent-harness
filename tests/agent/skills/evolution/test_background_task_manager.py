import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.infra.background_task_manager import (
    BackgroundEvolutionTaskManager,
)
from myrm_agent_harness.runtime.maintenance.protocols import CapacityDenial, CapacityTicket, MaintenanceTaskType


@pytest.fixture
def scheduler():
    sched = MagicMock()
    sched.request_capacity = AsyncMock(return_value=CapacityTicket(
        ticket_id="test",
        task_type=MaintenanceTaskType.EVOLUTION
    ))
    sched.release_capacity = AsyncMock()
    return sched

@pytest.fixture
def manager(scheduler):
    return BackgroundEvolutionTaskManager(scheduler=scheduler, shutdown_timeout=0.5)

@pytest.mark.asyncio
async def test_schedule_success(manager):
    async def sample_task():
        await asyncio.sleep(0.01)

    task_id = await manager.schedule(
        sample_task(),
        label="test_label",
        trigger_type="test_trigger",
        skill_ids=["skill1"]
    )

    assert task_id is not None
    assert task_id.startswith("test_label_")

    # Check status
    status = manager.get_status()
    assert len(status) == 1
    assert status[0]["task_id"] == task_id
    assert status[0]["label"] == "test_label"

    # Wait for completion
    await manager.wait_all()
    assert manager.count_active() == 0

@pytest.mark.asyncio
async def test_schedule_denial():
    sched = MagicMock()
    sched.request_capacity = AsyncMock(return_value=CapacityDenial(reason="Busy", retry_after_seconds=10))
    mgr = BackgroundEvolutionTaskManager(scheduler=sched)

    async def sample_task():
        pass

    task_id = await mgr.schedule(
        sample_task(),
        label="test_label",
        trigger_type="test_trigger"
    )

    assert task_id is None

@pytest.mark.asyncio
async def test_update_progress(manager):
    async def slow_task():
        await asyncio.sleep(0.1)

    task_id = await manager.schedule(
        slow_task(),
        label="test",
        trigger_type="test"
    )

    await manager.update_progress(task_id, "Running...")
    status = manager.get_status()
    assert status[0]["progress"] == "Running..."

    await manager.wait_all()

@pytest.mark.asyncio
async def test_wait_all_timeout(manager):
    # This manager has shutdown_timeout=0.5
    async def very_slow_task():
        await asyncio.sleep(1.0)

    await manager.schedule(
        very_slow_task(),
        label="slow",
        trigger_type="test"
    )

    result = await manager.wait_all(timeout=0.1)

    assert result["total"] == 1
    assert result["timeout"] == 1
    assert result["completed"] == 0

@pytest.mark.asyncio
async def test_task_exception(manager):
    async def failing_task():
        raise ValueError("Simulated error")

    await manager.schedule(
        failing_task(),
        label="fail",
        trigger_type="test"
    )

    result = await manager.wait_all()
    assert result["failed"] == 1
    assert result["completed"] == 0
