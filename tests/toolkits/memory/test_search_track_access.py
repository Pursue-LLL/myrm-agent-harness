"""Integration tests for search() track_access parameter."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory._manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, MemoryType, SemanticMemory


def _make_manager(*, search_results: list[MemorySearchResult] | None = None) -> MemoryManager:
    config = MemoryConfig(embedding_model="test")
    vector = AsyncMock()
    relational = AsyncMock()
    embedding = AsyncMock()
    manager = MemoryManager(
        config, user_id="u1", vector=vector, relational=relational, embedding=embedding
    )
    mock_search_svc = AsyncMock()
    mock_search_svc.search.return_value = search_results or []
    manager._search_service = mock_search_svc
    return manager


@pytest.mark.asyncio
async def test_search_track_access_true_triggers_bump():
    mem = SemanticMemory(id="s1", content="hello", metadata={})
    result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
    manager = _make_manager(search_results=[result])

    with patch(
        "myrm_agent_harness.toolkits.memory._internal.maintenance.bump_access_counts",
        new_callable=AsyncMock,
    ) as mock_bump:
        results = await manager.search("hello", track_access=True)
        await asyncio.sleep(0.05)

    assert len(results) == 1
    mock_bump.assert_awaited_once()
    call_args = mock_bump.call_args
    assert call_args[0][0] == [result]


@pytest.mark.asyncio
async def test_search_track_access_false_skips_bump():
    mem = SemanticMemory(id="s1", content="hello", metadata={})
    result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
    manager = _make_manager(search_results=[result])

    with patch(
        "myrm_agent_harness.toolkits.memory._internal.maintenance.bump_access_counts",
        new_callable=AsyncMock,
    ) as mock_bump:
        results = await manager.search("hello", track_access=False)
        await asyncio.sleep(0.05)

    assert len(results) == 1
    mock_bump.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_empty_results_skips_bump():
    manager = _make_manager(search_results=[])

    with patch(
        "myrm_agent_harness.toolkits.memory._internal.maintenance.bump_access_counts",
        new_callable=AsyncMock,
    ) as mock_bump:
        results = await manager.search("nothing")
        await asyncio.sleep(0.05)

    assert results == []
    mock_bump.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_default_track_access_is_true():
    """Default behavior should track access."""
    mem = SemanticMemory(id="s1", content="hello", metadata={})
    result = MemorySearchResult(memory=mem, score=0.9, memory_type=MemoryType.SEMANTIC)
    manager = _make_manager(search_results=[result])

    with patch(
        "myrm_agent_harness.toolkits.memory._internal.maintenance.bump_access_counts",
        new_callable=AsyncMock,
    ) as mock_bump:
        await manager.search("hello")
        await asyncio.sleep(0.05)

    mock_bump.assert_awaited_once()
