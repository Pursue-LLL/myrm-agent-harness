from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.skills.curator.engine import SkillCurator
from myrm_agent_harness.backends.skills.curator_config import CuratorConfig
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillUsageStats,
)


@pytest.fixture
def temp_skills_dir(tmp_path: Path) -> Path:
    return tmp_path / "skills"


@pytest.fixture
def stats_collector(temp_skills_dir: Path) -> SkillStatsCollector:
    temp_skills_dir.mkdir(parents=True, exist_ok=True)
    return SkillStatsCollector()


@pytest.fixture
def curator(stats_collector: SkillStatsCollector) -> SkillCurator:
    config = CuratorConfig(
        enabled=True,
        interval_hours=168,
        grace_period_days=7,
        stale_after_days=30,
        archive_after_days=90,
    )
    return SkillCurator(stats_collector, config)


def create_mock_skill(
    name: str,
    status: SkillLifecycleStatus = SkillLifecycleStatus.ACTIVE,
    pinned: bool = False,
    days_idle: int = 0,
    days_old: int = 10,
) -> SkillMetadata:
    now = datetime.now(UTC)
    last_used = now - timedelta(days=days_idle)
    created = now - timedelta(days=days_old)

    stats = SkillUsageStats(
        lifecycle_status=status,
        pinned=pinned,
        last_used_at=last_used,
        created_at=created,
        call_count=1 if days_idle > 0 else 0,
    )

    skill = MagicMock(spec=SkillMetadata)
    skill.name = name
    skill.storage_path = f"/tmp/skills/{name}"
    skill.usage_stats = stats
    skill.evolution_locked = False
    return skill


def test_curator_disabled(stats_collector: SkillStatsCollector):
    config = CuratorConfig(enabled=False)
    curator = SkillCurator(stats_collector, config)

    skill = create_mock_skill("test", days_idle=40)
    result = curator.run([skill])

    assert result.total_transitions == 0
    assert result.skills_scanned == 0


def test_curator_force_run(stats_collector: SkillStatsCollector):
    config = CuratorConfig(enabled=False)
    curator = SkillCurator(stats_collector, config)

    skill = create_mock_skill("test", days_idle=40)
    result = curator.run([skill], force=True)

    assert result.skills_scanned == 1
    assert result.total_transitions == 1
    assert result.stale_count == 1


def test_curator_skip_pinned(curator: SkillCurator):
    skill = create_mock_skill("test", pinned=True, days_idle=40)
    result = curator.run([skill])

    assert result.skipped_pinned == 1
    assert result.total_transitions == 0


def test_curator_grace_period(curator: SkillCurator):
    # 40 days idle, but only 5 days old (grace period is 7)
    skill = create_mock_skill("test", days_idle=40, days_old=5)
    result = curator.run([skill])

    assert result.total_transitions == 0


def test_curator_active_to_stale(curator: SkillCurator):
    skill = create_mock_skill("test", days_idle=40, days_old=50)
    result = curator.run([skill])

    assert result.total_transitions == 1
    assert result.stale_count == 1
    assert result.transitions[0].from_status == "active"
    assert result.transitions[0].to_status == "stale"


def test_curator_stale_to_archived(curator: SkillCurator):
    skill = create_mock_skill("test", status=SkillLifecycleStatus.STALE, days_idle=100, days_old=110)
    result = curator.run([skill])

    assert result.total_transitions == 1
    assert result.archived_count == 1
    assert result.transitions[0].from_status == "stale"
    assert result.transitions[0].to_status == "archived"


def test_curator_leaves_a_large_active_library_alone(curator: SkillCurator):
    # The sweep judges each skill on its own idleness and quality; the size of the library is not a reason to move any.
    skills = [create_mock_skill(f"s{i}", days_idle=1 + i % 20, days_old=10 + i % 20) for i in range(120)]

    result = curator.run(skills)

    assert result.total_transitions == 0
    assert result.errors == []


def test_curator_skips_protected_skill(curator: SkillCurator):
    protected = create_mock_skill("bound", days_idle=40, days_old=50)
    unprotected = create_mock_skill("free", days_idle=40, days_old=50)

    result = curator.run([protected, unprotected], protected_names=frozenset({"bound"}))

    assert result.skipped_protected == 1
    assert result.skipped_pinned == 0
    assert [t.skill_name for t in result.transitions] == ["free"]


def test_curator_protected_skill_never_archived(curator: SkillCurator):
    skill = create_mock_skill("bound", status=SkillLifecycleStatus.STALE, days_idle=100, days_old=110)

    result = curator.run([skill], protected_names=frozenset({"bound"}))

    assert result.skipped_protected == 1
    assert result.total_transitions == 0


def test_curator_protected_skill_not_counted_as_pinned(curator: SkillCurator):
    skill = create_mock_skill("both", pinned=True, days_idle=40, days_old=50)

    result = curator.run([skill], protected_names=frozenset({"both"}))

    assert result.skipped_pinned == 1
    assert result.skipped_protected == 0


@pytest.mark.asyncio
async def test_curator_consolidation_excludes_protected_skills(stats_collector: SkillStatsCollector):
    config = CuratorConfig(enabled=True, consolidation_enabled=True)
    curator = SkillCurator(
        stats_collector,
        config,
        embedding_service=MagicMock(),
        llm=MagicMock(),
        write_backend=MagicMock(),
    )
    seen: list[tuple[list[str], frozenset[str]]] = []

    async def fake_consolidation(
        skills: list[SkillMetadata], *, dry_run: bool = True, reserved_names: frozenset[str] = frozenset()
    ) -> None:
        seen.append(([s.name for s in skills], reserved_names))

    curator._run_consolidation = fake_consolidation  # type: ignore[method-assign]
    bound = create_mock_skill("bound")
    free = create_mock_skill("free")

    await curator.run_async([bound, free], protected_names=frozenset({"bound"}))

    assert seen == [(["free"], frozenset({"bound"}))]


def test_curator_installed_skill_is_exempt_while_protection_is_on(curator: SkillCurator):
    skill = create_mock_skill("from-store", days_idle=40, days_old=50)

    result = curator.run([skill], installed_names=frozenset({"from-store"}))

    assert result.skipped_protected == 1
    assert result.total_transitions == 0


def test_curator_installed_skill_is_curated_when_protection_is_off(stats_collector: SkillStatsCollector):
    curator = SkillCurator(stats_collector, CuratorConfig(protect_installed_skills=False))
    skill = create_mock_skill("from-store", days_idle=40, days_old=50)

    result = curator.run([skill], installed_names=frozenset({"from-store"}))

    assert result.skipped_protected == 0
    assert [t.skill_name for t in result.transitions] == ["from-store"]


@pytest.mark.parametrize(
    ("protect_installed", "expected"),
    [
        (True, [(["free"], frozenset({"from-store"}))]),
        (False, [(["from-store", "free"], frozenset[str]())]),
    ],
)
@pytest.mark.asyncio
async def test_curator_consolidation_follows_installed_protection(
    stats_collector: SkillStatsCollector, protect_installed: bool, expected: list[tuple[list[str], frozenset[str]]]
):
    config = CuratorConfig(enabled=True, consolidation_enabled=True, protect_installed_skills=protect_installed)
    curator = SkillCurator(
        stats_collector,
        config,
        embedding_service=MagicMock(),
        llm=MagicMock(),
        write_backend=MagicMock(),
    )
    seen: list[tuple[list[str], frozenset[str]]] = []

    async def fake_consolidation(
        skills: list[SkillMetadata], *, dry_run: bool = True, reserved_names: frozenset[str] = frozenset()
    ) -> None:
        seen.append(([s.name for s in skills], reserved_names))

    curator._run_consolidation = fake_consolidation  # type: ignore[method-assign]
    installed = create_mock_skill("from-store")
    free = create_mock_skill("free")

    await curator.run_async([installed, free], installed_names=frozenset({"from-store"}))

    assert seen == expected
