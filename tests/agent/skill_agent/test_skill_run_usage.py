"""``SkillAgent.run`` turns a run's skill activity into exactly one Curator use per skill.

The LLM loop is replaced by a scripted stream; selection, attribution of tool outcomes and the run-end
write all go through the real product chain (``[use skill]`` preload -> ``track_skill_execution`` ->
``commit_skill_run_usage`` -> ``.stats.json``).
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Callable, Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.middlewares.tooling._skill_failure_tracking import track_skill_execution
from myrm_agent_harness.agent.skill_agent import SkillAgent, wait_all_background_tasks
from myrm_agent_harness.backends.skills.local import LocalSkillBackend
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillUsageStats
from myrm_agent_harness.backends.skills.usage_recorder import set_stats_collector
from myrm_agent_harness.runtime.events import SkillFailureEvent

_Script = Callable[[], None]


class _SilentBus:
    def publish(self, event: SkillFailureEvent) -> None:
        pass


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    skill_dir = root / "alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("---\nname: alpha\ndescription: alpha probe\n---\n# alpha\n\nDo it.\n")
    return root


@pytest.fixture(autouse=True)
def stats_ledger(tmp_path: Path, skills_root: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr("myrm_agent_harness.runtime.events.get_event_bus", lambda: _SilentBus())
    set_stats_collector(SkillStatsCollector(tmp_path))
    yield
    set_stats_collector(None)


def _script_run(monkeypatch: pytest.MonkeyPatch, *tool_calls: _Script) -> None:
    async def fake_run(self: BaseAgent, query: object, **_: object) -> AsyncGenerator[dict[str, object]]:
        for call in tool_calls:
            call()
            yield {"type": "message", "data": "tick"}
        yield {"type": "message", "data": "done"}

    monkeypatch.setattr(BaseAgent, "run", fake_run)


def _tool(*, success: bool) -> _Script:
    return lambda: track_skill_execution(
        "bash_code_execute_tool",
        tool_call_id="c",
        tool_args={},
        success=success,
        error_message="" if success else "boom",
    )


async def _run(skills_root: Path, query: str) -> SkillUsageStats:
    agent = SkillAgent(llm=AsyncMock(), skill_backend=LocalSkillBackend(skills_root))
    _ = [event async for event in agent.run(query)]
    await wait_all_background_tasks()
    return SkillStatsCollector(skills_root).get_stats(skills_root / "alpha")


@pytest.mark.asyncio
async def test_run_with_mostly_failing_tools_is_one_failed_use(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script_run(monkeypatch, _tool(success=False), _tool(success=True), _tool(success=False))

    stats = await _run(skills_root, "[use alpha] go")

    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 0, 1)
    assert [record.success for record in stats.usage_history] == [False]


@pytest.mark.asyncio
async def test_run_with_only_successful_tools_is_one_successful_use(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _script_run(monkeypatch, _tool(success=True), _tool(success=True))

    stats = await _run(skills_root, "[use alpha] go")

    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 1, 0)


@pytest.mark.asyncio
async def test_run_without_tool_calls_is_an_unobserved_use(skills_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _script_run(monkeypatch)

    stats = await _run(skills_root, "[use alpha] go")

    assert (stats.call_count, stats.observed_count) == (1, 0)
    assert [record.success for record in stats.usage_history] == [None]


@pytest.mark.asyncio
async def test_run_without_a_skill_writes_nothing(skills_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _script_run(monkeypatch, _tool(success=False))

    stats = await _run(skills_root, "no skill involved")

    assert stats.call_count == 0


@pytest.mark.asyncio
async def test_consecutive_runs_are_separate_uses(skills_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _script_run(monkeypatch, _tool(success=True))
    await _run(skills_root, "[use alpha] first")

    stats = await _run(skills_root, "[use alpha] second")

    assert (stats.call_count, stats.success_count) == (2, 2)


@pytest.mark.asyncio
async def test_run_abandoned_midway_still_writes_its_use(skills_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Closing the stream early (client disconnect) must not lose the use that already happened."""
    _script_run(monkeypatch, _tool(success=False), _tool(success=False))
    agent = SkillAgent(llm=AsyncMock(), skill_backend=LocalSkillBackend(skills_root))

    stream = agent.run("[use alpha] go")
    await anext(stream)
    await stream.aclose()

    # Already on disk before the session cleanup task runs: a process exiting right here keeps the use.
    stats = SkillStatsCollector(skills_root).get_stats(skills_root / "alpha")
    assert (stats.call_count, stats.failure_count) == (1, 1)
    await wait_all_background_tasks()
