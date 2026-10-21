"""Interrupt → stream event translation: one event per interrupt, each carrying the id of the pause it announces."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt

from myrm_agent_harness.agent.streaming.interrupt_events import INTERRUPT_ID_KEY, interrupt_events
from myrm_agent_harness.agent.streaming.types import AgentEventType


def _interrupt(value: object, interrupt_id: object = "id-1") -> SimpleNamespace:
    return SimpleNamespace(value=value, id=interrupt_id)


def test_each_interrupt_kind_maps_to_its_event_type_and_keeps_its_value() -> None:
    clarification = {"type": "ask_question", "form": {}}
    swarm = {"action_type": "swarm_fission", "tasks": []}
    tool_approval = {"actionRequests": [{"action": "bash"}]}
    other = {"tool_name": "x"}

    events = interrupt_events(
        [
            _interrupt(clarification, "a"),
            _interrupt(swarm, "b"),
            _interrupt(tool_approval, "c"),
            _interrupt(other, "d"),
        ],
        "msg-1",
        {},
    )

    assert [(e["type"], e["data"], e[INTERRUPT_ID_KEY]) for e in events] == [
        (AgentEventType.CLARIFICATION_REQUIRED.value, clarification, "a.0"),
        ("swarm_fission", swarm, "b.0"),
        (AgentEventType.TOOL_APPROVAL_REQUEST.value, tool_approval, "c.0"),
        (AgentEventType.APPROVAL_REQUIRED.value, other, "d.0"),
    ]
    assert {e["messageId"] for e in events} == {"msg-1"}


def test_an_empty_action_request_list_is_a_plain_approval() -> None:
    [event] = interrupt_events([_interrupt({"actionRequests": []})], "msg-1", {})

    assert event["type"] == AgentEventType.APPROVAL_REQUIRED.value


@pytest.mark.parametrize("missing_id", [None, "", 7])
def test_an_interrupt_without_a_usable_id_is_still_announced_without_the_key(missing_id: object) -> None:
    [event] = interrupt_events([_interrupt({"tool_name": "x"}, missing_id)], "msg-1", {})

    assert INTERRUPT_ID_KEY not in event


def test_each_card_id_carries_the_round_of_the_task_that_paused() -> None:
    events = interrupt_events([_interrupt({"tool_name": "x"}, "a"), _interrupt({"tool_name": "y"}, "b")], "m", {"b": 3})

    assert [e[INTERRUPT_ID_KEY] for e in events] == ["a.0", "b.3"]


def test_pauses_whose_rounds_are_unknown_carry_no_card_id() -> None:
    [event] = interrupt_events([_interrupt({"tool_name": "x"})], "msg-1", None)

    assert INTERRUPT_ID_KEY not in event


def test_an_interrupt_whose_value_is_not_a_dict_is_skipped() -> None:
    assert interrupt_events([_interrupt("plain text"), _interrupt(None)], "msg-1", {}) == []


class _ScriptedModel(FakeMessagesListChatModel):
    def bind_tools(self, tools: object, **kwargs: object) -> _ScriptedModel:
        return self


@tool
async def ask(topic: str) -> str:
    """Pause until the user answers."""
    return f"{topic}:{interrupt({'actionRequests': [{'action': topic}]})}"


@pytest.mark.asyncio
async def test_the_card_id_names_the_interrupt_langgraph_resumes_the_pending_pause_by() -> None:
    calls = [{"name": "ask", "args": {"topic": topic}, "id": f"call-{topic}"} for topic in ("alpha", "beta")]
    model = _ScriptedModel(responses=[AIMessage(content="", tool_calls=calls), AIMessage(content="done")])
    agent = create_agent(model=model, tools=[ask], checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "chat"}}

    announced: dict[str, str] = {}
    async for chunk in agent.astream({"messages": [("user", "go")]}, config, stream_mode="updates"):
        if "__interrupt__" in chunk:
            for event in interrupt_events(chunk["__interrupt__"], "msg-1", {}):
                announced[event["data"]["actionRequests"][0]["action"]] = event[INTERRUPT_ID_KEY]  # type: ignore[index]

    pending = {i.value["actionRequests"][0]["action"]: i.id for i in (await agent.aget_state(config)).interrupts}
    assert set(announced) == {"alpha", "beta"}
    assert announced == {action: f"{interrupt_id}.0" for action, interrupt_id in pending.items()}
