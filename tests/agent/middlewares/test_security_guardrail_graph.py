"""SecurityGuardrailMiddleware inside a real LangChain agent graph: what the model receives across calls and turns.

A unit test hands ``before_model`` a state. The graph decides which state it gets: after every tool call, behind the
runtime's own messages, and on the next turn through a checkpointer. These tests run ``create_agent`` end to end and
read the messages the model was sent.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from langchain.agents import create_agent
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import Field

from myrm_agent_harness.agent.middlewares._session_context import reset_terminal_errors, set_security_config
from myrm_agent_harness.agent.middlewares.security.security_guardrail_middleware import SecurityGuardrailMiddleware
from myrm_agent_harness.agent.security.types import PIIAction, PrivacyPolicy, SecurityConfig
from myrm_agent_harness.core.security.audit import get_audit_entries, reset_audit_log
from myrm_agent_harness.core.security.guards.privacy_tracker import reset_privacy_tracker

PHONE = "13812345678"
DANGEROUS = "drop database production;"
CAUTION = "[SAFETY_CAUTION:"

Content = str | list[str | dict[str, object]]


@tool
def ping() -> str:
    """Answer pong."""
    return "pong"


def _tool_call(call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": "ping", "args": {}}])


class ScriptedModel(BaseChatModel):
    """Answers from a script and records the user messages each call was sent."""

    script: list[AIMessage]
    calls: list[list[Content]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: object, **kwargs: object) -> ScriptedModel:
        return self

    def _generate(
        self, messages: list[BaseMessage], stop: list[str] | None = None, run_manager: object = None, **kwargs: object
    ) -> ChatResult:
        self.calls.append([m.content for m in messages if isinstance(m, HumanMessage)])
        reply = self.script[min(len(self.calls), len(self.script)) - 1]
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _agent(
    script: list[AIMessage], *, checkpointer: InMemorySaver | None = None
) -> tuple[ScriptedModel, CompiledStateGraph]:
    model = ScriptedModel(script=script)
    tools: list[BaseTool] = [ping]
    return model, create_agent(
        model, tools=tools, middleware=[SecurityGuardrailMiddleware()], checkpointer=checkpointer
    )


@pytest.fixture(autouse=True)
def _clean_session() -> Iterator[None]:
    reset_terminal_errors()
    set_security_config(None)
    reset_audit_log()
    reset_privacy_tracker()
    yield
    set_security_config(None)
    reset_terminal_errors()


async def test_the_user_message_is_the_same_on_every_call_of_a_turn() -> None:
    model, agent = _agent([_tool_call("c1"), _tool_call("c2"), _tool_call("c3"), AIMessage(content="done")])

    await agent.ainvoke({"messages": [HumanMessage(content=DANGEROUS)]})

    assert len(model.calls) == 4
    assert all(call == model.calls[0] for call in model.calls)
    assert model.calls[0][0].count(CAUTION) == 1


async def test_a_detection_is_audited_once_for_one_input() -> None:
    _, agent = _agent([_tool_call("c1"), _tool_call("c2"), AIMessage(content="done")])

    await agent.ainvoke({"messages": [HumanMessage(content=DANGEROUS)]})

    assert [entry.decision for entry in get_audit_entries()] == ["DANGEROUS_INTENT_DETECTED"]


async def test_earlier_turns_keep_their_bytes_on_the_next_turn() -> None:
    model, agent = _agent(
        [_tool_call("c1"), AIMessage(content="first done"), _tool_call("c2"), AIMessage(content="second done")],
        checkpointer=InMemorySaver(),
    )
    thread = {"configurable": {"thread_id": "t1"}}

    await agent.ainvoke({"messages": [HumanMessage(content=DANGEROUS)]}, thread)
    last_call_of_turn_one = model.calls[-1]
    await agent.ainvoke({"messages": [HumanMessage(content="thanks, what next?")]}, thread)

    first_call_of_turn_two = model.calls[len(model.calls) - 2]
    assert first_call_of_turn_two[: len(last_call_of_turn_one)] == last_call_of_turn_one
    assert all(call[0] == last_call_of_turn_one[0] for call in model.calls)
    assert last_call_of_turn_one[0].count(CAUTION) == 1


async def test_pii_is_redacted_when_the_runtime_appends_a_message_behind_the_user_message() -> None:
    set_security_config(
        SecurityConfig(
            privacy_policy=PrivacyPolicy(enabled=True, s2_action=PIIAction.REDACT, s3_action=PIIAction.REDACT)
        )
    )
    model, agent = _agent([AIMessage(content="noted")])
    board = HumanMessage(content="<working_board>\n**Goal**: ship it\n</working_board>")
    board.additional_kwargs["is_system_synthetic"] = True

    await agent.ainvoke({"messages": [HumanMessage(content=f"my phone is {PHONE}, remember it"), board]})

    assert PHONE not in model.calls[0][0]
