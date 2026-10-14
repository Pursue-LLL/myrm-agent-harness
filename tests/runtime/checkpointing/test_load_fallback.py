"""The checkpointer the factory builds forwards the whole async saver interface and survives undecodable data.

Everything runs against the real SQLite-backed checkpointer ``create_checkpointer`` returns, because
that is the object the server hands to the continuity service, the agent runtime and LangGraph.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import aiosqlite
import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver, empty_checkpoint

from myrm_agent_harness.runtime.checkpointing.factory import create_checkpointer
from myrm_agent_harness.runtime.checkpointing.load_fallback import _is_undecodable_payload
from myrm_agent_harness.runtime.context.session.session_continuity import sync_checkpoint_messages


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}}


async def _store(saver: BaseCheckpointSaver[str], thread_id: str) -> None:
    await saver.aput(_config(thread_id), empty_checkpoint(), {"source": "input", "step": 0, "parents": {}}, {})


@pytest.fixture
async def sqlite_path(tmp_path: Path) -> Path:
    return tmp_path / "checkpoints.db"


@pytest.fixture
async def saver(sqlite_path: Path) -> AsyncIterator[BaseCheckpointSaver[str]]:
    checkpointer, cleanup = await create_checkpointer(mode="sqlite", sqlite_db_path=str(sqlite_path))
    try:
        yield checkpointer
    finally:
        await cleanup()


@pytest.mark.asyncio
async def test_a_stored_checkpoint_round_trips(saver: BaseCheckpointSaver[str]) -> None:
    await _store(saver, "t1")

    stored = await saver.aget_tuple(_config("t1"))

    assert stored is not None
    assert stored.checkpoint["id"]
    assert [item.config["configurable"]["thread_id"] async for item in saver.alist(_config("t1"))] == ["t1"]


@pytest.mark.asyncio
async def test_pending_writes_are_stored_against_the_checkpoint(saver: BaseCheckpointSaver[str]) -> None:
    config = await saver.aput(_config("t1"), empty_checkpoint(), {"source": "input", "step": 0, "parents": {}}, {})

    await saver.aput_writes(config, [("messages", "hello")], task_id="task-1")

    stored = await saver.aget_tuple(config)
    assert stored is not None
    assert stored.pending_writes == [("task-1", "messages", "hello")]


@pytest.mark.asyncio
async def test_deleting_a_thread_removes_its_checkpoints(saver: BaseCheckpointSaver[str]) -> None:
    await _store(saver, "t1")
    await _store(saver, "t2")

    await saver.adelete_thread("t1")

    assert await saver.aget_tuple(_config("t1")) is None
    assert await saver.aget_tuple(_config("t2")) is not None


@pytest.mark.asyncio
async def test_clearing_a_chat_history_deletes_both_thread_aliases(saver: BaseCheckpointSaver[str]) -> None:
    """Edit-resend of the first message and rewind to the start leave no messages to write back."""
    await _store(saver, "chat-1")
    await _store(saver, "chat_chat-1")

    synced = await sync_checkpoint_messages(saver, "chat-1", [])

    assert synced == 2
    assert await saver.aget_tuple(_config("chat-1")) is None
    assert await saver.aget_tuple(_config("chat_chat-1")) is None


@pytest.mark.asyncio
async def test_a_checkpoint_that_cannot_be_decoded_starts_a_fresh_session(
    saver: BaseCheckpointSaver[str], sqlite_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    await _store(saver, "t1")
    async with aiosqlite.connect(sqlite_path) as conn:
        await conn.execute("UPDATE checkpoints SET checkpoint = ? WHERE thread_id = ?", (b"not a pickle", "t1"))
        await conn.commit()

    with caplog.at_level(logging.WARNING):
        stored = await saver.aget_tuple(_config("t1"))

    assert stored is None
    assert any("starting fresh session" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_a_failure_unrelated_to_decoding_is_not_swallowed(
    saver: BaseCheckpointSaver[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from myrm_agent_harness.runtime.checkpointing.load_fallback import LoadFallbackCheckpointer

    assert isinstance(saver, LoadFallbackCheckpointer)

    async def failing(_config: RunnableConfig) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr(saver._wrapped, "aget_tuple", failing)

    with pytest.raises(RuntimeError, match="database is locked"):
        await saver.aget_tuple(_config("t1"))


@pytest.mark.parametrize(
    "message",
    [
        "Can't get attribute 'Gone' on <module 'pickle'>",
        "No module named 'dill._objects'",
        "Foo.__init__() missing 2 required positional arguments: 'a' and 'b'",
    ],
)
def test_decode_failures_are_recognised_by_message(message: str) -> None:
    assert _is_undecodable_payload(TypeError(message))


def test_decode_failures_are_recognised_by_where_they_were_raised() -> None:
    import dill  # type: ignore[import-untyped]

    with pytest.raises(Exception) as caught:  # dill raises a version-dependent error type
        dill.loads(b"not a pickle")  # noqa: S301  # deliberately undecodable input

    assert _is_undecodable_payload(caught.value)


def test_storage_failures_are_not_mistaken_for_decode_failures() -> None:
    assert not _is_undecodable_payload(RuntimeError("database is locked"))
