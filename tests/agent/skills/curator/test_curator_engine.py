from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.agent.skills.curator.engine import SkillCurator
from myrm_agent_harness.backends.skills.forgetting_strategy import CuratorConfig
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import (
    SkillLifecycleStatus,
    SkillMetadata,
    SkillTrust,
    SkillUsageStats,
)


@pytest.fixture
def temp_skills_dir(tmp_path: Path) -> Path:
    return tmp_path / "skills"


@pytest.fixture
def stats_collector(temp_skills_dir: Path) -> SkillStatsCollector:
    temp_skills_dir.mkdir(parents=True, exist_ok=True)
    return SkillStatsCollector(temp_skills_dir)


@pytest.fixture
def curator(stats_collector: SkillStatsCollector) -> SkillCurator:
    config = CuratorConfig(
        enabled=True,
        interval_hours=168,
        grace_period_days=7,
        stale_after_days=30,
        archive_after_days=90,
        max_skills=2,
    )
    return SkillCurator(stats_collector, config)


def create_mock_skill(
    name: str,
    status: SkillLifecycleStatus = SkillLifecycleStatus.ACTIVE,
    pinned: bool = False,
    days_idle: int = 0,
    days_old: int = 10,
    trust: SkillTrust = SkillTrust.TRUSTED,
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
    skill.trust = trust
    skill.usage_stats = stats
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
    skill = create_mock_skill(
        "test", status=SkillLifecycleStatus.STALE, days_idle=100, days_old=110
    )
    result = curator.run([skill])

    assert result.total_transitions == 1
    assert result.archived_count == 1
    assert result.transitions[0].from_status == "stale"
    assert result.transitions[0].to_status == "archived"


def test_curator_lru_eviction(curator: SkillCurator):
    # Max skills is 2. We provide 3 active skills.
    # The oldest used one should be evicted to stale.
    s1 = create_mock_skill("s1", days_idle=1, days_old=10)
    s2 = create_mock_skill("s2", days_idle=2, days_old=10)
    s3 = create_mock_skill("s3", days_idle=3, days_old=10)

    result = curator.run([s1, s2, s3])

    assert result.total_transitions == 1
    assert result.stale_count == 1
    assert result.transitions[0].skill_name == "s3"
    assert result.transitions[0].reason_type == "lru_eviction"
