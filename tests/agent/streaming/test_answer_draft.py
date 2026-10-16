"""Tests for AnswerDraft and the restart contract it encodes."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import Field

from myrm_agent_harness.agent.streaming.answer_draft import AnswerDraft, is_answer_restart
from myrm_agent_harness.agent.streaming.stream_executor import StreamContext, StreamExecutor
from myrm_agent_harness.agent.types import AgentRunStatistics
from myrm_agent_harness.core.events.types import AgentStreamEvent
from myrm_agent_harness.toolkits.llms.errors.classifier import ErrorKind


def _message(text: str) -> dict[str, object]:
    return {"type": "message", "data": text}


_TOOL_START: dict[str, object] = {"type": "tool_start"}
_FAILOVER_RESTART: dict[str, object] = {"type": "status", "step_key": "model_failover", "restart": True}


class TestIsAnswerRestart:
    def test_top_level_flag(self) -> None:
        assert is_answer_restart(_FAILOVER_RESTART)

    def test_nested_flag_on_model_escalated(self) -> None:
        assert is_answer_restart({"type": "model_escalated", "data": {"restart": True}})

    def test_hint_only_status_is_not_a_restart(self) -> None:
        assert not is_answer_restart({"type": "status", "step_key": "model_failover_unconfigured"})

    def test_flag_must_be_literal_true(self) -> None:
        assert not is_answer_restart({"type": "status", "restart": "yes"})
        assert not is_answer_restart({"type": "message", "data": "restart"})


class TestAnswerDraft:
    def test_accumulates_message_text(self) -> None:
        draft = AnswerDraft()
        assert not draft
        assert draft.feed(_message("Hello, "))
        assert draft.feed(_message("world"))
        assert draft.text == "Hello, world"
        assert draft

    def test_ignores_non_text_events(self) -> None:
        draft = AnswerDraft()
        assert not draft.feed({"type": "tasks_steps", "step_key": "lookup_tool"})
        assert not draft.feed({"type": "message", "data": {"unexpected": "shape"}})
        assert not draft.feed(_message(""))
        assert not draft
        assert not draft.feed({"type": "status", "step_key": "model_failover_unconfigured"})
        assert draft.text == ""

    def test_restart_drops_the_partial_answer(self) -> None:
        draft = AnswerDraft()
        draft.feed(_message("The capital of France is Pa"))
        assert draft.feed(_FAILOVER_RESTART)
        assert draft.text == ""
        draft.feed(_message("Paris is the capital of France."))
        assert draft.text == "Paris is the capital of France."

    def test_restart_keeps_text_streamed_before_a_tool_step(self) -> None:
        draft = AnswerDraft()
        draft.feed(_message("Let me check. "))
        draft.feed(_TOOL_START)
        draft.feed(_message("The capital of France is Pa"))
        assert draft.feed(_FAILOVER_RESTART)
        assert draft.text == "Let me check. "
        draft.feed(_message("Paris is the capital of France."))
        assert draft.text == "Let me check. Paris is the capital of France."

    def test_restart_without_in_flight_text_changes_nothing(self) -> None:
        draft = AnswerDraft()
        draft.feed(_message("Done. "))
        draft.feed(_TOOL_START)
        assert not draft.feed(_FAILOVER_RESTART)
        assert draft.text == "Done. "

    def test_consecutive_restarts_are_idempotent(self) -> None:
        draft = AnswerDraft()
        draft.feed(_message("partial"))
        assert draft.feed(_FAILOVER_RESTART)
        assert not draft.feed(_FAILOVER_RESTART)
        assert draft.text == ""

    def test_nested_escalation_restart_drops_the_segment(self) -> None:
        draft = AnswerDraft()
        draft.feed(_message("weak model draft"))
        assert draft.feed({"type": "model_escalated", "data": {"restart": True}})
        assert draft.text == ""

    def test_explicit_restart_matches_event_restart(self) -> None:
        draft = AnswerDraft()
        draft.feed(_message("a"))
        draft.feed(_TOOL_START)
        draft.feed(_message("b"))
        assert draft.restart()
        assert draft.text == "a"
        assert not draft.restart()


class _ScriptedLLM(BaseChatModel):
    """Chat model whose every call plays one scripted step: text pieces, optional tool call, optional failure."""

    steps: list[dict[str, object]] = Field(default_factory=list)
    model_name: str = "scripted"

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, *_args: object, **_kwargs: object) -> ChatResult:  # pragma: no cover - streaming only
        raise NotImplementedError

    async def _astream(
        self, messages: list[BaseMessage], *_args: object, **_kwargs: object
    ) -> AsyncIterator[ChatGenerationChunk]:
        step = self.steps.pop(0)
        for piece in step.get("text", []):  # type: ignore[union-attr]
            yield ChatGenerationChunk(message=AIMessageChunk(content=piece))
        if step.get("tool"):
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content="",
                    tool_call_chunks=[{"name": "lookup", "args": "{}", "id": "call_1", "index": 0}],
                )
            )
        if step.get("raise"):
            raise RuntimeError("upstream connection reset")


def _build_graph(llm: _ScriptedLLM, saver: InMemorySaver, tool_runs: list[str]) -> CompiledStateGraph:
    async def model(state: MessagesState, config: RunnableConfig) -> dict[str, list[AIMessage]]:
        return {"messages": [await llm.ainvoke(state["messages"], config)]}

    def tools(state: MessagesState) -> dict[str, list[ToolMessage]]:
        tool_runs.append("lookup")
        calls = getattr(state["messages"][-1], "tool_calls", [])
        return {"messages": [ToolMessage(content="France -> Paris", tool_call_id=call["id"]) for call in calls]}

    def route(state: MessagesState) -> str:
        return "tools" if getattr(state["messages"][-1], "tool_calls", None) else END

    graph = StateGraph(MessagesState)
    graph.add_node("model", model)
    graph.add_node("tools", tools)
    graph.add_edge(START, "model")
    graph.add_conditional_edges("model", route)
    graph.add_edge("tools", "model")
    return graph.compile(checkpointer=saver)


class _Compactor:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def put(self, event: object) -> None:
        self.events.append(event)

    async def flush(self) -> None:
        pass


@pytest.mark.asyncio
@patch("myrm_agent_harness.agent.hooks.executor.fire_hook", new_callable=AsyncMock)
async def test_failover_after_a_tool_step_leaves_the_pre_tool_text_intact(_fire_hook: AsyncMock) -> None:
    """A real graph + checkpointer: the fallback model resumes after the tool step, so only the segment
    that was in flight when the primary model failed may be superseded."""
    saver = InMemorySaver()
    tool_runs: list[str] = []
    primary = _ScriptedLLM(
        steps=[
            {"text": ["Let me check. "], "tool": True},
            {"text": ["The capital of France is Pa"], "raise": True},
        ]
    )
    fallback = _ScriptedLLM(steps=[{"text": ["Paris is the capital of France."]}])
    fallback.model_name = "backup-model"

    ctx = StreamContext(
        agent=_build_graph(primary, saver, tool_runs),
        agent_input={"messages": [HumanMessage(content="capital of France?")]},
        merged_context={"locale": "en"},
        run_config={"configurable": {"thread_id": "answer-draft-thread"}},
        stats=AgentRunStatistics(),
        message_id="answer-draft-message",
        cancel_token=None,
        steering_token=None,
        source_tracker=MagicMock(),
        output_queue=asyncio.Queue(),
    )
    executor = StreamExecutor(
        ctx=ctx,
        fallback_llm=fallback,
        safety_fallback_llm=None,
        rebuild_agent_fn=lambda _llm: _build_graph(fallback, saver, tool_runs),
    )
    compactor = _Compactor()
    executor._compactor = compactor

    with patch(
        "myrm_agent_harness.agent.streaming.recovery.stream_recovery.classify_error",
        return_value=ErrorKind.TIMEOUT,
    ):
        await executor.execute()

    draft = AnswerDraft()
    for event in compactor.events:
        # Recovery handlers emit plain dicts, the dispatcher emits AgentStreamEvent; the end-of-stream sentinel is neither.
        if isinstance(event, AgentStreamEvent):
            draft.feed(event.to_dict())
        elif isinstance(event, dict):
            draft.feed(event)

    assert draft.text == "Let me check. Paris is the capital of France."
    assert tool_runs == ["lookup"]
