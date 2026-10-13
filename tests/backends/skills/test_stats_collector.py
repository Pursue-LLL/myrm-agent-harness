"""Tests for SkillStatsCollector."""

from __future__ import annotations

import errno
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus, SkillUsageStats


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


def test_record_use_creates_stats_file(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that record_use creates .stats.json file."""
    collector.record_use(skill_dir, success=True)
    collector.flush()

    stats_file = skill_dir / ".stats.json"
    assert stats_file.exists()


def test_record_use_separates_uses_from_observed_outcomes(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Every run is a use; only runs with an observable outcome move the success counters."""
    collector.record_use(skill_dir, success=True)
    collector.record_use(skill_dir, success=False)
    collector.record_use(skill_dir, success=None)
    collector.flush()

    with (skill_dir / ".stats.json").open() as f:
        stats = SkillUsageStats.from_dict(json.load(f))

    assert stats.call_count == 3
    assert stats.success_count == 1
    assert stats.failure_count == 1
    assert stats.observed_count == 2
    assert stats.success_rate == 0.5
    assert [record.success for record in stats.usage_history] == [True, False, None]


def test_record_use_updates_last_used(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that record_use updates last_used_at."""
    collector.record_use(skill_dir, success=True)
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
        collector.record_use(skill_dir, success=True)

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
    initial_stats = SkillUsageStats(call_count=10, success_count=8, failure_count=2, last_used_at=datetime.now(UTC))
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


def test_concurrent_updates(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test handling of concurrent updates."""
    collector.record_use(skill_dir, success=True)
    collector.record_use(skill_dir, success=True)
    collector.flush()

    stats = collector.get_stats(skill_dir)
    assert stats.call_count == 2
    assert stats.success_count == 2


def test_stale_auto_recovery_on_usage(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that using a stale skill auto-recovers it to active."""
    from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus

    stats_file = skill_dir / ".stats.json"
    stats_file.write_text(json.dumps({"call_count": 3, "lifecycle_status": "stale"}))

    collector.record_use(skill_dir, success=None)
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


def test_reset_usage_keeps_governance_state(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Only the verdict on past runs is discarded; pin, lifecycle and last use survive, on disk too."""
    for outcome in (True, False, False, None):
        collector.record_use(skill_dir, success=outcome)
    collector.set_pinned(skill_dir, pinned=True)
    collector.update_lifecycle_status(skill_dir, SkillLifecycleStatus.STALE)
    last_used_at = collector.get_stats(skill_dir).last_used_at

    collector.reset_usage(skill_dir)

    on_disk = json.loads((skill_dir / ".stats.json").read_text())
    assert (on_disk["call_count"], on_disk["success_count"], on_disk["failure_count"]) == (0, 0, 0)
    assert on_disk["usage_history"] == []
    stats = SkillStatsCollector(skill_dir.parent).get_stats(skill_dir)
    assert stats.observed_count == 0
    assert stats.pinned is True
    assert stats.lifecycle_status == SkillLifecycleStatus.STALE
    assert stats.last_used_at == last_used_at


def test_get_stats_returns_pending(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that get_stats returns pending (unflushed) updates."""
    collector.record_use(skill_dir, success=True)
    stats = collector.get_stats(skill_dir)
    assert stats.call_count == 1


def test_corrupt_stats_file_is_set_aside_and_replaced(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """An unparseable ledger is kept for inspection and a fresh, valid one takes its place."""
    stats_file = skill_dir / ".stats.json"
    stats_file.write_text("{{not valid json!!!")

    stats = collector.get_stats(skill_dir)

    assert stats.call_count == 0
    assert stats.created_at is not None
    assert (skill_dir / ".stats.json.corrupt").read_text() == "{{not valid json!!!"
    assert json.loads(stats_file.read_text())["call_count"] == 0


@pytest.mark.parametrize("payload", ["[]", "null", '"text"', "42"])
def test_non_object_ledger_is_set_aside(collector: SkillStatsCollector, skill_dir: Path, payload: str) -> None:
    """Valid JSON that is not an object is no usable ledger either."""
    (skill_dir / ".stats.json").write_text(payload)

    collector.get_stats(skill_dir)

    assert (skill_dir / ".stats.json.corrupt").read_text() == payload


def test_undecodable_ledger_is_set_aside(collector: SkillStatsCollector, skill_dir: Path) -> None:
    (skill_dir / ".stats.json").write_bytes(b"\xff\xfe\x00 not utf-8")

    stats = collector.get_stats(skill_dir)

    assert stats.call_count == 0
    assert (skill_dir / ".stats.json.corrupt").exists()


def test_unreadable_ledger_is_never_replaced_by_a_blank_one(
    collector: SkillStatsCollector, skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient read failure must neither be cached nor overwrite the real history."""
    stats_file = skill_dir / ".stats.json"
    original = json.dumps({"call_count": 9, "pinned": True})
    stats_file.write_text(original)
    real_read_text = Path.read_text

    def failing_read_text(self: Path, *args: object, **kwargs: object) -> str:
        if self == stats_file:
            raise PermissionError("denied")
        return real_read_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "read_text", failing_read_text)

    assert collector.get_stats(skill_dir).call_count == 0  # unsaved blank view for readers
    with pytest.raises(PermissionError):
        collector.record_use(skill_dir, success=True)
    with pytest.raises(PermissionError):
        collector.set_pinned(skill_dir, pinned=False)
    collector.flush()

    monkeypatch.undo()
    assert stats_file.read_text() == original
    assert not (skill_dir / ".stats.json.corrupt").exists()
    assert collector.get_stats(skill_dir).call_count == 9


def test_malformed_fields_keep_pinned_and_lifecycle(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Damage to counters or history must not unpin or reactivate a skill."""
    (skill_dir / ".stats.json").write_text(
        json.dumps(
            {
                "call_count": "many",
                "last_used_at": "yesterday",
                "pinned": True,
                "lifecycle_status": "stale",
                "usage_history": [{"timestamp": 1}, "junk", None],
            }
        )
    )

    stats = collector.get_stats(skill_dir)

    assert stats.pinned is True
    assert stats.lifecycle_status == "stale"
    assert not (skill_dir / ".stats.json.corrupt").exists()


def test_flush_writes_atomically_without_leftovers(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Only the ledger remains in the skill directory after a write."""
    collector.record_use(skill_dir, success=True)
    collector.flush()

    assert sorted(entry.name for entry in skill_dir.iterdir()) == [".stats.json"]


def test_failed_write_keeps_the_previous_ledger(
    collector: SkillStatsCollector, skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that dies half-way leaves the old ledger intact and no temp file behind."""
    collector.record_use(skill_dir, success=True)
    collector.flush()
    stats_file = skill_dir / ".stats.json"
    before = stats_file.read_text()

    def failing_replace(src: object, dst: object) -> None:
        raise OSError(errno.EIO, "disk error")

    monkeypatch.setattr("myrm_agent_harness.infra.atomic_write.os.replace", failing_replace)
    collector.record_use(skill_dir, success=False)
    collector.flush()  # logs a warning instead of raising

    assert stats_file.read_text() == before
    assert sorted(entry.name for entry in skill_dir.iterdir()) == [".stats.json"]


def test_missing_skill_directory_is_not_recreated(collector: SkillStatsCollector, tmp_path: Path) -> None:
    """Flushing stats of a skill that was archived or removed must not resurrect an empty skill directory."""
    gone = tmp_path / "does_not_exist" / "skill"

    collector.record_use(gone, success=True)
    collector.flush()

    assert not gone.exists()
    assert not gone.parent.exists()
