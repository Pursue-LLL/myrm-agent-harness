import copy
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import (
    EvolutionType,
    ExecutionAnalysis,
    SkillLineage,
    SkillMetrics,
    SkillRecord,
)
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore


@pytest.fixture
def temp_db_path(tmp_path: Path):
    return tmp_path / "test_skills.db"

@pytest.fixture
def skill_record():
    return SkillRecord(
        skill_id="test_skill_1",
        name="test_skill",
        description="A test skill",
        content="def test(): pass",
        path="skills/test_skill.py",
        lineage=SkillLineage(
            evolution_type=EvolutionType.DERIVED,
            version=1,
            parent_id=None,
            change_summary="init"
        ),
        metrics=SkillMetrics(),
        traps=[],
        verification_steps=[],
    )

def test_store_init(temp_db_path):
    store = SkillStore(db_path=temp_db_path)
    assert temp_db_path.exists()
    store.close()

@pytest.mark.asyncio
async def test_save_and_get_skill(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    retrieved = store.get_skill("test_skill_1")
    assert retrieved is not None
    assert retrieved.name == "test_skill"
    assert retrieved.content == "def test(): pass"

    store.close()

@pytest.mark.asyncio
async def test_get_skill_by_name_version(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    retrieved = store.get_skill_by_name_version("test_skill", 1)
    assert retrieved is not None
    assert retrieved.skill_id == "test_skill_1"

    store.close()

@pytest.mark.asyncio
async def test_deactivate_skill(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    await store.deactivate_skill("test_skill_1")
    retrieved = store.get_skill("test_skill_1")
    assert retrieved is not None
    assert retrieved.is_active is False

    store.close()

@pytest.mark.asyncio
async def test_update_metrics(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    new_metrics = SkillMetrics(success_count=5)
    await store.update_metrics("test_skill_1", new_metrics)

    retrieved = store.get_skill("test_skill_1")
    assert retrieved.metrics.success_count == 5

    store.close()

@pytest.mark.asyncio
async def test_get_active_skills(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    active = store.get_active_skills()
    assert len(active) == 1
    assert active[0].skill_id == "test_skill_1"

    await store.deactivate_skill("test_skill_1")
    active2 = store.get_active_skills()
    assert len(active2) == 0
    store.close()

@pytest.mark.asyncio
async def test_get_skills_needing_fix(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    # Needs 3 consecutive failures to trigger without usage count
    skill_record.metrics.consecutive_failures = 3
    await store.save_skill(skill_record)

    needing_fix = store.get_skills_needing_fix()
    assert len(needing_fix) == 1
    assert needing_fix[0].skill_id == "test_skill_1"
    store.close()

@pytest.mark.asyncio
async def test_get_skill_lineage(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    lineage = store.get_skill_lineage("test_skill_1")
    assert len(lineage) == 1
    assert lineage[0].skill_id == "test_skill_1"
    store.close()

@pytest.mark.asyncio
async def test_search_skills_sync(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    res = store._search_skills_sync("test")
    assert len(res) == 1

    res2 = store._search_skills_sync("not_found")
    assert len(res2) == 0
    store.close()

@pytest.mark.asyncio
async def test_search_skills_async(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    # This falls back to sqlite sync because we don't configure qdrant in tests usually
    res = await store.search_skills("test")
    assert len(res) == 1
    store.close()

@pytest.mark.asyncio
async def test_get_recent_analyses_grouped(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    analysis = ExecutionAnalysis(
        skill_id="test_skill_1",
        task_id="task_1",
        success=False,
        error_message="test error",
        root_cause="test cause",
        suggested_fix="test fix"
    )
    await store.save_analysis(analysis)

    groups = store.get_recent_analyses_grouped(days=1)
    assert "test_skill_1" in groups
    assert len(groups["test_skill_1"]) == 1
    assert groups["test_skill_1"][0]["error_message"] == "test error"
    store.close()
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    analysis = ExecutionAnalysis(
        skill_id="test_skill_1",
        task_id="task_1",
        success=False,
        error_message="test error",
        root_cause="bug",
        suggested_fix="fix it",
        task_context='{"k":"v"}',
        analyzed_at=datetime.now()
    )
    await store.save_analysis(analysis)

    logs = await store.load_analyses("test_skill_1")
    assert len(logs) == 2
    assert logs[0].root_cause == "bug"

    store.close()

@pytest.mark.asyncio
async def test_evolution_rejections(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    await store.save_evolution_rejection(
        skill_id="test_skill_1",
        trigger_type="cooldown",
        proposed_type="FIX",
        rejection_reason="too soon",
        confidence=0.8,
        trigger_context='{"k":"v"}'
    )

    rejections = store.load_rejections("test_skill_1")
    assert len(rejections) == 1
    assert rejections[0]["rejection_reason"] == "too soon"

    store.close()

@pytest.mark.asyncio
async def test_evolution_constraints(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    await store.add_evolution_constraint("test_skill_1", "Must not use os.system")

    constraints = store.get_evolution_constraints("test_skill_1")
    assert len(constraints) == 1
    assert constraints[0] == "Must not use os.system"

    store.close()

@pytest.mark.asyncio
async def test_vector_sync(temp_db_path, skill_record):
    mock_vector = AsyncMock()
    mock_embedding = AsyncMock()
    mock_embedding.embed = AsyncMock(return_value=[0.1, 0.2])
    store = SkillStore(db_path=temp_db_path, vector_store=mock_vector, embedding=mock_embedding)

    await store.save_skill(skill_record)
    mock_vector.upsert.assert_called_once()

    await store.deactivate_skill("test_skill_1")
    mock_vector.delete.assert_called_once()

    store.close()

@pytest.mark.asyncio
async def test_delete_skill(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(skill_record)

    await store.delete_skill("test_skill_1")
    retrieved = store.get_skill("test_skill_1")
    assert retrieved is None

    store.close()

@pytest.mark.asyncio
async def test_delete_skills_by_agent(temp_db_path, skill_record):
    from myrm_agent_harness.agent.skills.evolution.core.types import EnvironmentFingerprint
    store = SkillStore(db_path=temp_db_path)
    skill_record.environment = EnvironmentFingerprint()
    skill_record.environment.custom_tags["scope_agent_id"] = "agent_x"
    # Ensure a valid path exists for rmtree to skip safely without blowing up
    skill_record.path = str(temp_db_path.parent / "skills" / "test_skill" / "SKILL.md")
    # create the path
    p = Path(skill_record.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("test")

    await store.save_skill(skill_record)

    # test another agent
    assert await store.delete_skills_by_agent("agent_y") == 0
    assert store.get_skill("test_skill_1") is not None

    # test correct agent
    count = await store.delete_skills_by_agent("agent_x")
    assert count == 1
    assert store.get_skill("test_skill_1") is None
    # Verify the physical file is deleted
    assert not p.exists()

    store.close()

@pytest.mark.asyncio
async def test_save_skills_batch(temp_db_path, skill_record):
    store = SkillStore(db_path=temp_db_path)
    # Create multiple records
    records = []
    for i in range(5):
        r = copy.deepcopy(skill_record)
        r.skill_id = f"batch_skill_{i}"
        r.name = f"Batch Skill {i}"
        records.append(r)

    await store.save_skills_batch(records)

    # Verify all were saved
    for i in range(5):
        s = store.get_skill(f"batch_skill_{i}")
        assert s is not None
        assert s.name == f"Batch Skill {i}"

    store.close()


@pytest.mark.asyncio
async def test_save_skills_batch_rejects_oversized_content(
    temp_db_path, skill_record
):
    store = SkillStore(db_path=temp_db_path)
    oversized = copy.deepcopy(skill_record)
    oversized.skill_id = "oversized_skill"
    oversized.content = "x" * (SkillStore.MAX_SKILL_CONTENT_CHARS + 1)

    with pytest.raises(ValueError, match="too large"):
        await store.save_skills_batch([oversized])

    assert store.get_skill("oversized_skill") is None
    store.close()


@pytest.mark.asyncio
async def test_eval_cases_persistence(temp_db_path):
    """Verify eval_cases survive a save -> close -> reopen -> get cycle."""
    eval_cases = [
        {"sandbox_assertions": [{"type": "code_contains", "target": "nginx"}]},
        {"expected_tools": ["shell"]},
    ]
    record = SkillRecord(
        skill_id="eval_persist_1",
        name="eval-persist-skill",
        description="Test eval_cases persistence",
        content="install nginx",
        path="skills/eval_persist.md",
        lineage=SkillLineage(
            evolution_type=EvolutionType.CAPTURED,
            version=1,
        ),
        eval_cases=eval_cases,
    )

    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(record)
    store.close()

    store2 = SkillStore(db_path=temp_db_path)
    loaded = store2.get_skill("eval_persist_1")
    assert loaded is not None
    assert loaded.eval_cases == eval_cases
    assert loaded.eval_cases[0]["sandbox_assertions"][0]["target"] == "nginx"
    assert loaded.eval_cases[1]["expected_tools"] == ["shell"]
    store2.close()


@pytest.mark.asyncio
async def test_eval_cases_empty_list_persistence(temp_db_path):
    """Verify eval_cases=[] persists correctly (default case)."""
    record = SkillRecord(
        skill_id="eval_empty_1",
        name="no-eval-skill",
        description="Skill without eval_cases",
        content="just content",
        path="skills/no_eval.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, version=1),
    )

    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(record)
    store.close()

    store2 = SkillStore(db_path=temp_db_path)
    loaded = store2.get_skill("eval_empty_1")
    assert loaded is not None
    assert loaded.eval_cases == []
    store2.close()


@pytest.mark.asyncio
async def test_eval_cases_unicode_persistence(temp_db_path):
    """Verify eval_cases with Unicode content persist correctly."""
    eval_cases = [
        {"sandbox_assertions": [{"type": "code_contains", "target": "安装nginx"}]},
        {"sandbox_assertions": [{"type": "code_not_contains", "target": "删除数据库"}]},
    ]
    record = SkillRecord(
        skill_id="eval_unicode_1",
        name="unicode-skill",
        description="Skill with Unicode eval_cases",
        content="安装 nginx 服务器",
        path="skills/unicode.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, version=1),
        eval_cases=eval_cases,
    )

    store = SkillStore(db_path=temp_db_path)
    await store.save_skill(record)
    store.close()

    store2 = SkillStore(db_path=temp_db_path)
    loaded = store2.get_skill("eval_unicode_1")
    assert loaded is not None
    assert loaded.eval_cases == eval_cases
    assert loaded.eval_cases[0]["sandbox_assertions"][0]["target"] == "安装nginx"
    store2.close()


@pytest.mark.asyncio
async def test_eval_cases_batch_save_persistence(temp_db_path):
    """Verify eval_cases persist correctly through batch save."""
    import copy

    base_record = SkillRecord(
        skill_id="batch_eval_0",
        name="batch-eval-0",
        description="Batch test",
        content="content",
        path="skills/batch.md",
        lineage=SkillLineage(evolution_type=EvolutionType.CAPTURED, version=1),
        eval_cases=[{"sandbox_assertions": [{"type": "ast_valid"}]}],
    )

    records = []
    for i in range(3):
        r = copy.deepcopy(base_record)
        r.skill_id = f"batch_eval_{i}"
        r.name = f"batch-eval-{i}"
        r.eval_cases = [{"sandbox_assertions": [{"type": "code_contains", "target": f"key_{i}"}]}]
        records.append(r)

    store = SkillStore(db_path=temp_db_path)
    await store.save_skills_batch(records)
    store.close()

    store2 = SkillStore(db_path=temp_db_path)
    for i in range(3):
        loaded = store2.get_skill(f"batch_eval_{i}")
        assert loaded is not None
        assert loaded.eval_cases[0]["sandbox_assertions"][0]["target"] == f"key_{i}"
    store2.close()
