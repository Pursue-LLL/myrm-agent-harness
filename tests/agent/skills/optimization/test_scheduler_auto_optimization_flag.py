"""enable_auto_optimization gates only the periodic evaluation, never an explicit trigger."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.optimization.config import OptimizationConfig
from myrm_agent_harness.agent.skills.optimization.scheduler import OptimizationScheduler
from myrm_agent_harness.agent.skills.optimization.types import SkillQualityScore
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture
def scheduler() -> OptimizationScheduler:
    return OptimizationScheduler(
        optimizer=AsyncMock(),
        execution_provider=AsyncMock(),
        quality_calculator=MagicMock(),
        config=OptimizationConfig(enable_auto_optimization=False),
        event_emitter=AsyncMock(),
        anomaly_detector=MagicMock(),
    )


@pytest.mark.asyncio
async def test_periodic_evaluation_skips_every_provider_call(scheduler: OptimizationScheduler) -> None:
    scheduler.execution_provider.get_all_skill_ids = AsyncMock(return_value=["skill_1"])
    scheduler._evaluate_skill = AsyncMock()
    scheduler._detect_and_handle_anomalies = AsyncMock()

    await scheduler._evaluate_all_skills()

    scheduler.execution_provider.get_all_skill_ids.assert_not_called()
    scheduler._evaluate_skill.assert_not_called()
    scheduler._detect_and_handle_anomalies.assert_not_called()


@pytest.mark.asyncio
async def test_manual_trigger_still_queues(scheduler: OptimizationScheduler) -> None:
    metadata = SkillMetadata(name="skill_1", description="desc", storage_skill_id="1")
    low_quality = SkillQualityScore(
        success_rate=0.1, token_efficiency=0.1, execution_time=0.1, user_satisfaction=0.1, call_frequency=0.1
    )

    queued = await scheduler.trigger_optimization(metadata, low_quality)

    assert queued is True
    assert scheduler._optimization_queue.qsize() == 1
