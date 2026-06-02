from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.strategies.subsumption import (
    apply_subsumption,
    find_subsumed_memories,
    judge_subsumption,
    undo_subsumption,
)
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, MemoryStatus, MemoryType, SemanticMemory


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def mock_manager():
    manager = AsyncMock(spec=MemoryManager)
    manager._user_id = "test_user"
    manager._vector = AsyncMock()
    manager._relational = AsyncMock()
    manager._config = MagicMock()
    manager._embedding = AsyncMock()
    manager._cache = AsyncMock()
    return manager


@pytest.mark.asyncio
async def test_judge_subsumption_true(mock_llm):
    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=MagicMock(subsumed=True, reason="Covered completely"))
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

    is_subsumed, reason = await judge_subsumption("mem1", "old rule", "new skill", mock_llm)

    assert is_subsumed is True
    assert reason == "Covered completely"
    mock_structured_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_judge_subsumption_false(mock_llm):
    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=MagicMock(subsumed=False, reason="Missing context"))
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

    is_subsumed, reason = await judge_subsumption("mem1", "old rule", "new skill", mock_llm)

    assert is_subsumed is False
    assert reason == "Missing context"


@pytest.mark.asyncio
async def test_judge_subsumption_markdown_trim(mock_llm):
    # Not relevant anymore with structured output, but we can test it passes
    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=MagicMock(subsumed=True, reason="Markdown handled"))
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

    is_subsumed, reason = await judge_subsumption("mem1", "old rule", "new skill", mock_llm)

    assert is_subsumed is True
    assert reason == "Markdown handled"


@pytest.mark.asyncio
async def test_judge_subsumption_exception(mock_llm):
    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(side_effect=Exception("LLM Error"))
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

    is_subsumed, reason = await judge_subsumption("mem1", "old rule", "new skill", mock_llm)

    assert is_subsumed is False
    assert "LLM Error" in reason


@pytest.mark.asyncio
async def test_find_subsumed_memories(mock_manager, mock_llm):
    # Mock search to return two candidate memories
    mock_manager.search.return_value = [
        MemorySearchResult(memory=SemanticMemory(content="A"), score=0.9, memory_type=MemoryType.SEMANTIC),
        MemorySearchResult(memory=SemanticMemory(content="B"), score=0.8, memory_type=MemoryType.SEMANTIC),
    ]

    # Mock get_memory to return actual memories
    mem1 = SemanticMemory(content="A", metadata={"status": "active"})
    mem1.id = "id1"
    mem2 = SemanticMemory(content="B", metadata={"status": "subsumed"})
    mem2.id = "id2"

    mock_manager.get_memory.side_effect = [mem1, mem2]

    # Mock LLM to return True for the first memory
    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=MagicMock(subsumed=True, reason="Yes"))
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

    subsumed_ids = await find_subsumed_memories(mock_manager, "new skill", mock_llm)

    assert len(subsumed_ids) == 1
    assert subsumed_ids[0] == "id1"
    mock_structured_llm.ainvoke.assert_called_once()  # Mem2 is skipped because it's already subsumed


@pytest.mark.asyncio
async def test_apply_subsumption(mock_manager):
    mem1 = SemanticMemory(content="A", metadata={"status": "active"})
    mem1.id = "id1"
    mock_manager.get_memory.return_value = mem1

    count = await apply_subsumption(mock_manager, ["id1"])

    assert count == 1
    assert mem1.metadata["status"] == "subsumed"
    mock_manager.update_memory.assert_called_once_with("id1", metadata=mem1.metadata, status=MemoryStatus.DISABLED)


@pytest.mark.asyncio
async def test_undo_subsumption(mock_manager):
    mem1 = SemanticMemory(content="A", metadata={"status": "subsumed"})
    mem1.id = "id1"
    mock_manager.get_memory.return_value = mem1

    count = await undo_subsumption(mock_manager, ["id1"])

    assert count == 1
    assert "status" not in mem1.metadata
    mock_manager.update_memory.assert_called_once_with("id1", metadata=mem1.metadata, status=MemoryStatus.ACTIVE)
