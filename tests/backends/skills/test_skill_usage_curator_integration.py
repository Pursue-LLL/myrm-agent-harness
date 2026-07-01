"""Integration test: skill selection records usage stats consumed by Curator."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from myrm_agent_harness.agent.skills.curator import SkillCurator
from myrm_agent_harness.backends.skills.forgetting_strategy import CuratorConfig
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillUsageStats
from myrm_agent_harness.backends.skills.usage_recorder import (
    flush_skill_usage_stats,
    record_skill_selection,
    reset_turn_usage_dedupe,
)


def test_select_records_stats_and_curator_sweep_reads_them(tmp_path: Path, monkeypatch) -> None:
    """record_skill_selection writes .stats.json; inactive skills become stale on sweep."""
    skill_dir = tmp_path / "demo_skill"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("# demo_skill\n")

    collector = SkillStatsCollector(tmp_path)
    monkeypatch.setattr(
        "myrm_agent_harness.backends.skills.usage_recorder._collector",
        collector,
    )

    skill_meta = SkillMetadata(
        name="demo_skill",
        description="Integration test skill",
        storage_path=str(skill_dir),
    )

    reset_turn_usage_dedupe()
    record_skill_selection(skill_meta, success=True)
    flush_skill_usage_stats()

    stats_file = skill_dir / ".stats.json"
    assert stats_file.exists()
    stats_data = json.loads(stats_file.read_text())
    assert stats_data["call_count"] == 1
    assert stats_data["last_used_at"] is not None

    # Turn dedupe: second call in same turn must not double-count
    record_skill_selection(skill_meta, success=True)
    flush_skill_usage_stats()
    stats_data = json.loads(stats_file.read_text())
    assert stats_data["call_count"] == 1

    # Simulate long inactivity and run curator sweep
    old_last_used = datetime.now(UTC) - timedelta(days=60)
    inactive_stats = SkillUsageStats(
        call_count=1,
        success_count=1,
        failure_count=0,
        last_used_at=old_last_used,
        total_duration_ms=0.0,
        created_at=old_last_used,
    )
    inactive_skill = SkillMetadata(
        name="demo_skill",
        description="Integration test skill",
        storage_path=str(skill_dir),
        usage_stats=inactive_stats,
    )

    config = CuratorConfig(stale_after_days=30, grace_period_days=0)
    curator = SkillCurator(collector, config)
    result = curator.run([inactive_skill], force=True)

    assert result.stale_count >= 1
    persisted = json.loads(stats_file.read_text())
    assert persisted["lifecycle_status"] == "stale"
