"""Tool-call outcomes are counted into the skill ledger only when the owning skill is unambiguous."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import pytest

from myrm_agent_harness.agent.middlewares.tooling._skill_failure_tracking import track_skill_execution
from myrm_agent_harness.agent.skill_agent.context import add_loaded_skill, reset_loaded_skills
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillUsageStats
from myrm_agent_harness.backends.skills.usage_recorder import (
    begin_skill_run_usage,
    commit_skill_run_usage,
    flush_skill_usage_stats,
    set_stats_collector,
)
from myrm_agent_harness.runtime.events import SkillFailureEvent


class _FakeEventBus:
    def __init__(self) -> None:
        self.events: list[SkillFailureEvent] = []

    def publish(self, event: object) -> None:
        if isinstance(event, SkillFailureEvent):
            self.events.append(event)


def _install_ledger(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    """Route the evolution ledger to an in-memory list and silence the event bus."""
    recorded: list[dict[str, object]] = []

    async def _record(self: object, **kwargs: object) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
        lambda: type("Evo", (), {"record_execution": _record})(),
    )
    monkeypatch.setattr("myrm_agent_harness.runtime.events.get_event_bus", lambda: _FakeEventBus())
    return recorded


@pytest.mark.asyncio
async def test_failure_is_counted_for_the_single_loaded_skill(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing tool call with one loaded storage skill is counted as that skill's failed execution."""
    recorded = _install_ledger(monkeypatch)
    reset_loaded_skills()
    add_loaded_skill(SkillMetadata(name="a", description="a", storage_skill_id="skill-1"))
    try:
        track_skill_execution(
            "bash_code_execute_tool",
            tool_call_id="call-fail",
            tool_args={},
            success=False,
            error_message="Traceback\nValueError: bad input",
        )
        await asyncio.sleep(0)
    finally:
        reset_loaded_skills()

    assert recorded == [{"skill_id": "skill-1", "success": False, "error_message": "Traceback | ValueError: bad input"}]


@pytest.mark.asyncio
async def test_guard_blocked_call_is_not_counted_as_skill_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Policy blocks (e-stop, hooks, ...) say nothing about the skill, so they are not counted."""
    recorded = _install_ledger(monkeypatch)
    reset_loaded_skills()
    add_loaded_skill(SkillMetadata(name="a", description="a", storage_skill_id="skill-1"))
    try:
        track_skill_execution(
            "bash_code_execute_tool",
            tool_call_id="call-blocked",
            tool_args={},
            success=False,
            error_message="E-Stop active",
            error_category="estop",
        )
        await asyncio.sleep(0)
    finally:
        reset_loaded_skills()

    assert recorded == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "category",
    ["guardrail_blocked", "turn_budget_guard", "sandbox_boundary", "benchmark_blocked"],
)
async def test_policy_category_is_neither_counted_nor_published(monkeypatch: pytest.MonkeyPatch, category: str) -> None:
    """Guard, budget, sandbox-boundary and benchmark blocks are policy decisions, not skill defects."""
    recorded = _install_ledger(monkeypatch)
    fake_bus = _FakeEventBus()
    monkeypatch.setattr("myrm_agent_harness.runtime.events.get_event_bus", lambda: fake_bus)
    reset_loaded_skills()
    add_loaded_skill(SkillMetadata(name="a", description="a", storage_skill_id="skill-1"))
    try:
        track_skill_execution(
            "bash_code_execute_tool",
            tool_call_id="call-policy",
            tool_args={},
            success=False,
            error_message="blocked by policy",
            error_category=category,
        )
        await asyncio.sleep(0)
    finally:
        reset_loaded_skills()

    assert recorded == []
    assert fake_bus.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("success", [True, False])
async def test_loading_a_skill_is_not_an_execution_outcome(monkeypatch: pytest.MonkeyPatch, success: bool) -> None:
    """``skill_select_tool`` only loads the SOP; its result carries no evidence about skill quality."""
    recorded = _install_ledger(monkeypatch)
    fake_bus = _FakeEventBus()
    monkeypatch.setattr("myrm_agent_harness.runtime.events.get_event_bus", lambda: fake_bus)
    reset_loaded_skills()
    add_loaded_skill(SkillMetadata(name="a", description="a", storage_skill_id="skill-1"))
    try:
        track_skill_execution(
            "skill_select_tool",
            tool_call_id="call-select",
            tool_args={"skill_names": ["a"]},
            success=success,
            error_message="" if success else "load failed",
        )
        await asyncio.sleep(0)
    finally:
        reset_loaded_skills()

    assert recorded == []
    assert fake_bus.events == []


@pytest.mark.asyncio
async def test_failure_with_several_loaded_skills_is_not_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    """With several storage skills loaded the failing owner is ambiguous, so nothing is counted."""
    recorded = _install_ledger(monkeypatch)
    reset_loaded_skills()
    add_loaded_skill(SkillMetadata(name="a", description="a", storage_skill_id="s1"))
    add_loaded_skill(SkillMetadata(name="b", description="b", storage_skill_id="s2"))
    try:
        track_skill_execution(
            "bash_code_execute_tool",
            tool_call_id="call-ambiguous",
            tool_args={},
            success=False,
            error_message="boom",
        )
        await asyncio.sleep(0)
    finally:
        reset_loaded_skills()

    assert recorded == []


def test_failure_event_is_published_even_when_the_ledger_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Counting is best effort: a broken ledger lookup must never swallow the failure event."""
    fake_bus = _FakeEventBus()
    monkeypatch.setattr("myrm_agent_harness.runtime.events.get_event_bus", lambda: fake_bus)

    def _broken_ledger() -> object:
        raise RuntimeError("ledger offline")

    monkeypatch.setattr(
        "myrm_agent_harness.agent.skills.evolution.infra.integration.get_global_evolution_integration",
        _broken_ledger,
    )
    reset_loaded_skills()
    add_loaded_skill(SkillMetadata(name="a", description="a", storage_skill_id="skill-1"))
    try:
        track_skill_execution("tool", tool_call_id="c", tool_args={}, success=False, error_message="boom")
    finally:
        reset_loaded_skills()

    assert len(fake_bus.events) == 1


@pytest.fixture
def stats_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An open run scope writing to a throw-away ``.stats.json`` store, with the event bus silenced."""
    monkeypatch.setattr("myrm_agent_harness.runtime.events.get_event_bus", lambda: _FakeEventBus())
    set_stats_collector(SkillStatsCollector(tmp_path))
    begin_skill_run_usage()
    reset_loaded_skills()
    yield tmp_path
    reset_loaded_skills()
    begin_skill_run_usage()
    set_stats_collector(None)


def _load_skill(root: Path, name: str, skill_id: str) -> None:
    skill_dir = root / name
    skill_dir.mkdir()
    add_loaded_skill(SkillMetadata(name=name, description=name, storage_skill_id=skill_id, storage_path=str(skill_dir)))


def _stats_of(root: Path, name: str) -> SkillUsageStats:
    commit_skill_run_usage()
    flush_skill_usage_stats()
    return SkillStatsCollector(root).get_stats(root / name)


def test_run_outcomes_reach_the_stats_ledger_as_one_use(stats_ledger: Path) -> None:
    """Every tool call of the single loaded skill folds into one use whose outcome follows the majority."""
    _load_skill(stats_ledger, "a", "skill-1")

    track_skill_execution("tool", tool_call_id="c1", tool_args={}, success=False, error_message="boom")
    track_skill_execution("tool", tool_call_id="c2", tool_args={}, success=False, error_message="boom")
    track_skill_execution("tool", tool_call_id="c3", tool_args={}, success=True, error_message="")

    stats = _stats_of(stats_ledger, "a")
    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 0, 1)


def test_successful_run_is_recorded_as_success(stats_ledger: Path) -> None:
    _load_skill(stats_ledger, "a", "skill-1")

    track_skill_execution("tool", tool_call_id="c1", tool_args={}, success=True, error_message="")

    stats = _stats_of(stats_ledger, "a")
    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 1, 0)


def test_policy_block_leaves_no_trace_in_the_stats_ledger(stats_ledger: Path) -> None:
    _load_skill(stats_ledger, "a", "skill-1")

    track_skill_execution(
        "tool", tool_call_id="c1", tool_args={}, success=False, error_message="E-Stop", error_category="estop"
    )

    assert _stats_of(stats_ledger, "a").call_count == 0


def test_loading_a_skill_leaves_no_trace_in_the_stats_ledger(stats_ledger: Path) -> None:
    _load_skill(stats_ledger, "a", "skill-1")

    track_skill_execution(
        "skill_select_tool", tool_call_id="c1", tool_args={}, success=False, error_message="load failed"
    )

    assert _stats_of(stats_ledger, "a").call_count == 0


def test_ambiguous_owner_leaves_no_trace_in_the_stats_ledger(stats_ledger: Path) -> None:
    _load_skill(stats_ledger, "a", "s1")
    _load_skill(stats_ledger, "b", "s2")

    track_skill_execution("tool", tool_call_id="c1", tool_args={}, success=False, error_message="boom")

    assert _stats_of(stats_ledger, "a").call_count == 0
    assert _stats_of(stats_ledger, "b").call_count == 0
