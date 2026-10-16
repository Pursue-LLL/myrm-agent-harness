"""A tool approval round trip through ``BaseAgent``: the card carries its interrupt id and the answer is bound to it.

The tool below is external to the harness, so the approval middleware pauses the run before it executes, exactly as it
does for a user's real tool call. Only the model is scripted.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from myrm_agent_harness.agent.base_agent import BaseAgent
from myrm_agent_harness.agent.streaming.interrupt_events import INTERRUPT_ID_KEY
from myrm_agent_harness.agent.streaming.types import AgentEventType


@tool
async def echo(topic: str) -> str:
    """Echo the topic back."""
    return f"ran:{topic}"


class _ScriptedLLM:
    """Asks for two echo calls in one message, then answers."""

    def __init__(self) -> None:
        self.calls = 0

    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedLLM:
        return self

    async def ainvoke(self, messages: object, config: object = None, **kwargs: object) -> AIMessage:
        self.calls += 1
        if self.calls == 1:
            calls = [{"name": "echo", "args": {"topic": t}, "id": f"call-{t}"} for t in ("alpha", "beta")]
            return AIMessage(content="", tool_calls=calls)
        return AIMessage(content="all done")


def _context(tmp_path: Path) -> dict[str, str]:
    return {"session_id": "chat-1", "workspace_path": str(tmp_path), "workspaces_storage_root": str(tmp_path)}


async def _run(agent: BaseAgent, query: str | Command[object], tmp_path: Path) -> list[dict[str, object]]:
    return [event async for event in agent.run(query=query, message_id="msg-1", context=_context(tmp_path))]


def _approvals(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [e for e in events if e.get("type") == AgentEventType.TOOL_APPROVAL_REQUEST.value]


def _answer(interrupt_id: str, action_count: int) -> Command[object]:
    return Command(resume={"decisions": [{"type": "approve"}] * action_count, INTERRUPT_ID_KEY: interrupt_id})


@pytest.mark.asyncio
async def test_the_approval_card_carries_the_interrupt_id_and_an_addressed_answer_resumes_the_run(
    tmp_path: Path,
) -> None:
    agent = BaseAgent(llm=_ScriptedLLM(), tools=[echo], checkpointer=MemorySaver())
    [card] = _approvals(await _run(agent, "go", tmp_path))
    interrupt_id = card[INTERRUPT_ID_KEY]
    assert isinstance(interrupt_id, str) and interrupt_id

    resumed = await _run(agent, _answer(interrupt_id, len(card["data"]["actionRequests"])), tmp_path)  # type: ignore[index]

    assert not _approvals(resumed)
    assert [e["data"] for e in resumed if e.get("type") == AgentEventType.MESSAGE.value] == ["all done"]


@pytest.mark.asyncio
async def test_an_answer_for_an_interrupt_that_is_not_pending_approves_nothing(tmp_path: Path) -> None:
    agent = BaseAgent(llm=_ScriptedLLM(), tools=[echo], checkpointer=MemorySaver())
    [card] = _approvals(await _run(agent, "go", tmp_path))
    action_count = len(card["data"]["actionRequests"])  # type: ignore[index]

    stale = await _run(agent, _answer("0" * 32, action_count), tmp_path)

    [still_pending] = _approvals(stale)
    assert still_pending[INTERRUPT_ID_KEY] == card[INTERRUPT_ID_KEY]
    assert not [e for e in stale if e.get("type") == AgentEventType.MESSAGE.value]
