"""Consolidation leaves the right usage ledgers on disk, through a real SkillStatsCollector.

The skill that absorbs others inherits their counters, and each absorbed skill records where it went.
The collector is real because a mocked one cannot tell whether the counters reached the ledger.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.skills.curator.consolidation.executor import ConsolidationExecutor
from myrm_agent_harness.agent.skills.curator.consolidation.types import ConsolidationAction, ConsolidationActionType
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillUsageStats

_LAST_USED = datetime(2026, 3, 1, tzinfo=UTC)


def _skill(skills_root: Path, name: str, *, call_count: int) -> SkillMetadata:
    skill_dir = skills_root / name
    skill_dir.mkdir()
    return SkillMetadata(
        name=name,
        description=f"{name} skill",
        storage_path=str(skill_dir),
        usage_stats=SkillUsageStats(
            call_count=call_count, success_count=call_count, last_used_at=_LAST_USED, created_at=_LAST_USED
        ),
    )


def _ledger(skill_dir: str | Path) -> dict[str, object]:
    return json.loads((Path(skill_dir) / ".stats.json").read_text(encoding="utf-8"))


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    return root


@pytest.fixture
def collector(tmp_path: Path) -> SkillStatsCollector:
    return SkillStatsCollector()


async def test_merge_adds_the_sources_counters_to_the_target_ledger(
    skills_root: Path, collector: SkillStatsCollector
) -> None:
    target = _skill(skills_root, "git_operations", call_count=0)
    commit = _skill(skills_root, "git_commit", call_count=3)
    push = _skill(skills_root, "git_push", call_count=4)
    collector.record_use(Path(target.storage_path or ""), success=True)
    backend = MagicMock()
    backend.write_resource = AsyncMock(return_value=MagicMock(success=True))
    action = ConsolidationAction(
        action_type=ConsolidationActionType.MERGE,
        target_skill="git_operations",
        source_skills=("git_commit", "git_push"),
        reasoning="same domain",
    )

    report = await ConsolidationExecutor(backend, collector, [target, commit, push]).execute([action])

    assert report.success_count == 1
    inherited = _ledger(target.storage_path or "")
    assert (inherited["call_count"], inherited["success_count"]) == (1 + 3 + 4, 1 + 3 + 4)
    for source in (commit, push):
        archived = _ledger(source.storage_path or "")
        assert (archived["lifecycle_status"], archived["merged_into"]) == ("archived", "git_operations")


async def test_umbrella_starts_with_the_sources_counters(skills_root: Path, collector: SkillStatsCollector) -> None:
    commit = _skill(skills_root, "git_commit", call_count=3)
    push = _skill(skills_root, "git_push", call_count=4)
    umbrella_dir = skills_root / "git_operations"
    umbrella_dir.mkdir()  # the write backend creates it when it saves the umbrella
    backend = MagicMock()
    backend.save_skill = AsyncMock(return_value=MagicMock(success=True, saved_path=str(umbrella_dir), error=""))
    action = ConsolidationAction(
        action_type=ConsolidationActionType.CREATE_UMBRELLA,
        target_skill="git_operations",
        source_skills=("git_commit", "git_push"),
        reasoning="same domain",
        umbrella_description="Git operations",
    )

    report = await ConsolidationExecutor(backend, collector, [commit, push]).execute([action])

    assert report.success_count == 1
    inherited = _ledger(umbrella_dir)
    assert inherited["call_count"] == 3 + 4
    assert datetime.fromisoformat(str(inherited["last_used_at"])) == _LAST_USED
