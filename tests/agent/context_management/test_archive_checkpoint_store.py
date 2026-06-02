"""Tests for EpisodicMemoryArchiveCheckpointStore."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.agent.context_management.archive_checkpoint.store import (
    EpisodicMemoryArchiveCheckpointStore,
    list_recent_checkpoints,
    tool_name_from_entities,
)
from myrm_agent_harness.agent.context_management.archive_checkpoint.types import (
    ARCHIVE_CHECKPOINT_EVENT_TYPE,
    ArchiveCheckpointRecord,
)
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, MemoryType
from myrm_agent_harness.toolkits.vector.base import VectorDocument


def _checkpoint_doc(
    *,
    doc_id: str,
    chat_id: str,
    archive_path: str,
    tool_name: str = "grep_tool",
    summary: str = "summary body",
    created_at: datetime | None = None,
) -> VectorDocument:
    created = created_at or datetime(2026, 5, 22, tzinfo=UTC)
    return VectorDocument(
        id=doc_id,
        content=f"Archive checkpoint (tool={tool_name}, path={archive_path}):\n{summary}",
        metadata={
            "memory_type": MemoryType.EPISODIC.value,
            "event_type": ARCHIVE_CHECKPOINT_EVENT_TYPE,
            "source_chat_id": chat_id,
            "importance": 0.85,
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
            "related_entities": [tool_name, archive_path],
        },
        created_at=created,
        updated_at=created,
    )


@pytest.mark.asyncio
async def test_find_by_archive_path_uses_scroll_not_search() -> None:
    manager = MagicMock()
    manager.has_vector = True
    manager._vector = AsyncMock()
    manager._config = MagicMock(episodic_collection="episodic")
    created_at = datetime(2026, 5, 22, tzinfo=UTC)
    doc = VectorDocument(
        id="mem-1",
        content="Archive checkpoint (tool=grep_tool, path=.context/chat/compacted/a.txt):\nsummary",
        metadata={
            "memory_type": MemoryType.EPISODIC.value,
            "event_type": ARCHIVE_CHECKPOINT_EVENT_TYPE,
            "source_chat_id": "chat-1",
            "importance": 0.85,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "related_entities": ["grep_tool", ".context/chat/compacted/a.txt"],
        },
    )
    manager._vector.scroll.return_value = ([doc], None)
    manager.search = AsyncMock(side_effect=AssertionError("find_by_archive_path must not search"))

    store = EpisodicMemoryArchiveCheckpointStore(manager)
    found = await store.find_by_archive_path("chat-1", ".context/chat/compacted/a.txt")

    assert found is not None
    assert found.memory_id == "mem-1"
    assert found.archive_path == ".context/chat/compacted/a.txt"
    manager.search.assert_not_called()


@pytest.mark.asyncio
async def test_store_checkpoint_returns_existing_record_without_duplicate_write() -> None:
    manager = MagicMock()
    manager.has_vector = True
    manager._vector = AsyncMock()
    manager._config = MagicMock(episodic_collection="episodic")
    created_at = datetime(2026, 5, 22, tzinfo=UTC)
    doc = VectorDocument(
        id="mem-1",
        content="Archive checkpoint (tool=grep_tool, path=.context/chat/compacted/a.txt):\nsummary",
        metadata={
            "memory_type": MemoryType.EPISODIC.value,
            "event_type": ARCHIVE_CHECKPOINT_EVENT_TYPE,
            "source_chat_id": "chat-1",
            "importance": 0.85,
            "created_at": created_at.isoformat(),
            "updated_at": created_at.isoformat(),
            "related_entities": ["grep_tool", ".context/chat/compacted/a.txt"],
        },
    )
    manager._vector.scroll.return_value = ([doc], None)
    manager.store = AsyncMock()

    store = EpisodicMemoryArchiveCheckpointStore(manager)
    record = await store.store_checkpoint(
        tool_name="grep_tool",
        archive_path=".context/chat/compacted/a.txt",
        summary="summary",
        chat_id="chat-1",
    )

    assert isinstance(record, ArchiveCheckpointRecord)
    manager.store.assert_not_called()


@pytest.mark.asyncio
async def test_store_checkpoint_writes_new_memory() -> None:
    manager = MagicMock()
    manager.has_vector = True
    manager._vector = AsyncMock()
    manager._config = MagicMock(episodic_collection="episodic")
    manager._vector.scroll.return_value = ([], None)
    stored_memory = EpisodicMemory(
        id="mem-new",
        content="stored",
        source_chat_id="chat-1",
    )
    manager.store = AsyncMock(return_value=stored_memory)

    store = EpisodicMemoryArchiveCheckpointStore(manager)
    record = await store.store_checkpoint(
        tool_name="grep_tool",
        archive_path=".context/chat/compacted/new.txt",
        summary="Q3 revenue -12%",
        chat_id="chat-1",
        tool_call_id="tc-99",
    )

    assert record.memory_id == "mem-new"
    assert record.summary == "Q3 revenue -12%"
    assert record.tool_call_id == "tc-99"
    manager.store.assert_awaited_once()
    stored_arg = manager.store.await_args.args[0]
    assert stored_arg.event_type == ARCHIVE_CHECKPOINT_EVENT_TYPE
    assert "tool_call:tc-99" in stored_arg.related_entities


@pytest.mark.asyncio
async def test_find_by_archive_path_returns_none_when_not_found() -> None:
    manager = MagicMock()
    manager.has_vector = True
    manager._vector = AsyncMock()
    manager._config = MagicMock(episodic_collection="episodic")
    manager._vector.scroll.return_value = (
        [_checkpoint_doc(doc_id="mem-1", chat_id="chat-1", archive_path=".context/chat/compacted/other.txt")],
        None,
    )

    store = EpisodicMemoryArchiveCheckpointStore(manager)
    found = await store.find_by_archive_path("chat-1", ".context/chat/compacted/missing.txt")

    assert found is None


@pytest.mark.asyncio
async def test_find_by_archive_path_handles_scroll_failure() -> None:
    manager = MagicMock()
    manager.has_vector = True
    manager._vector = AsyncMock()
    manager._config = MagicMock(episodic_collection="episodic")
    manager._vector.scroll.side_effect = RuntimeError("scroll down")

    store = EpisodicMemoryArchiveCheckpointStore(manager)
    found = await store.find_by_archive_path("chat-1", ".context/chat/compacted/a.txt")

    assert found is None


@pytest.mark.asyncio
async def test_list_recent_checkpoints_filters_by_chat_and_sorts() -> None:
    manager = MagicMock()
    manager.has_vector = True
    manager._vector = AsyncMock()
    manager._config = MagicMock(episodic_collection="episodic")
    older = _checkpoint_doc(
        doc_id="mem-old",
        chat_id="chat-1",
        archive_path=".context/chat/compacted/old.txt",
        created_at=datetime(2026, 5, 20, tzinfo=UTC),
    )
    newer = _checkpoint_doc(
        doc_id="mem-new",
        chat_id="chat-1",
        archive_path=".context/chat/compacted/new.txt",
        created_at=datetime(2026, 5, 22, tzinfo=UTC),
    )
    other_chat = _checkpoint_doc(
        doc_id="mem-other",
        chat_id="chat-2",
        archive_path=".context/chat/compacted/other.txt",
    )
    manager._vector.scroll.return_value = ([older, other_chat, newer], None)

    records = await list_recent_checkpoints(manager, chat_id="chat-1", limit=2)

    assert len(records) == 2
    assert records[0].memory_id == "mem-new"
    assert records[1].memory_id == "mem-old"


@pytest.mark.asyncio
async def test_list_recent_checkpoints_returns_empty_without_vector() -> None:
    manager = MagicMock()
    manager.has_vector = False

    records = await list_recent_checkpoints(manager, chat_id="chat-1")

    assert records == []


def test_tool_name_from_entities_prefers_non_path_entity() -> None:
    assert tool_name_from_entities(["grep_tool", ".context/chat/compacted/a.txt"], default="tool") == "grep_tool"
    assert tool_name_from_entities(["tool_call:tc-1"], default="fallback") == "fallback"
