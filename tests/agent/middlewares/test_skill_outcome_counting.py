"""Tool-call outcomes are counted into the skill's run usage only when the owning skill is unambiguous."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from myrm_agent_harness.agent.middlewares.tooling._skill_failure_tracking import track_skill_execution
from myrm_agent_harness.agent.skill_agent.context import add_loaded_skill, reset_loaded_skills
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillUsageStats
from myrm_agent_harness.backends.skills.usage_recorder import (
    begin_skill_run_usage,
    commit_skill_run_usage,
    set_stats_collector,
)
from myrm_agent_harness.runtime.events import SkillFailureEvent


@dataclass
class _Ledger:
    """An open run scope writing to a throw-away ``.stats.json`` store, plus the failure events it published."""

    root: Path
    events: list[SkillFailureEvent] = field(default_factory=list)

    def publish(self, event: object) -> None:
        if isinstance(event, SkillFailureEvent):
            self.events.append(event)

    def load_skill(self, name: str, skill_id: str) -> None:
        skill_dir = self.root / name
        skill_dir.mkdir()
        add_loaded_skill(
            SkillMetadata(name=name, description=name, storage_skill_id=skill_id, storage_path=str(skill_dir))
        )

    def stats_of(self, name: str) -> SkillUsageStats:
        commit_skill_run_usage()
        return SkillStatsCollector(self.root).get_stats(self.root / name)


@pytest.fixture
def ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[_Ledger]:
    run_ledger = _Ledger(tmp_path)
    monkeypatch.setattr("myrm_agent_harness.runtime.events.get_event_bus", lambda: run_ledger)
    set_stats_collector(SkillStatsCollector(tmp_path))
    begin_skill_run_usage()
    reset_loaded_skills()
    yield run_ledger
    reset_loaded_skills()
    begin_skill_run_usage()  # drops whatever a failing test left pending instead of writing it to the default store
    set_stats_collector(None)


def test_run_outcomes_fold_into_one_use_that_follows_the_majority(ledger: _Ledger) -> None:
    ledger.load_skill("a", "skill-1")

    track_skill_execution("tool", tool_call_id="c1", tool_args={}, success=False, error_message="boom")
    track_skill_execution("tool", tool_call_id="c2", tool_args={}, success=False, error_message="boom")
    track_skill_execution("tool", tool_call_id="c3", tool_args={}, success=True, error_message="")

    stats = ledger.stats_of("a")
    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 0, 1)
    assert len(ledger.events) == 2


def test_successful_run_is_recorded_as_success(ledger: _Ledger) -> None:
    ledger.load_skill("a", "skill-1")

    track_skill_execution("tool", tool_call_id="c1", tool_args={}, success=True, error_message="")

    stats = ledger.stats_of("a")
    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 1, 0)
    assert ledger.events == []


@pytest.mark.parametrize(
    "category",
    ["estop", "guardrail_blocked", "turn_budget_guard", "sandbox_boundary", "benchmark_blocked"],
)
def test_policy_block_is_neither_counted_nor_published(ledger: _Ledger, category: str) -> None:
    """Guard, budget, sandbox-boundary and benchmark blocks are policy decisions, not skill defects."""
    ledger.load_skill("a", "skill-1")

    track_skill_execution(
        "tool", tool_call_id="c1", tool_args={}, success=False, error_message="blocked", error_category=category
    )

    assert ledger.stats_of("a").call_count == 0
    assert ledger.events == []


@pytest.mark.parametrize("success", [True, False])
def test_loading_a_skill_is_not_an_execution_outcome(ledger: _Ledger, success: bool) -> None:
    """``skill_select_tool`` only loads the SOP; its result carries no evidence about skill quality."""
    ledger.load_skill("a", "skill-1")

    track_skill_execution(
        "skill_select_tool",
        tool_call_id="c1",
        tool_args={"skill_names": ["a"]},
        success=success,
        error_message="" if success else "load failed",
    )

    assert ledger.stats_of("a").call_count == 0
    assert ledger.events == []


def test_ambiguous_owner_leaves_no_trace_in_the_stats_ledger(ledger: _Ledger) -> None:
    """With several storage skills loaded the failing owner is unknown, so nothing is counted."""
    ledger.load_skill("a", "s1")
    ledger.load_skill("b", "s2")

    track_skill_execution("tool", tool_call_id="c1", tool_args={}, success=False, error_message="boom")

    assert ledger.stats_of("a").call_count == 0
    assert ledger.stats_of("b").call_count == 0
