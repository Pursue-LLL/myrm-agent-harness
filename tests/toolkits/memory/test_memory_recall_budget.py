"""Tests for memory_recall context-budget guardrails."""

from typing import Protocol, cast
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.memory_agent_tools import create_memory_tools
from myrm_agent_harness.toolkits.memory.memory_recall_budget import (
    MAX_RECALL_OUTPUT_CHARS,
    normalize_recall_limit,
)
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, MemoryType, SemanticMemory


class _AsyncTool(Protocol):
    name: str

    async def ainvoke(self, tool_input: dict[str, object]) -> str: ...


def _recall_tool(manager: MemoryManager) -> _AsyncTool:
    tool = next(
        candidate
        for candidate in create_memory_tools(manager)
        if getattr(candidate, "name", "") == "memory_search_tool"
    )
    return cast(_AsyncTool, tool)


def test_normalize_recall_limit_handles_model_provided_values() -> None:
    assert normalize_recall_limit("12") == 12
    assert normalize_recall_limit("100") == 15
    assert normalize_recall_limit("abc") == 5
    assert normalize_recall_limit(True) == 5
    assert normalize_recall_limit(None) == 5


@pytest.mark.asyncio
async def test_memory_recall_caps_oversized_limit(mock_vector_store, mock_embedding, memory_config) -> None:
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)
    search_mock = AsyncMock(return_value=[])

    with patch.object(MemoryManager, "search", search_mock):
        await _recall_tool(manager).ainvoke({"query": "shared context", "limit": 100})

    assert search_mock.call_args.kwargs["limit"] == 15


@pytest.mark.asyncio
async def test_memory_recall_raises_tiny_limit_to_one(mock_vector_store, mock_embedding, memory_config) -> None:
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)
    search_mock = AsyncMock(return_value=[])

    with patch.object(MemoryManager, "search", search_mock):
        await _recall_tool(manager).ainvoke({"query": "shared context", "limit": 0})

    assert search_mock.call_args.kwargs["limit"] == 1


@pytest.mark.asyncio
async def test_memory_recall_truncates_oversized_output(mock_vector_store, mock_embedding, memory_config) -> None:
    manager = MemoryManager(memory_config, user_id="test_user", vector=mock_vector_store, embedding=mock_embedding)
    long_content = "A" * (MAX_RECALL_OUTPUT_CHARS * 2)
    search_mock = AsyncMock(
        return_value=[
            MemorySearchResult(
                memory=SemanticMemory(id="mem-long", content=long_content),
                score=0.91,
                memory_type=MemoryType.SEMANTIC,
            )
        ]
    )

    with patch.object(MemoryManager, "search", search_mock):
        result = await _recall_tool(manager).ainvoke({"query": "shared context", "limit": "10"})

    assert "id: mem-long" in result
    assert "[truncated" in result
    assert "[recall_budget]" in result
    assert len(result) <= MAX_RECALL_OUTPUT_CHARS
    assert search_mock.call_args.kwargs["limit"] == 10
