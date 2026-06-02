"""Tests for session activity loading."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.runtime.context.session_activity import (
    load_session_activity,
    load_session_activity_async,
)


@pytest.mark.asyncio
async def test_async_returns_empty_when_no_checkpointer() -> None:
    result = await load_session_activity_async(datetime.now(UTC))
    assert result == set()


@pytest.mark.asyncio
async def test_async_returns_empty_when_no_thread_store() -> None:
    checkpointer = MagicMock(spec=[])
    result = await load_session_activity_async(datetime.now(UTC), checkpointer=checkpointer)
    assert result == set()


@pytest.mark.asyncio
async def test_async_returns_active_sessions() -> None:
    now = datetime.now(UTC)
    threshold = now - timedelta(days=30)

    record1 = MagicMock()
    record1.thread_id = "chat_abc"
    record1.last_active_at = now - timedelta(days=1)

    record2 = MagicMock()
    record2.thread_id = "chat_old"
    record2.last_active_at = now - timedelta(days=60)

    thread_store = AsyncMock()
    thread_store.find_active_threads = AsyncMock(return_value=[record1, record2])

    checkpointer = MagicMock()
    checkpointer.thread_store = thread_store

    result = await load_session_activity_async(threshold, checkpointer=checkpointer)

    assert result == {"chat_abc"}
    assert "chat_old" not in result


@pytest.mark.asyncio
async def test_async_handles_exception_gracefully() -> None:
    thread_store = AsyncMock()
    thread_store.find_active_threads = AsyncMock(side_effect=RuntimeError("DB error"))

    checkpointer = MagicMock()
    checkpointer.thread_store = thread_store

    result = await load_session_activity_async(datetime.now(UTC), checkpointer=checkpointer)
    assert result == set()


def test_sync_returns_empty_when_no_checkpointer() -> None:
    result = load_session_activity(datetime.now(UTC))
    assert result == set()


def test_sync_returns_empty_in_running_loop() -> None:
    """When called from within a running event loop, returns empty set."""
    import asyncio

    async def _inner() -> set[str]:
        return load_session_activity(datetime.now(UTC), checkpointer=MagicMock())

    result = asyncio.run(_inner())
    assert result == set()


def test_sync_handles_exception_gracefully() -> None:
    checkpointer = MagicMock(spec=[])
    del checkpointer.thread_store
    result = load_session_activity(datetime.now(UTC), checkpointer=checkpointer)
    assert result == set()


def test_sync_no_thread_store_attribute() -> None:
    """Sync version returns empty when checkpointer has no thread_store."""
    checkpointer = MagicMock(spec=[])
    result = load_session_activity(datetime.now(UTC), checkpointer=checkpointer)
    assert result == set()


@pytest.mark.asyncio
async def test_async_handles_thread_store_error() -> None:
    """Async version handles thread_store errors gracefully."""
    thread_store = AsyncMock()
    thread_store.find_active_threads = AsyncMock(side_effect=Exception("DB connection failed"))

    checkpointer = MagicMock()
    checkpointer.thread_store = thread_store

    result = await load_session_activity_async(datetime.now(UTC), checkpointer=checkpointer)
    assert result == set()


@pytest.mark.asyncio
async def test_async_returns_empty_for_old_sessions() -> None:
    """All sessions older than threshold are filtered out."""
    now = datetime.now(UTC)
    threshold = now - timedelta(days=1)

    record = MagicMock()
    record.thread_id = "chat_old"
    record.last_active_at = now - timedelta(days=10)

    thread_store = AsyncMock()
    thread_store.find_active_threads = AsyncMock(return_value=[record])

    checkpointer = MagicMock()
    checkpointer.thread_store = thread_store

    result = await load_session_activity_async(threshold, checkpointer=checkpointer)
    assert result == set()
