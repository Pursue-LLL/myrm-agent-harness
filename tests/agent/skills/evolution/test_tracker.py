from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType, SkillLineage, SkillMetrics, SkillRecord
from myrm_agent_harness.agent.skills.evolution.infra.tracker import SkillExecutionResult, SkillQualityTracker


@pytest.fixture
def mock_store():
    store = MagicMock()
    skill_rec = SkillRecord(
        skill_id="skill1",
        name="test",
        description="test desc",
        content="pass",
        path="test.py",
        lineage=SkillLineage(evolution_type=EvolutionType.FIX),
        metrics=SkillMetrics(),
    )
    store.get_skill.return_value = skill_rec
    store.update_metrics = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_record_execution_success(mock_store):
    tracker = SkillQualityTracker(mock_store)
    metrics = await tracker.record_execution(SkillExecutionResult(skill_id="skill1", success=True))

    assert metrics.success_count == 1
    mock_store.update_metrics.assert_called_once()


@pytest.mark.asyncio
async def test_record_execution_failure(mock_store):
    tracker = SkillQualityTracker(mock_store)
    metrics = await tracker.record_execution(
        SkillExecutionResult(skill_id="skill1", success=False, error_message="failed")
    )

    assert metrics.consecutive_failures == 1
    assert metrics.success_count == 0
    mock_store.update_metrics.assert_called_once()


@pytest.mark.asyncio
async def test_record_execution_not_found(mock_store):
    mock_store.get_skill.return_value = None
    tracker = SkillQualityTracker(mock_store)
    res = SkillExecutionResult(skill_id="skill2", success=True)

    with pytest.raises(ValueError, match="Skill not found"):
        await tracker.record_execution(res)
