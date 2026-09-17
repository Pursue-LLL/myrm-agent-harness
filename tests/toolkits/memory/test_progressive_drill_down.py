"""Tests for OpenViking-style progressive L0/L1/L2 retrieval and drill-down."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory.agent_surface.memory_agent_tools import (
    create_memory_tools,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)


@pytest.mark.asyncio
async def test_memory_search_progressive_l1_overview(
    mock_vector_store, mock_embedding, memory_config
) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    mem = SemanticMemory(
        id="mem-prog-1",
        content="This is the full verbose content of the memory spanning many sentences and implementation details.",
        summary_l0="Verbose memory details",
        overview_l1="Short factual overview of the implementation details.",
    )
    search_mock = AsyncMock(
        return_value=[
            MemorySearchResult(
                memory=mem,
                score=0.95,
                memory_type=MemoryType.SEMANTIC,
            )
        ]
    )

    with patch.object(MemoryManager, "search", search_mock):
        tool = next(
            t for t in create_memory_tools(manager) if t.name == "memory_search_tool"
        )
        result = await tool.ainvoke({"query": "implementation"})

    assert "[L1] Short factual overview" in result
    assert "Drill-down: memory_search_tool(memory_id='mem-prog-1'" in result
    assert "verbose content" not in result


@pytest.mark.asyncio
async def test_memory_search_drill_down_by_id(
    mock_vector_store, mock_embedding, memory_config
) -> None:
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    mem = SemanticMemory(
        id="mem-prog-2",
        content="Deep verbatim code snippet or architectural specification.",
        summary_l0="Deep spec",
        overview_l1="Architecture spec overview.",
    )

    with patch.object(MemoryManager, "get_memory", AsyncMock(return_value=mem)):
        tool = next(
            t for t in create_memory_tools(manager) if t.name == "memory_search_tool"
        )
        result = await tool.ainvoke({"memory_id": "mem-prog-2", "detail_level": "full"})

    assert "[L2 Verbatim Full Content]" in result
    assert "Deep verbatim code snippet or architectural specification." in result
