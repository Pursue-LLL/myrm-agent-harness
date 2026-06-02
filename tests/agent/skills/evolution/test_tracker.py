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
        metrics=SkillMetrics()
    )
    store.get_skill.return_value = skill_rec
    store.save_analysis = AsyncMock()
    store.update_metrics = AsyncMock()
    store.get_skills_needing_fix.return_value = [skill_rec]
    store.get_active_skills.return_value = [skill_rec]
    return store

@pytest.mark.asyncio
async def test_record_execution_success(mock_store):
    tracker = SkillQualityTracker(mock_store)
    res = SkillExecutionResult(
        skill_id="skill1",
        success=True,
        context={"task_id": "t1"}
    )
    metrics = await tracker.record_execution(res)

    assert metrics.success_count == 1
    mock_store.save_analysis.assert_called_once()
    mock_store.update_metrics.assert_called_once()

@pytest.mark.asyncio
async def test_record_execution_failure(mock_store):
    tracker = SkillQualityTracker(mock_store)
    res = SkillExecutionResult(
        skill_id="skill1",
        success=False,
        error_message="failed",
        context={"task_id": "t1"}
    )
    metrics = await tracker.record_execution(res)

    assert metrics.consecutive_failures == 1
    mock_store.save_analysis.assert_called_once()
    mock_store.update_metrics.assert_called_once()

@pytest.mark.asyncio
async def test_record_execution_not_found(mock_store):
    mock_store.get_skill.return_value = None
    tracker = SkillQualityTracker(mock_store)
    res = SkillExecutionResult(skill_id="skill2", success=True)

    with pytest.raises(ValueError, match="Skill not found"):
        await tracker.record_execution(res)

@pytest.mark.asyncio
async def test_get_skills_needing_fix(mock_store):
    tracker = SkillQualityTracker(mock_store)
    skills = await tracker.get_skills_needing_fix(0.6)

    assert len(skills) == 1
    mock_store.get_skills_needing_fix.assert_called_with(0.6)

def test_get_quality_report(mock_store):
    tracker = SkillQualityTracker(mock_store)
    report = tracker.get_quality_report()

    assert report["total_skills"] == 1
    assert report["total_executions"] == 0
    assert "avg_success_rate" in report

def test_get_quality_report_empty(mock_store):
    mock_store.get_active_skills.return_value = []
    tracker = SkillQualityTracker(mock_store)
    report = tracker.get_quality_report()

    assert report["total_skills"] == 0
    assert report["avg_success_rate"] == 0.0

@pytest.mark.asyncio
async def test_batch_record_executions(mock_store):
    tracker = SkillQualityTracker(mock_store)

    res1 = SkillExecutionResult(skill_id="skill1", success=True)
    res2 = SkillExecutionResult(skill_id="skill_missing", success=True)

    # We need to simulate that skill_missing throws ValueError, but skill1 succeeds.
    def get_skill_side_effect(skill_id):
        if skill_id == "skill1":
            return SkillRecord(
                skill_id="skill1", name="test", description="test", content="pass",
                path="test.py", lineage=SkillLineage(evolution_type=EvolutionType.FIX), metrics=SkillMetrics()
            )
        return None
    mock_store.get_skill.side_effect = get_skill_side_effect

    updated = await tracker.batch_record_executions([res1, res2])

    assert len(updated) == 1
    assert "skill1" in updated
    assert updated["skill1"].success_count == 1
