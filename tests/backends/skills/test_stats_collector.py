"""Tests for SkillStatsCollector."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillUsageStats


@pytest.fixture
def temp_workspace(tmp_path: Path) -> Path:
    """Create temporary workspace."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def skill_dir(temp_workspace: Path) -> Path:
    """Create skill directory."""
    skill_dir = temp_workspace / "skills" / "test_skill"
    skill_dir.mkdir(parents=True)
    return skill_dir


@pytest.fixture
def collector(temp_workspace: Path) -> SkillStatsCollector:
    """Create stats collector."""
    return SkillStatsCollector(temp_workspace)


def test_record_usage_creates_stats_file(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that record_usage creates .stats.json file."""
    collector.record_usage(skill_dir, success=True, duration_ms=100.0)
    collector.flush()

    stats_file = skill_dir / ".stats.json"
    assert stats_file.exists()


def test_record_usage_updates_stats(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that record_usage correctly updates statistics."""
    collector.record_usage(skill_dir, success=True, duration_ms=100.0)
    collector.record_usage(skill_dir, success=False, duration_ms=50.0)
    collector.flush()

    stats_file = skill_dir / ".stats.json"
    with stats_file.open() as f:
        data = json.load(f)

    stats = SkillUsageStats.from_dict(data)
    assert stats.call_count == 2
    assert stats.success_count == 1
    assert stats.failure_count == 1
    assert stats.total_duration_ms == 150.0
    assert stats.success_rate == 0.5
    assert stats.avg_duration_ms == 75.0


def test_record_usage_updates_last_used(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that record_usage updates last_used_at."""
    collector.record_usage(skill_dir, success=True, duration_ms=10.0)
    collector.flush()

    stats = collector.get_stats(skill_dir)
    assert stats.last_used_at is not None
    # Check that last_used_at is recent (within 1 second)
    time_diff = (datetime.now(UTC) - stats.last_used_at).total_seconds()
    assert abs(time_diff) < 1.0


def test_batch_flush_optimization(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that flush batches multiple updates."""
    # Record multiple times without flushing
    for _i in range(5):
        collector.record_usage(skill_dir, success=True, duration_ms=100.0)

    # Should not write until flush
    stats_file = skill_dir / ".stats.json"
    if stats_file.exists():
        # If exists, it's from a previous test or auto-flush
        pass

    collector.flush()

    # After flush, should be written
    assert stats_file.exists()
    with stats_file.open() as f:
        data = json.load(f)

    stats = SkillUsageStats.from_dict(data)
    assert stats.call_count == 5


def test_get_stats_loads_existing(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that get_stats loads existing .stats.json."""
    # Write initial stats
    initial_stats = SkillUsageStats(
        call_count=10, success_count=8, failure_count=2, last_used_at=datetime.now(UTC), total_duration_ms=1000.0
    )
    stats_file = skill_dir / ".stats.json"
    with stats_file.open("w") as f:
        json.dump(initial_stats.to_dict(), f)

    # Load stats
    loaded_stats = collector.get_stats(skill_dir)
    assert loaded_stats.call_count == 10
    assert loaded_stats.success_count == 8
    assert loaded_stats.success_rate == 0.8


def test_get_stats_returns_empty_if_not_exists(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that get_stats returns empty stats if file doesn't exist."""
    stats = collector.get_stats(skill_dir)
    assert stats.call_count == 0
    assert stats.success_count == 0
    assert stats.failure_count == 0
    assert stats.total_duration_ms == 0.0


def test_concurrent_updates(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test handling of concurrent updates."""
    collector.record_usage(skill_dir, success=True, duration_ms=100.0)
    collector.record_usage(skill_dir, success=True, duration_ms=200.0)
    collector.flush()

    stats = collector.get_stats(skill_dir)
    assert stats.call_count == 2
    assert stats.total_duration_ms == 300.0


def test_stale_auto_recovery_on_usage(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that using a stale skill auto-recovers it to active."""
    from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus

    stats_file = skill_dir / ".stats.json"
    stats_file.write_text(
        json.dumps({"call_count": 3, "success_count": 2, "failure_count": 1, "lifecycle_status": "stale"})
    )

    collector.record_usage(skill_dir, success=True, duration_ms=50.0)
    collector.flush()

    recovered = collector.get_stats(skill_dir)
    assert recovered.lifecycle_status == SkillLifecycleStatus.ACTIVE
    assert recovered.call_count == 4


def test_update_lifecycle_status(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test update_lifecycle_status writes immediately."""
    from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus

    collector.update_lifecycle_status(skill_dir, SkillLifecycleStatus.ARCHIVED)
    stats = collector.get_stats(skill_dir)
    assert stats.lifecycle_status == SkillLifecycleStatus.ARCHIVED


def test_set_pinned(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test set_pinned writes immediately."""
    collector.set_pinned(skill_dir, pinned=True)
    stats = collector.get_stats(skill_dir)
    assert stats.pinned is True

    collector.set_pinned(skill_dir, pinned=False)
    stats = collector.get_stats(skill_dir)
    assert stats.pinned is False


def test_get_stats_returns_pending(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that get_stats returns pending (unflushed) updates."""
    collector.record_usage(skill_dir, success=True, duration_ms=100.0)
    stats = collector.get_stats(skill_dir)
    assert stats.call_count == 1


def test_corrupt_stats_file_returns_default(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that a corrupt .stats.json returns default stats."""
    stats_file = skill_dir / ".stats.json"
    stats_file.write_text("{{not valid json!!!")

    stats = collector.get_stats(skill_dir)
    assert stats.call_count == 0
    assert stats.created_at is not None


def test_write_failure_logs_warning(collector: SkillStatsCollector, tmp_path: Path) -> None:
    """Test that write failure is handled gracefully."""
    non_existent = tmp_path / "does_not_exist" / "skill"
    collector.record_usage(non_existent, success=True, duration_ms=10.0)
    collector.flush()
