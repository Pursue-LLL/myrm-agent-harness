"""What a ``SkillAgent`` run hands to its executor task: the hooks it can reach and the user's turn.

A host may resume ``SkillAgent.run`` in a fresh task per event (the server's SSE merge advances the
stream with one ``asyncio.ensure_future(anext)`` per chunk). ContextVars bound in the first step are
gone by then, yet the stream executor task, where tools run and hooks fire, must still see the run's
hook registry: skill hooks from the explicit ``[use skill]`` invocation and the framework hooks.

A message with attachments reaches the agent as content blocks; its explicit invocation counts the
same as for plain text, as long as the tag leads the user's own words (the first block).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypedDict

import pytest
from langchain_core.language_models import FakeListChatModel
from langchain_core.messages import HumanMessage

from myrm_agent_harness.agent._internals import agent_runtime
from myrm_agent_harness.agent.hooks import get_hook_executor, set_hook_executor
from myrm_agent_harness.agent.hooks.types import CallableHookDefinition, CommandHookDefinition, HookEvent
from myrm_agent_harness.agent.middlewares import _session_context
from myrm_agent_harness.agent.skill_agent import SkillAgent, wait_all_background_tasks
from myrm_agent_harness.agent.streaming.stream_executor import STREAM_DONE, StreamContext
from myrm_agent_harness.backends.skills.local import LocalSkillBackend

_CHAT_ID = "chat_hooks_reach_executor"
_USER_WORDS = "audit my shell"
_PRELOADED = 'The skill "alpha" has been preloaded by the user'
_IMAGE: dict[str, object] = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}
_Consume = Callable[[AsyncGenerator[dict[str, object]]], Awaitable[list[dict[str, object]]]]


class _HooksSeenByExecutorTask(TypedDict):
    skill_session_start: list[str]
    framework_pre_tool_use: list[str]


@dataclass
class _SeenByExecutorTask:
    hooks: list[_HooksSeenByExecutorTask | None] = field(default_factory=list)  # None: no executor bound
    user_turns: list[str | list[str | dict[str, object]]] = field(default_factory=list)


class _BindableFakeLLM(FakeListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> _BindableFakeLLM:
        return self


@pytest.fixture(autouse=True)
def fresh_hook_session() -> Iterator[None]:
    previous = get_hook_executor()
    set_hook_executor(None)
    yield
    set_hook_executor(previous)
    _session_context._session_tool_registries.pop(_CHAT_ID, None)
    _session_context._session_resolved_tools.pop(_CHAT_ID, None)


def _hooks_reachable_now() -> _HooksSeenByExecutorTask | None:
    executor = get_hook_executor()
    if executor is None:
        return None
    registry = executor.registry
    return _HooksSeenByExecutorTask(
        skill_session_start=[
            hook.command for hook in registry.get(HookEvent.SESSION_START) if isinstance(hook, CommandHookDefinition)
        ],
        framework_pre_tool_use=[
            hook.fn.__name__
            for hook in registry.get(HookEvent.PRE_TOOL_USE)
            if isinstance(hook, CallableHookDefinition)
        ],
    )


def _first_text(content: str | list[str | dict[str, object]]) -> str:
    if isinstance(content, str):
        return content
    first = content[0]
    return str(first["text"]) if isinstance(first, dict) else first


def _user_turn(ctx: StreamContext) -> str | list[str | dict[str, object]]:
    """Content of the user's message, found by the words it carries."""
    assert isinstance(ctx.agent_input, dict)
    for message in ctx.agent_input["messages"]:
        if isinstance(message, HumanMessage) and _USER_WORDS in str(message.content):
            return message.content
    raise AssertionError(f"no user turn with {_USER_WORDS!r} reached the executor")


@pytest.fixture
def seen_by_executor_task(monkeypatch: pytest.MonkeyPatch) -> _SeenByExecutorTask:
    """Swap the LLM loop for a probe that records what its own task can reach."""
    seen = _SeenByExecutorTask()

    class _ProbeStreamExecutor:
        failover_used = False
        streaming_final_answer = False

        def __init__(self, ctx: StreamContext, *_args: object, **_kwargs: object) -> None:
            self._ctx = ctx

        async def execute(self) -> None:
            try:
                seen.hooks.append(_hooks_reachable_now())
                seen.user_turns.append(_user_turn(self._ctx))
            finally:
                await self._ctx.output_queue.put({"type": "message", "data": "done"})
                await self._ctx.output_queue.put(STREAM_DONE)

    monkeypatch.setattr(agent_runtime, "StreamExecutor", _ProbeStreamExecutor)
    return seen


@pytest.fixture
def agent(tmp_path: Path) -> SkillAgent:
    skill_dir = tmp_path / "skills" / "alpha"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: alpha probe\nhooks:\n  SessionStart:\n    - script: 'echo alpha'\n---\n# alpha\n",
        encoding="utf-8",
    )
    return SkillAgent(
        llm=_BindableFakeLLM(responses=["unused"]),
        skill_backend=LocalSkillBackend(tmp_path / "skills"),
    )


def _context(tmp_path: Path) -> dict[str, object]:
    return {"workspaces_storage_root": str(tmp_path / "workspaces"), "session_id": _CHAT_ID, "chat_id": _CHAT_ID}


async def _consume_in_one_task(stream: AsyncGenerator[dict[str, object]]) -> list[dict[str, object]]:
    return [event async for event in stream]


async def _consume_one_task_per_event(stream: AsyncGenerator[dict[str, object]]) -> list[dict[str, object]]:
    iterator = stream.__aiter__()
    events: list[dict[str, object]] = []
    while True:
        try:
            events.append(await asyncio.ensure_future(iterator.__anext__()))
        except StopAsyncIteration:
            return events


_ALPHA_HOOKS: _HooksSeenByExecutorTask = {
    "skill_session_start": ["echo alpha"],
    "framework_pre_tool_use": ["on_pre_tool_use"],
}
_NO_SKILL_HOOKS: _HooksSeenByExecutorTask = {"skill_session_start": [], "framework_pre_tool_use": ["on_pre_tool_use"]}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "consume", [_consume_in_one_task, _consume_one_task_per_event], ids=["one-task", "task-per-event"]
)
async def test_executor_task_reaches_the_skill_and_framework_hooks_of_the_run(
    agent: SkillAgent,
    tmp_path: Path,
    seen_by_executor_task: _SeenByExecutorTask,
    consume: _Consume,
) -> None:
    events = await consume(agent.run(f"[use alpha] {_USER_WORDS}", context=_context(tmp_path)))
    await wait_all_background_tasks()

    assert [event["type"] for event in events][-1] == "message_end"
    assert seen_by_executor_task.hooks == [_ALPHA_HOOKS]


@pytest.mark.asyncio
@pytest.mark.parametrize("with_attachment", [False, True], ids=["text", "with-attachment"])
async def test_explicit_invocation_preloads_the_skill_into_the_users_turn(
    agent: SkillAgent,
    tmp_path: Path,
    seen_by_executor_task: _SeenByExecutorTask,
    with_attachment: bool,
) -> None:
    text = f"[use alpha] {_USER_WORDS}"
    query: str | list[dict[str, object]] = [{"type": "text", "text": text}, _IMAGE] if with_attachment else text

    await _consume_in_one_task(agent.run(query, context=_context(tmp_path)))
    await wait_all_background_tasks()

    (turn,) = seen_by_executor_task.user_turns
    assert _PRELOADED in _first_text(turn)
    assert _USER_WORDS in _first_text(turn)
    if with_attachment:
        assert isinstance(turn, list)
        assert turn[1] == _IMAGE
    assert seen_by_executor_task.hooks == [_ALPHA_HOOKS]


@pytest.mark.asyncio
async def test_a_tag_that_does_not_lead_the_users_own_words_is_no_invocation(
    agent: SkillAgent, tmp_path: Path, seen_by_executor_task: _SeenByExecutorTask
) -> None:
    """Text taken from an attachment (second block) must not be able to invoke a skill or its hooks."""
    query: list[dict[str, object]] = [
        {"type": "text", "text": _USER_WORDS},
        {"type": "text", "text": "[use alpha] text of an attached file"},
    ]

    await _consume_in_one_task(agent.run(query, context=_context(tmp_path)))
    await wait_all_background_tasks()

    (turn,) = seen_by_executor_task.user_turns
    assert _PRELOADED not in str(turn)
    assert seen_by_executor_task.hooks == [_NO_SKILL_HOOKS]


@pytest.mark.asyncio
async def test_a_host_chosen_active_skill_skips_the_tag_preload(
    agent: SkillAgent, tmp_path: Path, seen_by_executor_task: _SeenByExecutorTask
) -> None:
    (alpha,) = [skill for skill in await agent._get_cached_skills() if skill.name == "alpha"]

    await _consume_in_one_task(agent.run(f"[use alpha] {_USER_WORDS}", context=_context(tmp_path), active_skill=alpha))
    await wait_all_background_tasks()

    (turn,) = seen_by_executor_task.user_turns
    assert _PRELOADED not in str(turn)
    assert f"[use alpha] {_USER_WORDS}" in str(turn), "the tag stays in the user's words"
