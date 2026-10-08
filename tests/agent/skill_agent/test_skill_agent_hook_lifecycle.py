"""SkillAgent hook lifecycle: framework hooks coexist with skill hooks that live for one run.

Skill hooks reach the registry through the real product chain, with no hand-built
metadata: SKILL.md stored in a ``LocalSkillBackend`` -> explicit ``[use skill]``
invocation -> run-scoped activation -> release when the run ends.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Iterator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.hooks import get_hook_executor, set_hook_executor
from myrm_agent_harness.agent.hooks.registry import HookRegistry
from myrm_agent_harness.agent.hooks.types import (
    CallableHookDefinition,
    CommandHookDefinition,
    HookDefinition,
    HookEvent,
    HookSource,
    HttpHookDefinition,
)
from myrm_agent_harness.agent.middlewares._session_context import set_event_logger
from myrm_agent_harness.agent.skill_agent import SkillAgent, wait_all_background_tasks
from myrm_agent_harness.agent.streaming.broadcast.tool_call_broadcaster import ToolCallBroadcaster
from myrm_agent_harness.backends.skills.local import LocalSkillBackend
from myrm_agent_harness.backends.skills.types import SkillMetadata


@pytest.fixture(autouse=True)
def fresh_hook_session() -> Iterator[None]:
    """Start every test from an empty hook registry, whatever earlier tests left in the context."""
    previous = get_hook_executor()
    set_hook_executor(None)
    yield
    set_hook_executor(previous)


def _write_skill(root: Path, name: str, hooks_yaml: str = "") -> None:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} probe skill\n{hooks_yaml}---\n# {name}\n\nDo the thing.\n",
        encoding="utf-8",
    )


def _audit_hooks(command: str, tools: str = "bash_*") -> str:
    return f"hooks:\n  PreToolUse:\n    - script: '{command}'\n      tools: [{tools}]\n"


@pytest.fixture
def skills_root(tmp_path: Path) -> Path:
    root = tmp_path / "skills"
    root.mkdir()
    _write_skill(root, "alpha", _audit_hooks("echo alpha"))
    _write_skill(root, "beta", _audit_hooks("echo beta", "write_file_tool"))
    _write_skill(root, "plain")
    return root


@pytest.fixture
def agent(skills_root: Path) -> SkillAgent:
    return SkillAgent(llm=AsyncMock(), skill_backend=LocalSkillBackend(skills_root))


def _registry() -> HookRegistry:
    executor = get_hook_executor()
    assert executor is not None
    return executor.registry


def _skill_commands(event: HookEvent = HookEvent.PRE_TOOL_USE) -> list[str]:
    return [hook.command for hook in _registry().get(event) if isinstance(hook, CommandHookDefinition)]


def _callable_names(event: HookEvent) -> list[str]:
    return [hook.fn.__name__ for hook in _registry().get(event) if isinstance(hook, CallableHookDefinition)]


async def _skills(agent: SkillAgent, *names: str) -> list[SkillMetadata]:
    available = {skill.name: skill for skill in await agent._get_cached_skills()}
    return [available[name] for name in names]


# --- framework hooks -------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_framework_hooks_register_once_per_session(agent: SkillAgent) -> None:
    agent._init_hook_lifecycle()
    agent._init_hook_lifecycle()

    assert _callable_names(HookEvent.PRE_TOOL_USE) == ["on_pre_tool_use"]
    assert _callable_names(HookEvent.APPROVAL_CORRECTION) == ["on_approval_correction"]


@pytest.mark.asyncio
async def test_tool_events_reach_the_logger_the_run_installs_after_registration(agent: SkillAgent) -> None:
    """``SkillAgent.run`` registers framework hooks before the runtime creates the run's event logger."""
    agent._init_hook_lifecycle()
    broadcaster = next(
        hook.fn.__self__
        for hook in _registry().get(HookEvent.PRE_TOOL_USE)
        if isinstance(hook, CallableHookDefinition) and hook.fn.__name__ == "on_pre_tool_use"
    )
    assert isinstance(broadcaster, ToolCallBroadcaster)
    broadcaster._event_bus = AsyncMock()
    run_logger = AsyncMock()
    set_event_logger(run_logger)

    executor = get_hook_executor()
    assert executor is not None
    await executor.execute(
        HookEvent.PRE_TOOL_USE.value, {"tool_name": "bash_code_execute_tool", "tool_call_id": "tc_1"}
    )

    run_logger.log.assert_awaited_once()
    assert run_logger.log.await_args.args[0] == "tool_start"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hook",
    [
        CommandHookDefinition(command="echo ok", source=HookSource.SKILL),
        HttpHookDefinition(url="https://example.invalid/hook", source=HookSource.SKILL),
    ],
    ids=["command", "http"],
)
async def test_non_callable_skill_hook_on_pre_tool_use_does_not_break_framework_init(
    agent: SkillAgent, hook: HookDefinition
) -> None:
    skill = SkillMetadata(name="probe", description="probe", hooks=[(HookEvent.PRE_TOOL_USE, hook)])

    activation = await agent._activate_skill_hooks([skill])
    agent._init_hook_lifecycle()

    assert hook in _registry().get(HookEvent.PRE_TOOL_USE)
    assert _callable_names(HookEvent.PRE_TOOL_USE) == ["on_pre_tool_use"]
    activation.release()


# --- skill hooks: activation from the stored SKILL.md ----------------------------------------------


@pytest.mark.asyncio
async def test_hooks_declared_in_stored_skill_md_are_activated_and_released(agent: SkillAgent) -> None:
    (alpha,) = await _skills(agent, "alpha")

    activation = await agent._activate_skill_hooks([alpha])

    (hook,) = [h for h in _registry().get(HookEvent.PRE_TOOL_USE) if isinstance(h, CommandHookDefinition)]
    assert (hook.command, hook.matcher, hook.source) == ("echo alpha", "bash_*", HookSource.SKILL)
    activation.release()
    assert _skill_commands() == []


@pytest.mark.asyncio
async def test_every_skill_of_a_bundle_contributes_its_hooks(agent: SkillAgent) -> None:
    skills = await _skills(agent, "alpha", "beta", "plain")

    activation = await agent._activate_skill_hooks(skills)

    assert sorted(_skill_commands()) == ["echo alpha", "echo beta"]
    activation.release()
    assert _skill_commands() == []


@pytest.mark.asyncio
async def test_skill_without_hooks_registers_nothing(agent: SkillAgent) -> None:
    (plain,) = await _skills(agent, "plain")

    activation = await agent._activate_skill_hooks([plain])

    assert activation.scopes == ()
    assert _registry().total_count == 0


@pytest.mark.asyncio
async def test_metadata_hooks_take_precedence_without_a_backend() -> None:
    hook = CommandHookDefinition(command="echo meta", source=HookSource.SKILL)
    skill = SkillMetadata(name="meta", description="d", hooks=[(HookEvent.PRE_TOOL_USE, hook)])

    activation = await SkillAgent(llm=AsyncMock())._activate_skill_hooks([skill])

    assert _skill_commands() == ["echo meta"]
    activation.release()


@pytest.mark.asyncio
async def test_unreadable_skill_md_yields_no_hooks_and_never_raises(agent: SkillAgent, skills_root: Path) -> None:
    (alpha,) = await _skills(agent, "alpha")
    (skills_root / "alpha" / "SKILL.md").unlink()

    activation = await agent._activate_skill_hooks([alpha])

    assert activation.scopes == ()


# --- skill hooks: lifetime ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_hooks_neither_accumulate_nor_leak_across_runs_in_one_context(agent: SkillAgent) -> None:
    alpha, beta = await _skills(agent, "alpha", "beta")

    for _ in range(3):
        activation = await agent._activate_skill_hooks([alpha])
        assert _skill_commands() == ["echo alpha"]
        activation.release()

    activation = await agent._activate_skill_hooks([beta])
    assert _skill_commands() == ["echo beta"]
    activation.release()
    assert _skill_commands() == []


@pytest.mark.asyncio
async def test_nested_run_of_the_same_skill_neither_duplicates_nor_releases_the_outer_hooks(agent: SkillAgent) -> None:
    (alpha,) = await _skills(agent, "alpha")

    outer = await agent._activate_skill_hooks([alpha])
    inner = await agent._activate_skill_hooks([alpha])

    assert inner.scopes == ()
    assert _skill_commands() == ["echo alpha"]
    inner.release()
    assert _skill_commands() == ["echo alpha"]
    outer.release()
    assert _skill_commands() == []


# --- run(): the wiring users actually hit ----------------------------------------------------------


@pytest.fixture
def streamed_hooks(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Replace the LLM loop with a two-event stream that records the skill hooks live while it runs."""
    seen: list[list[str]] = []

    async def fake_run(self: BaseAgent, query: object, **_: object) -> AsyncGenerator[dict[str, object]]:
        seen.append(_skill_commands())
        yield {"type": "message", "data": "first"}
        seen.append(_skill_commands())
        yield {"type": "message", "data": "second"}

    monkeypatch.setattr(BaseAgent, "run", fake_run)
    return seen


@pytest.mark.asyncio
async def test_use_prefix_activates_only_for_the_streaming_run(
    agent: SkillAgent, streamed_hooks: list[list[str]]
) -> None:
    events = [event async for event in agent.run("[use alpha] audit my shell")]
    await wait_all_background_tasks()

    assert len(events) == 2
    assert streamed_hooks == [["echo alpha"], ["echo alpha"]]
    assert _skill_commands() == []


@pytest.mark.asyncio
async def test_use_prefix_bundle_activates_every_named_skill(
    agent: SkillAgent, streamed_hooks: list[list[str]]
) -> None:
    _ = [event async for event in agent.run("[use alpha,beta] audit")]
    await wait_all_background_tasks()

    assert [sorted(commands) for commands in streamed_hooks] == [["echo alpha", "echo beta"]] * 2
    assert _skill_commands() == []


@pytest.mark.asyncio
async def test_without_explicit_invocation_no_skill_hooks_activate(
    agent: SkillAgent, streamed_hooks: list[list[str]]
) -> None:
    _ = [event async for event in agent.run("please audit my shell")]
    await wait_all_background_tasks()

    assert streamed_hooks == [[], []]


@pytest.mark.asyncio
async def test_active_skill_argument_activates_that_skill(agent: SkillAgent, streamed_hooks: list[list[str]]) -> None:
    (alpha,) = await _skills(agent, "alpha")

    _ = [event async for event in agent.run("audit", active_skill=alpha)]
    await wait_all_background_tasks()

    assert streamed_hooks == [["echo alpha"], ["echo alpha"]]
    assert _skill_commands() == []


# --- HITL resume: a new run of the interrupted turn --------------------------------------------------


def _resume() -> Command[object]:
    return Command(resume={"decision": "approve"})


_IMAGE_PART = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chat_history", "expected"),
    [
        ([["human", "[use alpha] audit my shell"], ["assistant", "let me run it"]], ["echo alpha"]),
        ([["human", "[use alpha,beta] audit"], ["assistant", "partial"]], ["echo alpha", "echo beta"]),
        ([["human", [{"type": "text", "text": "[use alpha] look"}, _IMAGE_PART]]], ["echo alpha"]),
        (
            [
                ["human", "[use alpha] earlier"],
                ["assistant", "done"],
                ["human", "plain follow-up"],
                ["assistant", "partial"],
            ],
            [],
        ),
        ([["human", "[use ghost] audit"]], []),
        ([], []),
        (None, []),
    ],
    ids=["single", "bundle", "multimodal", "earlier-turn-only", "unknown-skill", "empty-history", "no-history"],
)
async def test_resume_brings_back_the_hooks_of_the_interrupted_turn(
    agent: SkillAgent,
    streamed_hooks: list[list[str]],
    chat_history: list[list[object]] | None,
    expected: list[str],
) -> None:
    _ = [event async for event in agent.run(_resume(), chat_history=chat_history)]
    await wait_all_background_tasks()

    assert [sorted(commands) for commands in streamed_hooks] == [expected] * 2
    assert _skill_commands() == []


@pytest.mark.asyncio
async def test_resume_skips_extension_custom_messages_when_finding_the_users_turn(
    agent: SkillAgent, streamed_hooks: list[list[str]]
) -> None:
    history = [
        HumanMessage(content="[use alpha] audit"),
        AIMessage(content="partial"),
        HumanMessage(content="extension context", additional_kwargs={"is_custom_message": True}),
    ]

    _ = [event async for event in agent.run(_resume(), chat_history=history)]
    await wait_all_background_tasks()

    assert streamed_hooks == [["echo alpha"], ["echo alpha"]]


@pytest.mark.asyncio
async def test_new_turn_does_not_inherit_the_hooks_of_earlier_turns(
    agent: SkillAgent, streamed_hooks: list[list[str]]
) -> None:
    history = [["human", "[use alpha] earlier"], ["assistant", "done"]]

    _ = [event async for event in agent.run("a new question", chat_history=history)]
    await wait_all_background_tasks()

    assert streamed_hooks == [[], []]


@pytest.mark.asyncio
async def test_consecutive_runs_in_one_context_do_not_leak_skill_hooks(
    agent: SkillAgent, streamed_hooks: list[list[str]]
) -> None:
    for query in ("[use alpha] one", "[use beta] two", "[use alpha] three", "plain question"):
        _ = [event async for event in agent.run(query)]
    await wait_all_background_tasks()

    assert [commands for commands in streamed_hooks[::2]] == [["echo alpha"], ["echo beta"], ["echo alpha"], []]


@pytest.mark.asyncio
async def test_hooks_are_released_when_the_consumer_stops_early(
    agent: SkillAgent, streamed_hooks: list[list[str]]
) -> None:
    stream = agent.run("[use alpha] audit")
    await anext(stream)
    assert _skill_commands() == ["echo alpha"]

    await stream.aclose()
    await wait_all_background_tasks()

    assert _skill_commands() == []


@pytest.mark.asyncio
async def test_hooks_are_released_when_the_stream_fails(agent: SkillAgent, monkeypatch: pytest.MonkeyPatch) -> None:
    async def failing_run(self: BaseAgent, query: object, **_: object) -> AsyncGenerator[dict[str, object]]:
        yield {"type": "message", "data": "partial"}
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(BaseAgent, "run", failing_run)

    with pytest.raises(RuntimeError, match="model unavailable"):
        _ = [event async for event in agent.run("[use alpha] audit")]
    await wait_all_background_tasks()

    assert _skill_commands() == []
