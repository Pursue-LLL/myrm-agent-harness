"""Tests for the checkpoint thread aliases of a chat session and their deletion."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from myrm_agent_harness.runtime.context.session.session_continuity import (
    CheckpointClearError,
    clear_checkpoint_threads,
    resolve_thread_ids,
)


async def _write_thread(checkpointer: MemorySaver, thread_id: str) -> None:
    graph = StateGraph(MessagesState)
    graph.add_node("pass", lambda state: state)
    graph.add_edge(START, "pass")
    chat = graph.compile(checkpointer=checkpointer)
    await chat.aupdate_state(
        {"configurable": {"thread_id": thread_id}},
        {"messages": [HumanMessage(content="hello"), AIMessage(content="world")]},
    )


async def _has_thread(checkpointer: MemorySaver, thread_id: str) -> bool:
    return await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}}) is not None


def test_resolve_thread_ids_returns_chat_aliases() -> None:
    assert resolve_thread_ids("abc") == ("abc", "chat_abc")


@pytest.mark.asyncio
async def test_clear_deletes_every_alias_and_leaves_other_chats_alone() -> None:
    checkpointer = MemorySaver()
    for thread_id in (*resolve_thread_ids("continuity-chat"), "other-chat"):
        await _write_thread(checkpointer, thread_id)

    deleted = await clear_checkpoint_threads(checkpointer, "continuity-chat")

    assert deleted == 2
    for thread_id in resolve_thread_ids("continuity-chat"):
        assert not await _has_thread(checkpointer, thread_id)
    assert await _has_thread(checkpointer, "other-chat")


@pytest.mark.asyncio
async def test_clear_of_a_chat_without_threads_succeeds() -> None:
    assert await clear_checkpoint_threads(MemorySaver(), "never-ran") == 2


@pytest.mark.asyncio
async def test_clear_attempts_every_alias_before_it_reports_a_partial_failure() -> None:
    checkpointer = AsyncMock()
    checkpointer.adelete_thread = AsyncMock(side_effect=[RuntimeError("database is locked"), None])

    with pytest.raises(CheckpointClearError, match="Deleted 1/2"):
        await clear_checkpoint_threads(checkpointer, "partial-chat")

    assert checkpointer.adelete_thread.await_count == 2
