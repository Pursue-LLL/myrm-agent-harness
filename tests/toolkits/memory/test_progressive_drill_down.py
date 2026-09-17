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
    ProceduralMemory,
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


@pytest.mark.asyncio
async def test_memory_search_domain_filtering(
    mock_vector_store, mock_embedding, memory_config
) -> None:
    from myrm_agent_harness.toolkits.memory.domain_types import MemoryDomain

    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    user_mem = SemanticMemory(
        id="mem-user-1",
        content="User prefers dark mode and fast responses.",
        summary_l0="User UI preference",
        overview_l1="Dark mode preference.",
        domain=MemoryDomain.USER,
    )
    task_mem = SemanticMemory(
        id="mem-task-1",
        content="Trap alert: Always check HTTP status before parsing JSON payload.",
        summary_l0="API error handling trap",
        overview_l1="HTTP status check trap.",
        domain=MemoryDomain.TASK,
    )
    search_mock = AsyncMock(
        return_value=[
            MemorySearchResult(
                memory=user_mem,
                score=0.92,
                memory_type=MemoryType.SEMANTIC,
            ),
            MemorySearchResult(
                memory=task_mem,
                score=0.88,
                memory_type=MemoryType.SEMANTIC,
            ),
        ]
    )

    with patch.object(MemoryManager, "search", search_mock):
        tool = next(
            t for t in create_memory_tools(manager) if t.name == "memory_search_tool"
        )
        # Search specifically for task domain
        task_result = await tool.ainvoke({"query": "check", "domain": "task"})
        # Search specifically for user domain
        user_result = await tool.ainvoke({"query": "preference", "domain": "user"})
        # Search for assistant domain (no match)
        empty_result = await tool.ainvoke({"query": "soul", "domain": "assistant"})

    assert "HTTP status check trap" in task_result
    assert "Dark mode preference" not in task_result

    assert "Dark mode preference" in user_result
    assert "HTTP status check trap" not in user_result

    assert "No relevant memories found." in empty_result


@pytest.mark.asyncio
async def test_memory_search_heuristic_domain_fallback(
    mock_vector_store, mock_embedding, memory_config
) -> None:
    """When a legacy memory lacks an explicit domain field, heuristic classification falls back seamlessly."""
    manager = MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        embedding=mock_embedding,
    )
    # Legacy memory without domain attribute set (domain defaults to None)
    legacy_task_mem = ProceduralMemory(
        id="mem-legacy-sop",
        trigger="When running frontend tests",
        action="Always use bun for test execution.",
        content="Guideline and runbook: Always use bun for frontend test execution.",
        summary_l0="Frontend testing SOP",
        overview_l1="Runbook for bun testing.",
    )
    object.__setattr__(legacy_task_mem, "domain", None)
    assert legacy_task_mem.domain is None

    search_mock = AsyncMock(
        return_value=[
            MemorySearchResult(
                memory=legacy_task_mem,
                score=0.95,
                memory_type=MemoryType.PROCEDURAL,
                content=legacy_task_mem.content,
            ),
        ]
    )

    with patch.object(MemoryManager, "search", search_mock):
        tool = next(
            t for t in create_memory_tools(manager) if t.name == "memory_search_tool"
        )
        # 1. Searching for task domain matches via heuristic inference
        matched_result = await tool.ainvoke({"query": "testing", "domain": "task"})
        assert "Runbook for bun testing" in matched_result

        # 2. Searching for user domain prunes it correctly
        pruned_result = await tool.ainvoke({"query": "testing", "domain": "user"})
        assert "No relevant memories found." in pruned_result


