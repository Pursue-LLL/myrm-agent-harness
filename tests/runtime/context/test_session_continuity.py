"""Tests for session_continuity checkpoint sync."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver

from myrm_agent_harness.runtime.context.session.session_continuity import (
    ContinuitySyncError,
    resolve_thread_ids,
    sync_checkpoint_messages,
)


@pytest.mark.asyncio
async def test_resolve_thread_ids_returns_chat_aliases() -> None:
    assert resolve_thread_ids("abc") == ("abc", "chat_abc")


@pytest.mark.asyncio
async def test_sync_checkpoint_messages_writes_and_truncates() -> None:
    checkpointer = MemorySaver()
    chat_id = "continuity-chat"

    written = await sync_checkpoint_messages(
        checkpointer,
        chat_id,
        [HumanMessage(content="hello"), AIMessage(content="world")],
    )
    assert written == 2

    config = {"configurable": {"thread_id": chat_id}}
    saved = await checkpointer.aget_tuple(config)
    assert saved is not None
    assert saved.checkpoint is not None
    messages = saved.checkpoint["channel_values"]["messages"]
    assert len(messages) == 2

    written = await sync_checkpoint_messages(
        checkpointer,
        chat_id,
        [HumanMessage(content="hello")],
    )
    assert written == 2
    saved = await checkpointer.aget_tuple(config)
    assert saved is not None
    assert saved.checkpoint is not None
    assert len(saved.checkpoint["channel_values"]["messages"]) == 1


@pytest.mark.asyncio
async def test_sync_checkpoint_messages_deletes_when_empty() -> None:
    checkpointer = MemorySaver()
    chat_id = "continuity-empty"
    await sync_checkpoint_messages(checkpointer, chat_id, [HumanMessage(content="x")])

    deleted = await sync_checkpoint_messages(checkpointer, chat_id, [])
    assert deleted == 2

    for thread_id in resolve_thread_ids(chat_id):
        saved = await checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})
        assert saved is None


@pytest.mark.asyncio
async def test_sync_checkpoint_messages_raises_on_partial_failure() -> None:
    from unittest.mock import AsyncMock

    checkpointer = AsyncMock()
    checkpointer.aget_tuple = AsyncMock(return_value=None)
    checkpointer.aput = AsyncMock(side_effect=RuntimeError("write failed"))

    with pytest.raises(ContinuitySyncError, match="Synced 0/2"):
        await sync_checkpoint_messages(
            checkpointer,
            "partial-chat",
            [HumanMessage(content="hello")],
        )
