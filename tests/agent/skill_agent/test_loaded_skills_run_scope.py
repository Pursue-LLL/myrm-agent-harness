"""A skill loaded inside a tool stays visible to everything that runs afterwards in the same run.

Tools run in copies of the run's context, so the loaded-skill list is one mutable list owned by the run;
every consumer (usage stats, failure events, trust attenuation, the model-call read point) sees the same skills.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import ToolException, tool

import myrm_agent_harness.agent.meta_tools.skills.select.skill_select_tool as select_mod
from myrm_agent_harness.agent.middlewares.tooling.tool_interceptor_middleware import tool_interceptor_middleware
from myrm_agent_harness.agent.skill_agent.context import (
    add_loaded_skill,
    get_loaded_skills,
    reset_loaded_skills,
    set_loaded_skills,
)
from myrm_agent_harness.backends.skills.stats_collector import SkillStatsCollector
from myrm_agent_harness.backends.skills.types import SkillMetadata, SkillTrust
from myrm_agent_harness.backends.skills.usage_recorder import (
    begin_skill_run_usage,
    commit_skill_run_usage,
    set_stats_collector,
)
from myrm_agent_harness.runtime.events import SkillFailureEvent


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class _LoadedSkillsAtModelCall(AgentMiddleware):
    """Reads the loaded skills where the skill attenuation middleware reads them: inside the model call."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[list[str]] = []

    async def awrap_model_call(self, request, handler):
        self.seen.append([skill.name for skill in get_loaded_skills()])
        return await handler(request)


@tool
async def work_tool() -> str:
    """Do work."""
    return "done"


@tool
async def failing_tool() -> str:
    """Fail like a broken skill script."""
    raise ToolException("FileNotFoundError: templates/weekly.pptx")


failing_tool.handle_tool_error = True


def _call(name: str, call_id: str, **args: object) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def _skill(
    name: str = "weekly_skill", trust: SkillTrust = SkillTrust.TRUSTED, root: Path | None = None
) -> SkillMetadata:
    if root is None:
        storage_path = tempfile.mkdtemp()
    else:
        storage_path = str(root / name)
        (root / name).mkdir()
    return SkillMetadata(
        name=name,
        description="d",
        storage_skill_id=f"{name}-id",
        storage_path=storage_path,
        trust=trust,
    )


class _Run:
    """One scripted agent run with the real select tool and the real tool interceptor."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, skill: SkillMetadata) -> None:
        self.events: list[SkillFailureEvent] = []
        self.reload_branch_hits = 0
        self.model_call_reads = _LoadedSkillsAtModelCall()
        self.skill = skill

        async def _document(*_args: object, **_kwargs: object) -> str:
            return "# skill document"

        async def _reload_summary(*_args: object, **_kwargs: object) -> str:
            self.reload_branch_hits += 1
            return "# reload summary"

        monkeypatch.setattr(select_mod, "get_skill_document", _document)
        monkeypatch.setattr(select_mod, "build_reload_summary_with_index", _reload_summary)
        monkeypatch.setattr(
            "myrm_agent_harness.runtime.events.get_event_bus",
            lambda: SimpleNamespace(
                publish=lambda event: self.events.append(event) if isinstance(event, SkillFailureEvent) else None
            ),
        )

    async def run(self, script: list[AIMessage]) -> list[ToolMessage]:
        select_tool = select_mod.create_select_skill_tool([self.skill], SimpleNamespace())
        agent = create_agent(
            _ScriptedModel(responses=[*script, AIMessage(content="finished")]),
            tools=[select_tool, work_tool, failing_tool],
            middleware=[tool_interceptor_middleware, self.model_call_reads],
        )
        result = await agent.ainvoke({"messages": [("user", "go")]})
        await asyncio.sleep(0.05)
        return [message for message in result["messages"] if isinstance(message, ToolMessage)]


@pytest.fixture(autouse=True)
def _clean_run_scope():
    reset_loaded_skills()
    begin_skill_run_usage()
    yield
    reset_loaded_skills()
    begin_skill_run_usage()  # drops whatever a test left pending instead of writing it to the default store
    set_stats_collector(None)


@pytest.mark.asyncio
async def test_skill_selected_mid_run_is_counted_and_reported_for_later_tool_calls(monkeypatch, tmp_path) -> None:
    collector = SkillStatsCollector()
    set_stats_collector(collector)
    skill = _skill(root=tmp_path)
    run = _Run(monkeypatch, skill)
    await run.run(
        [
            _call("skill_select_tool", "c1", skill_names=["weekly_skill"], reason="r"),
            _call("failing_tool", "c2"),
            _call("work_tool", "c3"),
            _call("failing_tool", "c4"),
        ]
    )
    commit_skill_run_usage()

    stats = collector.get_stats(tmp_path / "weekly_skill")
    assert (stats.call_count, stats.success_count, stats.failure_count) == (1, 0, 1)
    assert len(run.events) == 2
    assert [skill.name for skill in get_loaded_skills()] == ["weekly_skill"]


@pytest.mark.asyncio
async def test_model_call_after_the_selection_sees_the_loaded_skill(monkeypatch) -> None:
    run = _Run(monkeypatch, _skill())
    await run.run(
        [_call("skill_select_tool", "c1", skill_names=["weekly_skill"], reason="r"), _call("work_tool", "c2")]
    )

    assert run.model_call_reads.seen[0] == []
    assert all(names == ["weekly_skill"] for names in run.model_call_reads.seen[1:])


@pytest.mark.asyncio
async def test_installed_skill_selected_mid_run_restricts_the_tool_calls_that_follow(monkeypatch) -> None:
    run = _Run(monkeypatch, _skill(trust=SkillTrust.INSTALLED))
    tool_messages = await run.run(
        [_call("skill_select_tool", "c1", skill_names=["weekly_skill"], reason="r"), _call("work_tool", "c2")]
    )

    blocked = next(message for message in tool_messages if message.tool_call_id == "c2")
    assert blocked.status == "error"
    assert "trust attenuation" in str(blocked.content)


@pytest.mark.asyncio
async def test_selecting_a_loaded_skill_again_in_the_same_run_returns_the_reload_summary(monkeypatch) -> None:
    run = _Run(monkeypatch, _skill())
    await run.run(
        [
            _call("skill_select_tool", "c1", skill_names=["weekly_skill"], reason="first"),
            _call("skill_select_tool", "c2", skill_names=["weekly_skill"], reason="again"),
        ]
    )

    assert run.reload_branch_hits == 1


def test_get_loaded_skills_returns_a_snapshot() -> None:
    add_loaded_skill(_skill("a_skill"))

    snapshot = get_loaded_skills()
    snapshot.clear()

    assert [skill.name for skill in get_loaded_skills()] == ["a_skill"]


def test_add_loaded_skill_ignores_a_skill_that_is_already_loaded() -> None:
    add_loaded_skill(_skill("a_skill"))
    add_loaded_skill(_skill("a_skill"))

    assert [skill.name for skill in get_loaded_skills()] == ["a_skill"]


def test_add_loaded_skill_without_a_run_scope_still_records_in_the_current_context() -> None:
    from myrm_agent_harness.agent.skill_agent import context as skill_context

    skill_context._loaded_skills_var.set(None)
    add_loaded_skill(_skill("a_skill"))

    assert [skill.name for skill in get_loaded_skills()] == ["a_skill"]


@pytest.mark.asyncio
async def test_nested_run_scope_does_not_leak_into_the_parent_run() -> None:
    set_loaded_skills([_skill("parent_skill")])
    child_view: list[str] = []

    async def _nested_run() -> None:
        reset_loaded_skills()
        add_loaded_skill(_skill("child_skill"))
        child_view.extend(skill.name for skill in get_loaded_skills())

    await asyncio.create_task(_nested_run())

    assert child_view == ["child_skill"]
    assert [skill.name for skill in get_loaded_skills()] == ["parent_skill"]


@pytest.mark.asyncio
async def test_concurrent_runs_keep_separate_loaded_skills() -> None:
    views: dict[str, list[str]] = {}
    both_loaded = asyncio.Barrier(2)

    async def _run(name: str) -> None:
        reset_loaded_skills()
        add_loaded_skill(_skill(name))
        await both_loaded.wait()
        views[name] = [skill.name for skill in get_loaded_skills()]

    await asyncio.gather(asyncio.create_task(_run("first_skill")), asyncio.create_task(_run("second_skill")))

    assert views == {"first_skill": ["first_skill"], "second_skill": ["second_skill"]}
    assert get_loaded_skills() == []
