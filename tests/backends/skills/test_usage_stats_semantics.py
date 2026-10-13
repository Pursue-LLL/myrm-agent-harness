"""Field semantics of ``SkillUsageStats``: uses vs. observed outcomes, and the reset of unversioned ledgers."""

from __future__ import annotations

from datetime import UTC, datetime

from myrm_agent_harness.backends.skills.types import SkillLifecycleStatus, SkillUsageStats
from myrm_agent_harness.backends.skills.types.types_usage import STATS_SCHEMA_VERSION


def test_success_rate_is_computed_over_observed_outcomes_only() -> None:
    """Uses without an observable outcome neither raise nor lower the rate."""
    stats = SkillUsageStats(call_count=10, success_count=3, failure_count=1)

    assert stats.observed_count == 4
    assert stats.success_rate == 0.75


def test_success_rate_is_zero_without_any_observed_outcome() -> None:
    stats = SkillUsageStats(call_count=7)

    assert stats.observed_count == 0
    assert stats.success_rate == 0.0


def test_history_record_keeps_unobserved_outcome_as_none() -> None:
    stats = SkillUsageStats()
    stats.append_usage("2026-10-12T00:00:00+00:00", None)
    stats.append_usage("2026-10-12T00:01:00+00:00", True)

    restored = SkillUsageStats.from_dict(stats.to_dict())

    assert [record.success for record in restored.usage_history] == [None, True]


def test_to_dict_stamps_the_current_schema_version() -> None:
    assert SkillUsageStats().to_dict()["schema_version"] == STATS_SCHEMA_VERSION


def test_current_schema_round_trip_keeps_outcome_counters() -> None:
    stats = SkillUsageStats(call_count=5, success_count=3, failure_count=1)
    stats.append_usage("2026-10-12T00:00:00+00:00", False)

    restored = SkillUsageStats.from_dict(stats.to_dict())

    assert (restored.call_count, restored.success_count, restored.failure_count) == (5, 3, 1)
    assert len(restored.usage_history) == 1


def test_unversioned_ledger_drops_its_outcomes_and_keeps_everything_else() -> None:
    """A ledger without a schema version holds selection-time outcomes, so only its outcome fields are discarded."""
    created = datetime(2026, 1, 1, tzinfo=UTC)
    unversioned = {
        "call_count": 12,
        "success_count": 12,
        "failure_count": 0,
        "last_used_at": "2026-10-01T00:00:00+00:00",
        "lifecycle_status": "stale",
        "pinned": True,
        "merged_into": "umbrella",
        "created_at": created.isoformat(),
        "usage_history": [{"timestamp": "2026-10-01T00:00:00+00:00", "success": True}],
    }

    stats = SkillUsageStats.from_dict(unversioned)

    assert (stats.success_count, stats.failure_count) == (0, 0)
    assert stats.usage_history == []
    assert stats.call_count == 12
    assert stats.last_used_at == datetime(2026, 10, 1, tzinfo=UTC)
    assert stats.lifecycle_status == SkillLifecycleStatus.STALE
    assert stats.pinned is True
    assert stats.merged_into == "umbrella"
    assert stats.created_at == created


def test_unversioned_ledger_reset_happens_once() -> None:
    """After the first rewrite the file carries the schema version, so later outcomes are never discarded again."""
    first = SkillUsageStats.from_dict({"call_count": 4, "success_count": 4})
    first.success_count += 2

    second = SkillUsageStats.from_dict(first.to_dict())

    assert second.success_count == 2
