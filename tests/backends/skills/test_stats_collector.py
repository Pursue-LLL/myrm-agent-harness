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
    return SkillStatsCollector()


def test_record_use_creates_stats_file(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that record_use creates .stats.json file."""
    collector.record_use(skill_dir, success=True)

    stats_file = skill_dir / ".stats.json"
    assert stats_file.exists()


def test_record_use_separates_uses_from_observed_outcomes(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Every run is a use; only runs with an observable outcome move the success counters."""
    collector.record_use(skill_dir, success=True)
    collector.record_use(skill_dir, success=False)
    collector.record_use(skill_dir, success=None)

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

    stats = collector.get_stats(skill_dir)
    assert stats.last_used_at is not None
    # Check that last_used_at is recent (within 1 second)
    time_diff = (datetime.now(UTC) - stats.last_used_at).total_seconds()
    assert abs(time_diff) < 1.0


def test_every_use_is_on_disk_when_record_use_returns(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Nothing is buffered: a process that exits right after a use loses nothing."""
    stats_file = skill_dir / ".stats.json"

    for expected in range(1, 6):
        collector.record_use(skill_dir, success=True)
        assert json.loads(stats_file.read_text())["call_count"] == expected


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


def test_successive_uses_accumulate(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Each use is added to the ledger the previous one left."""
    collector.record_use(skill_dir, success=True)
    collector.record_use(skill_dir, success=True)

    stats = collector.get_stats(skill_dir)
    assert stats.call_count == 2
    assert stats.success_count == 2


def test_stale_auto_recovery_on_usage(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test that using a stale skill auto-recovers it to active."""
    stats_file = skill_dir / ".stats.json"
    stats_file.write_text(json.dumps({"call_count": 3, "lifecycle_status": "stale"}))

    collector.record_use(skill_dir, success=None)

    recovered = collector.get_stats(skill_dir)
    assert recovered.lifecycle_status == SkillLifecycleStatus.ACTIVE
    assert recovered.call_count == 4


def test_update_lifecycle_status(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Test update_lifecycle_status writes immediately."""
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
    stats = SkillStatsCollector().get_stats(skill_dir)
    assert stats.observed_count == 0
    assert stats.pinned is True
    assert stats.lifecycle_status == SkillLifecycleStatus.STALE
    assert stats.last_used_at == last_used_at


def test_get_stats_reads_changes_made_by_another_collector(temp_workspace: Path, skill_dir: Path) -> None:
    """The disk is the only state: a reader never serves what it saw earlier."""
    reader = SkillStatsCollector()
    writer = SkillStatsCollector()
    assert reader.get_stats(skill_dir).call_count == 0

    writer.record_use(skill_dir, success=True)
    writer.set_pinned(skill_dir, pinned=True)

    seen = reader.get_stats(skill_dir)
    assert (seen.call_count, seen.pinned) == (1, True)


def test_a_stale_view_never_overwrites_changes_made_elsewhere(temp_workspace: Path, skill_dir: Path) -> None:
    """A collector that touched a skill earlier must not write its old counters back over newer ones."""
    api = SkillStatsCollector()
    recorder = SkillStatsCollector()
    api.set_pinned(skill_dir, pinned=True)

    for _ in range(3):
        recorder.record_use(skill_dir, success=True)
    api.set_pinned(skill_dir, pinned=False)

    on_disk = json.loads((skill_dir / ".stats.json").read_text())
    assert (on_disk["call_count"], on_disk["pinned"]) == (3, False)


def test_first_observation_creates_the_ledger_and_anchors_created_at(
    collector: SkillStatsCollector, skill_dir: Path
) -> None:
    """The forgetting policy ages a never-used skill from the moment it was first seen, so that moment is kept."""
    stats_file = skill_dir / ".stats.json"
    assert not stats_file.exists()

    first = collector.get_stats(skill_dir)

    assert stats_file.exists()
    assert first.created_at is not None
    later = SkillStatsCollector().get_stats(skill_dir)
    assert later.created_at == first.created_at


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
    """A transient read failure must not overwrite the real history, nor be remembered once reads work again."""
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


def test_write_leaves_no_temp_files_behind(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """Only the ledger remains in the skill directory after a write."""
    collector.record_use(skill_dir, success=True)

    assert sorted(entry.name for entry in skill_dir.iterdir()) == [".stats.json"]


def test_failed_write_keeps_the_previous_ledger(
    collector: SkillStatsCollector, skill_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write that dies half-way leaves the old ledger intact and no temp file behind."""
    collector.record_use(skill_dir, success=True)
    stats_file = skill_dir / ".stats.json"
    before = stats_file.read_text()

    def failing_replace(src: object, dst: object) -> None:
        raise OSError(errno.EIO, "disk error")

    monkeypatch.setattr("myrm_agent_harness.infra.atomic_write.os.replace", failing_replace)
    collector.record_use(skill_dir, success=False)  # logs a warning instead of raising

    assert stats_file.read_text() == before
    assert sorted(entry.name for entry in skill_dir.iterdir()) == [".stats.json"]


def test_inherit_usage_adds_to_the_skills_own_history(collector: SkillStatsCollector, skill_dir: Path) -> None:
    """The absorbed counters are added to what the skill already recorded, on disk."""
    collector.record_use(skill_dir, success=True)

    collector.inherit_usage(
        skill_dir,
        [
            SkillUsageStats(call_count=3, success_count=2, failure_count=1),
            SkillUsageStats(call_count=4, success_count=4),
            SkillUsageStats(call_count=1),
        ],
    )

    on_disk = json.loads((skill_dir / ".stats.json").read_text())
    assert (on_disk["call_count"], on_disk["success_count"], on_disk["failure_count"]) == (9, 7, 1)


def test_archive_merged_keeps_the_skills_history(collector: SkillStatsCollector, skill_dir: Path) -> None:
    collector.record_use(skill_dir, success=True)

    collector.archive_merged(skill_dir, "umbrella")

    on_disk = json.loads((skill_dir / ".stats.json").read_text())
    assert (on_disk["lifecycle_status"], on_disk["merged_into"], on_disk["call_count"]) == ("archived", "umbrella", 1)


def test_inherit_usage_keeps_the_latest_use(collector: SkillStatsCollector, skill_dir: Path) -> None:
    earlier = datetime(2026, 1, 1, tzinfo=UTC)
    later = datetime(2026, 2, 1, tzinfo=UTC)

    collector.inherit_usage(
        skill_dir,
        [
            SkillUsageStats(call_count=1, last_used_at=later),
            SkillUsageStats(call_count=1, last_used_at=earlier),
            SkillUsageStats(call_count=1),
        ],
    )

    on_disk = json.loads((skill_dir / ".stats.json").read_text())
    assert datetime.fromisoformat(on_disk["last_used_at"]) == later


def test_missing_skill_directory_is_not_recreated(collector: SkillStatsCollector, tmp_path: Path) -> None:
    """Recording stats of a skill that was archived or removed must not resurrect an empty skill directory."""
    gone = tmp_path / "does_not_exist" / "skill"

    collector.record_use(gone, success=True)

    assert not gone.exists()
    assert not gone.parent.exists()
