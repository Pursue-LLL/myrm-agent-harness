"""Tests for OptimizationScheduler batch cancellation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.optimization.config import MonitoringConfig, OptimizationConfig
from myrm_agent_harness.agent.skills.optimization.scheduler import OptimizationScheduler
from myrm_agent_harness.agent.skills.optimization.types import SkillQualityScore
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def scheduler() -> OptimizationScheduler:
    config = OptimizationConfig(
        monitoring=MonitoringConfig(circuit_breaker_threshold=5, evaluation_interval=0.1, cooldown_period=3600)
    )
    return OptimizationScheduler(
        optimizer=AsyncMock(),
        execution_provider=AsyncMock(),
        quality_calculator=MagicMock(),
        config=config,
        event_emitter=AsyncMock(),
        anomaly_detector=MagicMock(),
    )


def _setup_skill_mocks(sched: OptimizationScheduler) -> None:
    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    quality = SkillQualityScore(
        success_rate=0.5,
        token_efficiency=0.5,
        execution_time=0.5,
        user_satisfaction=0.5,
        call_frequency=0.5,
    )
    sched.execution_provider.get_skill_metadata = AsyncMock(return_value=metadata)
    sched.execution_provider.get_skill_content = AsyncMock(return_value="# skill")
    mock_sample = MagicMock()
    mock_sample.skill = metadata
    sched.execution_provider.get_skill_executions = AsyncMock(return_value=[mock_sample])
    sched.quality_calculator.calculate = AsyncMock(return_value=quality)


@pytest.mark.asyncio
async def test_cancel_batch_optimization_stops_pending_skills(scheduler: OptimizationScheduler) -> None:
    optimize_started = asyncio.Event()
    release_optimize = asyncio.Event()

    async def slow_optimize(*_args: object, **_kwargs: object) -> MagicMock:
        optimize_started.set()
        await release_optimize.wait()
        return MagicMock(success=True, duration_seconds=1.0, version=2)

    scheduler.optimizer.optimize_skill = AsyncMock(side_effect=slow_optimize)
    _setup_skill_mocks(scheduler)

    batch_id = await scheduler.trigger_batch_optimization(
        ["skill-a", "skill-b", "skill-c"],
        max_concurrent=1,
    )

    await asyncio.wait_for(optimize_started.wait(), timeout=2.0)
    assert await scheduler.cancel_batch_optimization(batch_id) is True
    release_optimize.set()
    await asyncio.sleep(0.3)

    assert scheduler.optimizer.optimize_skill.await_count == 1
    batch_info = scheduler.get_batch_status(batch_id)
    assert batch_info is not None
    assert batch_info["status"] == "cancelled"
    assert batch_id not in scheduler._batch_cancel_tokens


@pytest.mark.asyncio
async def test_cancel_batch_optimization_returns_false_for_unknown_batch(
    scheduler: OptimizationScheduler,
) -> None:
    assert await scheduler.cancel_batch_optimization("batch_missing") is False


@pytest.mark.asyncio
async def test_cancel_batch_optimization_returns_false_when_token_missing(
    scheduler: OptimizationScheduler,
) -> None:
    batch_id = await scheduler.trigger_batch_optimization(["skill-a"], max_concurrent=1)
    scheduler._batch_cancel_tokens.pop(batch_id)
    assert await scheduler.cancel_batch_optimization(batch_id) is False


@pytest.mark.asyncio
async def test_await_batch_optimization_returns_true_when_finished(
    scheduler: OptimizationScheduler,
) -> None:
    scheduler.optimizer.optimize_skill = AsyncMock(
        return_value=MagicMock(success=True, duration_seconds=0.1, version=2)
    )
    _setup_skill_mocks(scheduler)

    batch_id = await scheduler.trigger_batch_optimization(["skill-a"], max_concurrent=1)
    assert await scheduler.await_batch_optimization(batch_id, timeout=5.0) is True


@pytest.mark.asyncio
async def test_await_batch_optimization_returns_false_on_timeout(
    scheduler: OptimizationScheduler,
) -> None:
    release_optimize = asyncio.Event()

    async def slow_optimize(*_args: object, **_kwargs: object) -> MagicMock:
        await release_optimize.wait()
        return MagicMock(success=True, duration_seconds=1.0, version=2)

    scheduler.optimizer.optimize_skill = AsyncMock(side_effect=slow_optimize)
    _setup_skill_mocks(scheduler)

    batch_id = await scheduler.trigger_batch_optimization(["skill-a"], max_concurrent=1)
    assert await scheduler.await_batch_optimization(batch_id, timeout=0.05) is False
    release_optimize.set()


@pytest.mark.asyncio
async def test_cancel_discards_in_flight_optimization_result(
    scheduler: OptimizationScheduler,
) -> None:
    optimize_started = asyncio.Event()
    release_optimize = asyncio.Event()

    async def slow_optimize(*_args: object, **_kwargs: object) -> MagicMock:
        optimize_started.set()
        await release_optimize.wait()
        return MagicMock(success=True, duration_seconds=1.0, version=2)

    scheduler.optimizer.optimize_skill = AsyncMock(side_effect=slow_optimize)
    _setup_skill_mocks(scheduler)

    batch_id = await scheduler.trigger_batch_optimization(["skill-a", "skill-b"], max_concurrent=1)
    await asyncio.wait_for(optimize_started.wait(), timeout=2.0)
    assert await scheduler.cancel_batch_optimization(batch_id) is True
    release_optimize.set()
    await asyncio.sleep(0.3)

    batch_info = scheduler.get_batch_status(batch_id)
    assert batch_info is not None
    assert batch_info["completed"] == 0
    assert batch_info["failed"] >= 1
