"""Unit tests for usage_recorder — the run-scoped bridge from skill activity to ``.stats.json``."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextvars import copy_context
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillUsageStats
from myrm_agent_harness.backends.skills.usage_recorder import (
    begin_skill_run_usage,
    commit_skill_run_usage,
    flush_skill_usage_stats,
    get_injected_stats_collector,
    record_skill_execution,
    record_skill_selection,
    set_stats_collector,
)


@pytest.fixture(autouse=True)
def _reset_usage_recorder() -> Iterator[None]:
    set_stats_collector(None)
    begin_skill_run_usage()
    yield
    begin_skill_run_usage()  # drops whatever a failing test left pending instead of writing it to the default store
    set_stats_collector(None)


def _skill(tmp_path: Path, name: str = "demo") -> SkillMetadata:
    skill_dir = tmp_path / name
    skill_dir.mkdir()
    return SkillMetadata(name=name, description=name, storage_path=str(skill_dir))


def _stats(tmp_path: Path, name: str = "demo") -> SkillUsageStats:
    return SkillStatsCollector(tmp_path).get_stats(tmp_path / name)


def test_selection_is_written_at_run_end_not_at_selection(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    collector = SkillStatsCollector(tmp_path)
    set_stats_collector(collector)

    record_skill_selection(skill)
    assert collector.get_stats(tmp_path / "demo").call_count == 0

    commit_skill_run_usage()
    stats = collector.get_stats(tmp_path / "demo")
    assert stats.call_count == 1


def test_selection_without_execution_is_a_use_with_unobserved_outcome(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    record_skill_selection(skill)
    commit_skill_run_usage()
    flush_skill_usage_stats()

    stats = _stats(tmp_path)
    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 0, 0)
    assert [record.success for record in stats.usage_history] == [None]


def test_successful_execution_is_a_successful_use(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    record_skill_selection(skill)
    record_skill_execution(skill.name, skill.storage_path, success=True)
    record_skill_execution(skill.name, skill.storage_path, success=True)
    commit_skill_run_usage()
    flush_skill_usage_stats()

    stats = _stats(tmp_path)
    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 1, 0)


@pytest.mark.parametrize(
    ("tool_outcomes", "expected_success"),
    [
        ([True, False, True], True),
        ([True, True, True, False], True),
        ([False, False, True], False),
        ([False], False),
        ([True, False], True),
    ],
    ids=["incidental-error", "one-error-in-four", "mostly-failing", "single-failure", "tie-counts-as-recovered"],
)
def test_use_fails_only_when_most_tool_calls_failed(
    tmp_path: Path, tool_outcomes: list[bool], expected_success: bool
) -> None:
    """Many tool calls in one run are one use; an incidental, recovered error must not mark the skill as failed."""
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    for success in tool_outcomes:
        record_skill_execution(skill.name, skill.storage_path, success=success)
    commit_skill_run_usage()
    flush_skill_usage_stats()

    stats = _stats(tmp_path)
    assert stats.call_count == 1
    assert [record.success for record in stats.usage_history] == [expected_success]


def test_execution_without_selection_counts_as_a_use(tmp_path: Path) -> None:
    """A skill carried over from an earlier turn is used again when its execution is observed."""
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    record_skill_execution(skill.name, skill.storage_path, success=True)
    commit_skill_run_usage()
    flush_skill_usage_stats()

    assert _stats(tmp_path).call_count == 1


def test_repeated_selection_in_one_run_is_one_use(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    record_skill_selection(skill)
    record_skill_selection(skill)
    commit_skill_run_usage()
    flush_skill_usage_stats()

    assert _stats(tmp_path).call_count == 1


def test_commit_closes_the_scope(tmp_path: Path) -> None:
    """A second commit must not write the same run again."""
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    record_skill_selection(skill)
    commit_skill_run_usage()
    commit_skill_run_usage()
    flush_skill_usage_stats()

    assert _stats(tmp_path).call_count == 1


def test_each_skill_gets_its_own_outcome(tmp_path: Path) -> None:
    first = _skill(tmp_path, "first")
    second = _skill(tmp_path, "second")
    set_stats_collector(SkillStatsCollector(tmp_path))

    record_skill_selection(first)
    record_skill_selection(second)
    record_skill_execution(second.name, second.storage_path, success=False)
    commit_skill_run_usage()
    flush_skill_usage_stats()

    assert [r.success for r in _stats(tmp_path, "first").usage_history] == [None]
    assert [r.success for r in _stats(tmp_path, "second").usage_history] == [False]


def test_scope_is_shared_with_tool_contexts_and_isolated_for_nested_runs(tmp_path: Path) -> None:
    """Tools run in copied contexts: their records reach the run, while a nested run keeps its own scope."""
    skill = _skill(tmp_path, "outer")
    nested = _skill(tmp_path, "inner")
    set_stats_collector(SkillStatsCollector(tmp_path))

    def _nested_run() -> None:
        begin_skill_run_usage()
        record_skill_selection(nested)
        commit_skill_run_usage()

    copy_context().run(lambda: record_skill_selection(skill))
    copy_context().run(_nested_run)
    commit_skill_run_usage()
    flush_skill_usage_stats()

    assert _stats(tmp_path, "outer").call_count == 1
    assert _stats(tmp_path, "inner").call_count == 1


@pytest.mark.asyncio
async def test_records_from_concurrent_tool_tasks_reach_the_run(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    async def _tool(success: bool) -> None:
        record_skill_execution(skill.name, skill.storage_path, success=success)

    await asyncio.gather(_tool(False), _tool(False), _tool(True))
    commit_skill_run_usage()
    flush_skill_usage_stats()

    stats = _stats(tmp_path)
    assert (stats.call_count, stats.failure_count) == (1, 1)


def test_selection_outside_a_run_is_recorded_immediately(tmp_path: Path) -> None:
    """Embedders that use the select tool without ``SkillAgent`` have no run end to wait for."""
    commit_skill_run_usage()
    skill = _skill(tmp_path)
    set_stats_collector(SkillStatsCollector(tmp_path))

    record_skill_selection(skill)
    flush_skill_usage_stats()

    assert _stats(tmp_path).call_count == 1


def test_record_skips_when_no_storage_path() -> None:
    skill_meta = SkillMetadata(name="orphan", description="No path")
    record_skill_selection(skill_meta)
    record_skill_execution(skill_meta.name, None, success=True)
    commit_skill_run_usage()
    assert get_injected_stats_collector() is None


def test_record_skips_when_storage_path_not_directory(tmp_path: Path) -> None:
    file_path = tmp_path / "not_a_dir"
    file_path.write_text("x")
    skill_meta = SkillMetadata(
        name="bad_path",
        description="File not dir",
        storage_path=str(file_path),
    )
    collector = SkillStatsCollector(tmp_path)
    set_stats_collector(collector)
    record_skill_selection(skill_meta)
    record_skill_execution(skill_meta.name, skill_meta.storage_path, success=True)
    commit_skill_run_usage()
    flush_skill_usage_stats()
    assert not (file_path / ".stats.json").exists()


def test_default_collector_when_not_injected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    skill_dir = tmp_path / "lazy_skill"
    skill_dir.mkdir()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    skill_meta = SkillMetadata(
        name="lazy_skill",
        description="Uses lazy default collector",
        storage_path=str(skill_dir),
    )
    record_skill_selection(skill_meta)
    commit_skill_run_usage()
    flush_skill_usage_stats()
    assert (skill_dir / ".stats.json").exists()


def test_commit_swallows_collector_errors(tmp_path: Path) -> None:
    skill = _skill(tmp_path)
    broken = MagicMock(spec=SkillStatsCollector)
    broken.record_use.side_effect = RuntimeError("disk full")
    set_stats_collector(broken)

    record_skill_selection(skill)
    commit_skill_run_usage()
    broken.record_use.assert_called_once()


def test_flush_noop_when_no_collector() -> None:
    flush_skill_usage_stats()
