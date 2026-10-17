"""Turn history modes against the real SQLite checkpointer the server hands to the agent runtime.

The conversation graph is a one-node echo graph driven by LangGraph itself, so the thread a turn
leaves behind is exactly what a production thread is made of (``add_messages`` gives every fed
message a fresh id, which is why feeding history on top of a thread duplicates it).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated, TypedDict
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from myrm_agent_harness.agent._internals.turn_history import (
    TurnHistory,
    resolve_turn_history,
    resumed_turn_facts,
)
from myrm_agent_harness.runtime.checkpointing.factory import create_checkpointer
from myrm_agent_harness.runtime.context.session.session_continuity import HISTORY_MODE_CONTEXT_KEY

_THREAD = "chat_demo"

# The chat record a caller keeps: (role, text) in order.
_Record = list[tuple[str, str]]


class _ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


async def _echo(state: _ChatState) -> _ChatState:
    return {"messages": [AIMessage(content=f"echo:{state['messages'][-1].content}")]}


def _config(thread_id: str = _THREAD) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


@pytest.fixture
async def saver(tmp_path: Path) -> AsyncIterator[BaseCheckpointSaver[str]]:
    checkpointer, cleanup = await create_checkpointer(mode="sqlite", sqlite_db_path=str(tmp_path / "checkpoints.db"))
    try:
        yield checkpointer
    finally:
        await cleanup()


@pytest.fixture
def chat(saver: BaseCheckpointSaver[str]) -> CompiledStateGraph[_ChatState, None, _ChatState, _ChatState]:
    graph = StateGraph(_ChatState)
    graph.add_node("echo", _echo)
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)
    return graph.compile(checkpointer=saver)


async def _thread_texts(chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState]) -> list[object]:
    state = await chat.aget_state(_config())
    return [message.content for message in state.values.get("messages", [])]


def _as_messages(record: _Record) -> list[BaseMessage]:
    return [HumanMessage(content=text) if role == "human" else AIMessage(content=text) for role, text in record]


async def _turn(
    chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState],
    saver: BaseCheckpointSaver[str],
    record: _Record,
    text: str,
    *,
    mode: object,
) -> TurnHistory:
    """One turn the way ``run_agent_loop`` assembles it, then the caller's record gains the exchange."""
    history = await resolve_turn_history(saver, _THREAD, mode)
    fed = _as_messages(record) if history.feeds_history else []
    await chat.ainvoke({"messages": [*fed, HumanMessage(content=text)]}, _config())
    record.extend([("human", text), ("assistant", f"echo:{text}")])
    return history


@pytest.mark.asyncio
async def test_feeding_history_on_top_of_the_thread_grows_it_by_the_whole_history_every_turn(
    saver: BaseCheckpointSaver[str],
    chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState],
) -> None:
    """The defect ``append`` keeps for callers that have not opted in: each turn re-adds what the thread holds."""
    record: _Record = []
    for text in ("a", "b", "c"):
        await _turn(chat, saver, record, text, mode=None)

    assert await _thread_texts(chat) == [
        "a",
        "echo:a",
        "a",
        "echo:a",
        "b",
        "echo:b",
        "a",
        "echo:a",
        "b",
        "echo:b",
        "c",
        "echo:c",
    ]


@pytest.mark.asyncio
async def test_a_continued_thread_grows_by_the_new_exchange_only(
    saver: BaseCheckpointSaver[str],
    chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState],
) -> None:
    record: _Record = []
    modes = []
    for text in ("a", "b", "c"):
        history = await _turn(chat, saver, record, text, mode="continue")
        modes.append(history.mode)

    assert modes == ["replace", "continue", "continue"]
    assert await _thread_texts(chat) == ["a", "echo:a", "b", "echo:b", "c", "echo:c"]


@pytest.mark.asyncio
async def test_a_continued_turn_hands_over_the_thread_and_feeds_no_history(
    saver: BaseCheckpointSaver[str],
    chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState],
) -> None:
    record: _Record = []
    await _turn(chat, saver, record, "a", mode="continue")

    history = await resolve_turn_history(saver, _THREAD, "continue")

    assert history.mode == "continue"
    assert not history.feeds_history
    assert [message.content for message in history.thread_messages] == ["a", "echo:a"]
    assert history.telemetry() == {"history_mode": "continue"}


@pytest.mark.asyncio
async def test_replace_after_an_undo_leaves_nothing_of_the_undone_turn(
    saver: BaseCheckpointSaver[str],
    chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState],
) -> None:
    record: _Record = []
    await _turn(chat, saver, record, "a", mode="continue")
    await _turn(chat, saver, record, "b", mode="continue")
    del record[2:]  # the caller undid turn "b"

    history = await _turn(chat, saver, record, "c", mode="replace")

    assert history.mode == "replace"
    assert history.discarded_messages == 4
    assert await _thread_texts(chat) == ["a", "echo:a", "c", "echo:c"]


@pytest.mark.asyncio
async def test_replace_counts_the_tool_traces_it_discards(
    saver: BaseCheckpointSaver[str],
    chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState],
) -> None:
    await chat.aupdate_state(
        _config(),
        {
            "messages": [
                HumanMessage(content="look it up"),
                AIMessage(content="", tool_calls=[{"name": "search", "args": {}, "id": "call-1"}]),
                ToolMessage(content="result", tool_call_id="call-1"),
                AIMessage(content="found it"),
            ]
        },
    )

    history = await resolve_turn_history(saver, _THREAD, "replace")

    assert history.discarded_messages == 4
    assert history.discarded_tool_messages == 1
    assert history.telemetry() == {
        "history_mode": "replace",
        "history_discarded_messages": 4,
        "history_discarded_tool_messages": 1,
    }
    assert await _thread_texts(chat) == []


@pytest.mark.asyncio
async def test_continue_over_an_empty_thread_resolves_to_a_replace_that_feeds_history(
    saver: BaseCheckpointSaver[str],
) -> None:
    history = await resolve_turn_history(saver, "never-used", "continue")

    assert history == TurnHistory(mode="replace")
    assert history.feeds_history
    assert history.telemetry() == {"history_mode": "replace"}


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, "", "append", "REPLACE", 3, ["continue"]])
async def test_an_undeclared_or_unknown_mode_leaves_the_thread_alone(
    saver: BaseCheckpointSaver[str],
    chat: CompiledStateGraph[_ChatState, None, _ChatState, _ChatState],
    declared: object,
) -> None:
    record: _Record = []
    await _turn(chat, saver, record, "a", mode="continue")

    history = await resolve_turn_history(saver, _THREAD, declared)

    assert history == TurnHistory(mode="append")
    assert history.feeds_history
    assert await _thread_texts(chat) == ["a", "echo:a"]


@pytest.mark.asyncio
async def test_a_replace_that_cannot_clear_the_thread_fails_the_turn() -> None:
    checkpointer = AsyncMock()
    checkpointer.aget = AsyncMock(return_value=None)
    checkpointer.adelete_thread = AsyncMock(side_effect=RuntimeError("database is locked"))

    with pytest.raises(RuntimeError, match="database is locked"):
        await resolve_turn_history(checkpointer, _THREAD, "replace")


@pytest.mark.asyncio
async def test_a_replace_without_a_checkpointer_has_nothing_to_clear() -> None:
    history = await resolve_turn_history(None, _THREAD, "replace")

    assert history == TurnHistory(mode="replace")


def test_the_context_key_is_the_documented_declaration_name() -> None:
    assert HISTORY_MODE_CONTEXT_KEY == "history_mode"


def test_a_resume_reports_itself_as_continuing_the_paused_thread() -> None:
    assert resumed_turn_facts() == {"history_mode": "resume"}
