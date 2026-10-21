"""Checkpoint read access — payload shape contract and end-to-end regression.

The langgraph ``Checkpoint`` payload is a TypedDict, so ``aget()`` hands back a
plain ``dict``. Reading it with attribute access silently yields ``None`` for
every thread, which is how the context-budget ``turn_count`` and the subagent
checkpoint-state extraction both degraded to empty results without any test
failing. These tests pin the mapping contract, and one drives a real LangGraph
run so a mock cannot re-encode the same wrong assumption.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from myrm_agent_harness.runtime.checkpointing import read_checkpoint_messages

_THREAD_ID = "read-access-thread"


class _State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]


def _echo_node(state: _State) -> _State:
    return {"messages": [AIMessage(content=f"echo:{state['messages'][-1].content}")]}


def _build_graph(saver: MemorySaver) -> CompiledStateGraph[Any, Any, Any, Any]:
    graph = StateGraph(_State)
    graph.add_node("respond", _echo_node)
    graph.add_edge(START, "respond")
    graph.add_edge("respond", END)
    return graph.compile(checkpointer=saver)


def _thread_config(thread_id: str = _THREAD_ID) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


class TestReadCheckpointMessagesGuards:
    """Unavailable inputs must degrade to an empty list, never raise."""

    @pytest.mark.asyncio
    async def test_none_checkpointer_returns_empty(self) -> None:
        assert await read_checkpoint_messages(None, _THREAD_ID) == []

    @pytest.mark.asyncio
    async def test_object_without_aget_returns_empty(self) -> None:
        assert await read_checkpoint_messages(object(), _THREAD_ID) == []

    @pytest.mark.asyncio
    async def test_checkpoint_none_returns_empty(self) -> None:
        checkpointer = AsyncMock()
        checkpointer.aget = AsyncMock(return_value=None)
        assert await read_checkpoint_messages(checkpointer, _THREAD_ID) == []

    @pytest.mark.asyncio
    async def test_aget_failure_returns_empty_without_raising(self) -> None:
        checkpointer = AsyncMock()
        checkpointer.aget = AsyncMock(side_effect=RuntimeError("checkpoint unavailable"))
        assert await read_checkpoint_messages(checkpointer, _THREAD_ID) == []

    @pytest.mark.asyncio
    async def test_non_mapping_channel_values_returns_empty(self) -> None:
        checkpointer = AsyncMock()
        checkpointer.aget = AsyncMock(return_value={"channel_values": "not-a-mapping"})
        assert await read_checkpoint_messages(checkpointer, _THREAD_ID) == []

    @pytest.mark.asyncio
    async def test_missing_messages_channel_returns_empty(self) -> None:
        checkpointer = AsyncMock()
        checkpointer.aget = AsyncMock(return_value={"channel_values": {}})
        assert await read_checkpoint_messages(checkpointer, _THREAD_ID) == []

    @pytest.mark.asyncio
    async def test_non_list_messages_returns_empty(self) -> None:
        checkpointer = AsyncMock()
        checkpointer.aget = AsyncMock(
            return_value={"channel_values": {"messages": "not-a-list"}}
        )
        assert await read_checkpoint_messages(checkpointer, _THREAD_ID) == []


class TestReadCheckpointMessagesContract:
    """The payload is a mapping; attribute access would return nothing."""

    @pytest.mark.asyncio
    async def test_dict_payload_is_read_via_mapping_lookup(self) -> None:
        message = HumanMessage(content="stored turn")
        checkpointer = AsyncMock()
        checkpointer.aget = AsyncMock(
            return_value={"channel_values": {"messages": [message]}}
        )

        messages = await read_checkpoint_messages(checkpointer, _THREAD_ID)

        assert messages == [message]

    @pytest.mark.asyncio
    async def test_end_to_end_real_langgraph_run(self) -> None:
        saver = MemorySaver()
        app = _build_graph(saver)
        config = _thread_config()

        await app.ainvoke({"messages": [HumanMessage(content="turn one")]}, config)
        await app.ainvoke({"messages": [HumanMessage(content="turn two")]}, config)

        messages = await read_checkpoint_messages(saver, _THREAD_ID)

        # langgraph persists both turns: 2 human + 2 assistant messages.
        assert len(messages) == 4
        assert all(isinstance(msg, BaseMessage) for msg in messages)
        assert sum(1 for msg in messages if isinstance(msg, BaseMessage) and msg.type == "human") == 2

    @pytest.mark.asyncio
    async def test_unknown_thread_returns_empty(self) -> None:
        saver = MemorySaver()
        await _build_graph(saver).ainvoke(
            {"messages": [HumanMessage(content="x")]},
            _thread_config(),
        )

        assert await read_checkpoint_messages(saver, "never-written-thread") == []
