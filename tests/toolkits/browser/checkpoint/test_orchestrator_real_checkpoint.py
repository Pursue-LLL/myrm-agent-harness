"""Startup recovery reads the checkpoints a real LangGraph saver writes.

[INPUT]
- langgraph.checkpoint.memory::InMemorySaver (POS: real checkpoint writer; `ts` is the ISO-8601 string production savers store)
- checkpoint.incremental_checkpointer::IncrementalSessionCheckpointer (POS: the production checkpointer wrapper)
- checkpoint.thread_registry::ThreadStore (POS: SQLite registry of threads to recover)
- checkpoint.orchestrator::AutoRecoveryOrchestrator (POS: startup recovery scan under test)

[OUTPUT]
- Tests: a checkpoint written by a real saver becomes a RecoveryContext

[POS]
Closes the gap the mocked orchestrator tests leave: they hand over hand-made checkpoint dicts,
so a checkpoint field read in the wrong shape never fails there.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import TypedDict

import aiosqlite
import pytest
from langgraph.checkpoint.base import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from myrm_agent_harness.toolkits.browser.checkpoint import (
    AutoRecoveryOrchestrator,
    IncrementalSessionCheckpointer,
    ThreadStore,
)

THREAD_ID = "thread-real-checkpoint"


class _State(TypedDict):
    messages: list[str]


@pytest.fixture
async def thread_store() -> AsyncIterator[ThreadStore]:
    async with aiosqlite.connect(":memory:") as conn:
        store = ThreadStore(conn)
        await store.setup()
        await store.register(THREAD_ID)
        yield store


async def _write_checkpoint(saver: InMemorySaver) -> RunnableConfig:
    graph = StateGraph(_State)
    graph.add_node("work", lambda state: {"messages": [*state["messages"], "done"]})
    graph.add_edge(START, "work")
    graph.add_edge("work", END)
    config: RunnableConfig = {"configurable": {"thread_id": THREAD_ID}}
    await graph.compile(checkpointer=saver).ainvoke({"messages": ["start"]}, config)
    return config


async def test_checkpoint_written_by_a_real_saver_becomes_a_recovery_context(thread_store: ThreadStore) -> None:
    saver = InMemorySaver()
    config = await _write_checkpoint(saver)
    written = await saver.aget_tuple(config)
    assert written is not None

    orchestrator = AutoRecoveryOrchestrator(
        IncrementalSessionCheckpointer(saver, thread_store=thread_store), thread_store
    )
    await orchestrator.initialize()
    contexts = await orchestrator.find_incomplete_tasks()

    assert len(contexts) == 1
    context = contexts[0]
    assert context.thread_id == THREAD_ID
    assert context.checkpoint_id == written.checkpoint["id"]
    assert context.messages == ["start", "done"]
    assert context.last_updated_at == datetime.fromisoformat(written.checkpoint["ts"]).timestamp()
