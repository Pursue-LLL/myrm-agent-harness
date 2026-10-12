"""Skill execution ledger: outcomes are counted exactly, also under concurrency and commit retries."""

import asyncio
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from myrm_agent_harness.agent.skills.evolution.core.types import EvolutionType, SkillLineage, SkillRecord
from myrm_agent_harness.agent.skills.evolution.db import store as store_module
from myrm_agent_harness.agent.skills.evolution.db.store import SkillStore
from myrm_agent_harness.agent.skills.evolution.infra.tracker import SkillExecutionResult, SkillQualityTracker


@pytest.fixture
async def store(tmp_path: Path):
    skill_store = SkillStore(tmp_path / "skills.db")
    await skill_store.save_skill(
        SkillRecord(
            skill_id="skill1",
            name="test",
            description="test desc",
            content="pass",
            path="test.py",
            lineage=SkillLineage(evolution_type=EvolutionType.FIX),
        )
    )
    yield skill_store
    skill_store.close()


def _metrics(store: SkillStore):
    skill = store.get_skill("skill1")
    assert skill is not None
    return skill.metrics


@pytest.mark.asyncio
async def test_success_is_counted_and_resets_the_failure_streak(store):
    tracker = SkillQualityTracker(store)
    await tracker.record_execution(SkillExecutionResult(skill_id="skill1", success=False, error_message="boom"))
    await tracker.record_execution(SkillExecutionResult(skill_id="skill1", success=False))
    assert _metrics(store).consecutive_failures == 2

    await tracker.record_execution(SkillExecutionResult(skill_id="skill1", success=True))

    metrics = _metrics(store)
    assert (metrics.total_selections, metrics.applied_count, metrics.completed_count) == (3, 3, 3)
    assert metrics.success_count == 1
    assert metrics.consecutive_failures == 0
    assert metrics.last_success_at is not None
    assert metrics.last_failure_at is not None
    assert metrics.effective_rate == pytest.approx(1 / 3)


@pytest.mark.asyncio
async def test_failure_is_counted_without_a_success(store):
    tracker = SkillQualityTracker(store)

    await tracker.record_execution(SkillExecutionResult(skill_id="skill1", success=False, error_message="failed"))

    metrics = _metrics(store)
    assert metrics.applied_count == 1
    assert metrics.success_count == 0
    assert metrics.consecutive_failures == 1
    assert metrics.last_success_at is None
    assert metrics.last_failure_at is not None


@pytest.mark.asyncio
async def test_concurrent_outcomes_are_all_counted(store):
    """Every outcome must land: concurrent callers may not overwrite one another's increments."""
    tracker = SkillQualityTracker(store)
    outcomes = [index % 5 < 3 for index in range(50)]  # 30 successes, 20 failures, interleaved

    await asyncio.gather(
        *(tracker.record_execution(SkillExecutionResult(skill_id="skill1", success=ok)) for ok in outcomes)
    )

    metrics = _metrics(store)
    assert metrics.applied_count == 50
    assert metrics.total_selections == 50
    assert metrics.completed_count == 50
    assert metrics.success_count == 30


@pytest.mark.asyncio
async def test_retried_commit_counts_the_outcome_once(store, monkeypatch):
    """A commit blocked by a reader is retried by the store; the retry must not stack a second increment."""
    # Rollback-journal mode: a reader's shared lock blocks the writer's COMMIT, not its UPDATE.
    store._conn.execute("PRAGMA journal_mode=DELETE")
    store._conn.execute("PRAGMA busy_timeout=50")
    reader = sqlite3.connect(store.db_path, isolation_level=None, check_same_thread=False)
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM skills").fetchall()
    retries: list[float] = []

    def release_reader_before_retry(delay: float) -> None:
        retries.append(delay)
        reader.execute("ROLLBACK")

    monkeypatch.setattr(store_module, "time", SimpleNamespace(sleep=release_reader_before_retry))

    await SkillQualityTracker(store).record_execution(SkillExecutionResult(skill_id="skill1", success=True))
    reader.close()

    assert len(retries) == 1, "the first commit must have been blocked"
    metrics = _metrics(store)
    assert (metrics.total_selections, metrics.applied_count, metrics.success_count) == (1, 1, 1)


@pytest.mark.asyncio
async def test_unknown_skill_raises(store):
    tracker = SkillQualityTracker(store)

    with pytest.raises(ValueError, match="Skill not found"):
        await tracker.record_execution(SkillExecutionResult(skill_id="missing", success=True))
