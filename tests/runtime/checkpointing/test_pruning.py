"""Pruning keeps the newest checkpoint of every thread and namespace with its writes, and returns space to the disk.

Everything runs against real SQLite files. The checkpointer the factory builds is the object the server hands to
LangGraph, so the end-to-end cases use it; the batching and VACUUM cases build the pruning saver directly to control
its limits.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from collections.abc import AsyncIterator, Callable
from contextlib import closing
from pathlib import Path
from typing import Annotated, TypedDict

import aiosqlite
import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph

from myrm_agent_harness.runtime.checkpointing import pruning
from myrm_agent_harness.runtime.checkpointing.factory import create_checkpointer
from myrm_agent_harness.runtime.checkpointing.load_fallback import LoadFallbackCheckpointer
from myrm_agent_harness.runtime.checkpointing.pruning import PruningAsyncSqliteSaver, prune_checkpoint_history


def _config(thread_id: str, namespace: str = "", checkpoint_id: str | None = None) -> RunnableConfig:
    configurable = {"thread_id": thread_id, "checkpoint_ns": namespace}
    if checkpoint_id:
        configurable["checkpoint_id"] = checkpoint_id
    return {"configurable": configurable}


async def _store(
    saver: BaseCheckpointSaver[str],
    thread_id: str,
    *,
    namespace: str = "",
    payload: str = "state",
    writes: tuple[tuple[str, str], ...] = (),
) -> str:
    """Store one more checkpoint (with pending writes) on the thread and return its id."""
    checkpoint = empty_checkpoint()
    checkpoint["channel_values"] = {"messages": payload}
    stored = await saver.aput(
        _config(thread_id, namespace), checkpoint, {"source": "loop", "step": 0, "parents": {}}, {}
    )
    if writes:
        await saver.aput_writes(stored, list(writes), task_id=f"task-{checkpoint['id']}")
    return checkpoint["id"]


def _rows(database: Path, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
    with closing(sqlite3.connect(database)) as conn:
        return conn.execute(sql, params).fetchall()


def _checkpoint_ids(database: Path, thread_id: str, namespace: str = "") -> list[str]:
    rows = _rows(
        database,
        "SELECT checkpoint_id FROM checkpoints WHERE thread_id = ? AND checkpoint_ns = ? ORDER BY checkpoint_id",
        (thread_id, namespace),
    )
    return [str(row[0]) for row in rows]


def _write_ids(database: Path, thread_id: str) -> set[str]:
    rows = _rows(database, "SELECT DISTINCT checkpoint_id FROM writes WHERE thread_id = ?", (thread_id,))
    return {str(row[0]) for row in rows}


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "checkpoints.db"


@pytest.fixture
async def saver(database: Path) -> AsyncIterator[BaseCheckpointSaver[str]]:
    checkpointer, cleanup = await create_checkpointer(mode="sqlite", sqlite_db_path=str(database))
    try:
        yield checkpointer
    finally:
        await cleanup()


@pytest.fixture
async def pruner(database: Path) -> AsyncIterator[PruningAsyncSqliteSaver]:
    """The pruning saver on a bare connection, with one stored row per deletion batch."""
    async with aiosqlite.connect(database) as conn:
        pruner = PruningAsyncSqliteSaver(conn, batch_bytes=1)
        await pruner.setup()
        yield pruner


@pytest.mark.asyncio
async def test_pruning_keeps_only_the_newest_checkpoint_of_each_thread(
    saver: BaseCheckpointSaver[str], database: Path
) -> None:
    ids = {"t1": [await _store(saver, "t1") for _ in range(5)], "t2": [await _store(saver, "t2") for _ in range(3)]}

    await saver.aprune(["t1", "t2"])

    assert _checkpoint_ids(database, "t1") == [ids["t1"][-1]]
    assert _checkpoint_ids(database, "t2") == [ids["t2"][-1]]
    for thread_id in ("t1", "t2"):
        stored = await saver.aget_tuple(_config(thread_id))
        assert stored is not None
        assert stored.checkpoint["id"] == ids[thread_id][-1]


@pytest.mark.asyncio
async def test_the_newest_checkpoint_keeps_its_pending_writes_and_older_writes_go(
    saver: BaseCheckpointSaver[str], database: Path
) -> None:
    await _store(saver, "t1", writes=(("messages", "old"),))
    newest = await _store(saver, "t1", writes=(("messages", "new-a"), ("other", "new-b")))

    await saver.aprune(["t1"])

    stored = await saver.aget_tuple(_config("t1"))
    assert stored is not None
    assert sorted(channel for _, channel, _ in stored.pending_writes) == ["messages", "other"]
    assert _write_ids(database, "t1") == {newest}


@pytest.mark.asyncio
async def test_each_namespace_keeps_its_own_newest_checkpoint(saver: BaseCheckpointSaver[str], database: Path) -> None:
    root = [await _store(saver, "t1") for _ in range(3)]
    sub = [await _store(saver, "t1", namespace="sub:1") for _ in range(4)]

    await saver.aprune(["t1"])

    assert _checkpoint_ids(database, "t1", "") == [root[-1]]
    assert _checkpoint_ids(database, "t1", "sub:1") == [sub[-1]]


@pytest.mark.asyncio
async def test_only_the_requested_threads_are_pruned(saver: BaseCheckpointSaver[str], database: Path) -> None:
    for _ in range(3):
        await _store(saver, "t1")
        await _store(saver, "t2")

    await saver.aprune(["t1"])

    assert len(_checkpoint_ids(database, "t1")) == 1
    assert len(_checkpoint_ids(database, "t2")) == 3


@pytest.mark.asyncio
async def test_writes_of_a_checkpoint_that_has_not_landed_yet_survive(
    saver: BaseCheckpointSaver[str], database: Path
) -> None:
    """A run records writes for its new checkpoint concurrently with storing it; the newer id keeps them safe."""
    for _ in range(3):
        await _store(saver, "t1")
    upcoming = empty_checkpoint()["id"]
    await saver.aput_writes(_config("t1", checkpoint_id=upcoming), [("messages", "in flight")], task_id="task-x")

    await saver.aprune(["t1"])

    assert upcoming in _write_ids(database, "t1")


@pytest.mark.asyncio
async def test_a_namespace_with_a_single_checkpoint_is_left_untouched(
    saver: BaseCheckpointSaver[str], database: Path
) -> None:
    only = await _store(saver, "t1", writes=(("messages", "kept"),))

    await saver.aprune(["t1"])

    assert _checkpoint_ids(database, "t1") == [only]
    assert _write_ids(database, "t1") == {only}


@pytest.mark.asyncio
async def test_pruning_twice_changes_nothing_the_second_time(saver: BaseCheckpointSaver[str], database: Path) -> None:
    for _ in range(4):
        await _store(saver, "t1", writes=(("messages", "w"),))
    await saver.aprune(["t1"])
    before = (_checkpoint_ids(database, "t1"), _write_ids(database, "t1"))

    await saver.aprune(["t1"])

    assert (_checkpoint_ids(database, "t1"), _write_ids(database, "t1")) == before


@pytest.mark.asyncio
async def test_pruning_unknown_threads_or_none_at_all_is_harmless(
    saver: BaseCheckpointSaver[str], database: Path
) -> None:
    only = await _store(saver, "t1")

    await saver.aprune(["never-seen"])
    await saver.aprune([])

    assert _checkpoint_ids(database, "t1") == [only]


@pytest.mark.asyncio
async def test_the_delete_strategy_removes_whole_threads(saver: BaseCheckpointSaver[str]) -> None:
    for _ in range(3):
        await _store(saver, "t1", writes=(("messages", "w"),))
    await _store(saver, "t2")

    await saver.aprune(["t1"], strategy="delete")

    assert await saver.aget_tuple(_config("t1")) is None
    assert await saver.aget_tuple(_config("t2")) is not None


@pytest.mark.asyncio
async def test_an_unknown_strategy_is_rejected_before_anything_is_touched(
    saver: BaseCheckpointSaver[str], database: Path
) -> None:
    for _ in range(3):
        await _store(saver, "t1")

    with pytest.raises(ValueError, match="Unsupported prune strategy"):
        await saver.aprune(["t1"], strategy="keep_everything")

    assert len(_checkpoint_ids(database, "t1")) == 3


class _ChatState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


async def _echo(state: _ChatState) -> _ChatState:
    return {"messages": [AIMessage(content=f"echo:{state['messages'][-1].content}")]}


def _chat_graph(saver: BaseCheckpointSaver[str]) -> CompiledStateGraph[_ChatState, None, _ChatState, _ChatState]:
    graph = StateGraph(_ChatState)
    graph.add_node("echo", _echo)
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)
    return graph.compile(checkpointer=saver)


@pytest.mark.asyncio
async def test_a_conversation_continues_unchanged_after_its_history_is_pruned(saver: BaseCheckpointSaver[str]) -> None:
    chat = _chat_graph(saver)
    config = _config("t1")
    for text in ("a", "b", "c"):
        await chat.ainvoke({"messages": [HumanMessage(content=text)]}, config)
    assert len([step async for step in chat.aget_state_history(config)]) > 1

    await saver.aprune(["t1"])

    assert len([step async for step in chat.aget_state_history(config)]) == 1
    await chat.ainvoke({"messages": [HumanMessage(content="d")]}, config)
    state = await chat.aget_state(config)
    assert [message.content for message in state.values["messages"]] == [
        "a",
        "echo:a",
        "b",
        "echo:b",
        "c",
        "echo:c",
        "d",
        "echo:d",
    ]


@pytest.mark.asyncio
async def test_threads_with_superseded_history_are_the_prunable_ones(saver: BaseCheckpointSaver[str]) -> None:
    for _ in range(3):
        await _store(saver, "history")
    await _store(saver, "single")
    await _store(saver, "nested")
    for _ in range(2):
        await _store(saver, "nested", namespace="sub:1")

    assert isinstance(saver, LoadFallbackCheckpointer)
    assert sorted(await saver.alist_prunable_thread_ids()) == ["history", "nested"]


@pytest.mark.asyncio
async def test_pruning_every_thread_with_history_skips_checkpointers_that_cannot_prune(
    saver: BaseCheckpointSaver[str], database: Path
) -> None:
    for _ in range(3):
        await _store(saver, "t1")
    await _store(saver, "t2")

    assert await prune_checkpoint_history(saver) is True
    assert len(_checkpoint_ids(database, "t1")) == 1
    assert await prune_checkpoint_history(saver) is True  # nothing left to prune is still a supported no-op

    assert await prune_checkpoint_history(MemorySaver()) is False
    assert await prune_checkpoint_history(LoadFallbackCheckpointer(MemorySaver())) is False


@pytest.mark.asyncio
async def test_a_wrapped_saver_that_cannot_prune_says_so() -> None:
    wrapper = LoadFallbackCheckpointer(MemorySaver())

    with pytest.raises(NotImplementedError):
        await wrapper.alist_prunable_thread_ids()


@pytest.mark.asyncio
async def test_a_long_history_is_deleted_in_batches_other_callers_can_interleave_with(
    pruner: PruningAsyncSqliteSaver, database: Path
) -> None:
    for _ in range(40):
        await _store(pruner, "long")

    running = asyncio.create_task(pruner.aprune(["long"]))
    await asyncio.sleep(0)
    other = await _store(pruner, "other")

    assert not running.done(), "the saver lock was held for the whole prune instead of one batch at a time"
    await running
    assert len(_checkpoint_ids(database, "long")) == 1
    assert _checkpoint_ids(database, "other") == [other]


@pytest.mark.asyncio
async def test_a_writer_racing_the_prune_never_loses_its_newest_checkpoint(
    pruner: PruningAsyncSqliteSaver, database: Path
) -> None:
    for _ in range(30):
        await _store(pruner, "busy")
    written: list[str] = []

    async def writer() -> None:
        for _ in range(15):
            written.append(await _store(pruner, "busy"))
            await asyncio.sleep(0)

    await asyncio.gather(pruner.aprune(["busy"]), writer())
    await pruner.aprune(["busy"])

    assert _checkpoint_ids(database, "busy") == [written[-1]]


@pytest.mark.asyncio
async def test_a_cancelled_prune_leaves_the_saver_usable(pruner: PruningAsyncSqliteSaver, database: Path) -> None:
    for _ in range(40):
        await _store(pruner, "long")
    newest = await pruner.aget_tuple(_config("long"))
    assert newest is not None

    running = asyncio.create_task(pruner.aprune(["long"]))
    await asyncio.sleep(0.05)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running

    assert pruner.conn.in_transaction is False
    survivor = await pruner.aget_tuple(_config("long"))
    assert survivor is not None
    assert survivor.checkpoint["id"] == newest.checkpoint["id"]
    await pruner.aprune(["long"])
    assert _checkpoint_ids(database, "long") == [newest.checkpoint["id"]]


def test_a_batch_takes_the_oldest_rows_that_fit_the_budget_and_always_at_least_one() -> None:
    rows = [("", "a", 40), ("", "b", 40), ("", "c", 40)]

    assert pruning._take_within_budget(rows, 100) == rows[:2]
    assert pruning._take_within_budget(rows, 10) == rows[:1]
    assert pruning._take_within_budget([], 10) == []


@pytest.fixture
def vacuum_when_a_little_is_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pruning, "_VACUUM_MIN_FREE_BYTES", 64 * 1024)


@pytest.mark.asyncio
async def test_the_freed_space_is_returned_to_the_filesystem(
    pruner: PruningAsyncSqliteSaver, database: Path, vacuum_when_a_little_is_free: None
) -> None:
    for _ in range(30):
        await _store(pruner, "t1", payload="x" * 100_000)
    async with pruner.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)"):
        pass
    size_before = os.path.getsize(database)

    await pruner.aprune(["t1"])

    assert os.path.getsize(database) < size_before / 4
    assert _rows(database, "PRAGMA freelist_count") == [(0,)]
    assert _rows(database, "PRAGMA integrity_check") == [("ok",)]
    assert len(_checkpoint_ids(database, "t1")) == 1


@pytest.mark.asyncio
async def test_a_small_amount_of_freed_space_is_not_worth_a_rewrite(
    pruner: PruningAsyncSqliteSaver, database: Path
) -> None:
    for _ in range(5):
        await _store(pruner, "t1", payload="x" * 10_000)

    await pruner.aprune(["t1"])

    assert _rows(database, "PRAGMA freelist_count")[0][0] > 0


@pytest.mark.asyncio
async def test_live_data_too_large_to_rewrite_quickly_is_not_vacuumed(
    pruner: PruningAsyncSqliteSaver, database: Path, vacuum_when_a_little_is_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pruning, "_VACUUM_MAX_LIVE_BYTES", 1024)
    for _ in range(10):
        await _store(pruner, "t1", payload="x" * 50_000)

    await pruner.aprune(["t1"])

    assert _rows(database, "PRAGMA freelist_count")[0][0] > 0


@pytest.mark.asyncio
async def test_a_failing_vacuum_is_reported_and_the_saver_keeps_working(
    pruner: PruningAsyncSqliteSaver,
    vacuum_when_a_little_is_free: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    for _ in range(30):
        await _store(pruner, "t1", payload="x" * 100_000)
    real_execute: Callable[..., object] = pruner.conn.execute

    def failing_vacuum(sql: str, *args: object, **kwargs: object) -> object:
        if sql == "VACUUM":
            raise sqlite3.OperationalError("database is locked")
        return real_execute(sql, *args, **kwargs)

    monkeypatch.setattr(pruner.conn, "execute", failing_vacuum)

    with caplog.at_level(logging.WARNING):
        await pruner.aprune(["t1"])

    assert any("VACUUM failed" in record.getMessage() for record in caplog.records)
    newest = await _store(pruner, "t1")
    stored = await pruner.aget_tuple(_config("t1"))
    assert stored is not None
    assert stored.checkpoint["id"] == newest
