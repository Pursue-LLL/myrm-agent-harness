from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.strategies.subsumption import (
    apply_subsumption,
    find_subsumed_memories,
    judge_subsumption,
    undo_subsumption,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryStatus,
    MemoryType,
    SemanticMemory,
)


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
    mem1 = SemanticMemory(content="A", metadata={})
    mem1.id = "id1"
    mem2 = SemanticMemory(content="B", metadata={"subsumed": True})
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
    mem1 = SemanticMemory(content="A", metadata={})
    mem1.id = "id1"
    mock_manager.get_memory.return_value = mem1

    count = await apply_subsumption(mock_manager, ["id1"])

    assert count == 1
    assert mem1.metadata["subsumed"] is True
    mock_manager.update_memory.assert_called_once_with(
        "id1",
        metadata=mem1.metadata,
        status=MemoryStatus.DISABLED,
        allow_protected=False,
    )


@pytest.mark.asyncio
async def test_apply_subsumption_skips_unsupported_types_without_deleting(mock_manager):
    episodic = MagicMock(spec=EpisodicMemory)
    episodic.id = "ep1"
    episodic.metadata = {}
    mock_manager.get_memory.return_value = episodic

    count = await apply_subsumption(mock_manager, ["ep1"])

    assert count == 0
    assert "subsumed" not in episodic.metadata
    mock_manager.update_memory.assert_not_called()
    mock_manager.delete_memory.assert_not_called()


@pytest.mark.asyncio
async def test_apply_subsumption_skips_missing_memory(mock_manager):
    mock_manager.get_memory.return_value = None

    assert await apply_subsumption(mock_manager, ["gone"]) == 0
    mock_manager.update_memory.assert_not_called()


@pytest.mark.asyncio
async def test_undo_subsumption(mock_manager):
    mem1 = SemanticMemory(content="A", metadata={"subsumed": True})
    mem1.id = "id1"
    mock_manager.get_memory.return_value = mem1

    count = await undo_subsumption(mock_manager, ["id1"])

    assert count == 1
    assert "subsumed" not in mem1.metadata
    mock_manager.update_memory.assert_called_once_with("id1", metadata=mem1.metadata, status=MemoryStatus.ACTIVE)


@pytest.mark.asyncio
async def test_subsumed_marker_survives_the_payload_roundtrip(tmp_path):
    """The rollback marker must persist; a metadata "status" would be dropped by the payload's own status field."""
    from uuid import uuid4

    from myrm_agent_harness.toolkits.memory.setup import create_local_memory_manager

    manager = await create_local_memory_manager(tmp_path / "mem", None)
    try:
        memory = await manager.store(
            SemanticMemory(id=str(uuid4()), user_id="sandbox_user", content="将被吸收：TypeScript strict")
        )

        assert await apply_subsumption(manager, [memory.id]) == 1
        reloaded = await manager.get_memory(memory.id)
        assert reloaded is not None
        assert reloaded.metadata.get("subsumed") is True
        assert reloaded.status == MemoryStatus.DISABLED
        assert await manager.search("TypeScript", limit=5) == []

        assert await undo_subsumption(manager, [memory.id]) == 1
        restored = await manager.get_memory(memory.id)
        assert restored is not None
        assert restored.metadata.get("subsumed") is None
        assert restored.status == MemoryStatus.ACTIVE
        assert [hit.memory.id for hit in await manager.search("TypeScript", limit=5)] == [memory.id]
    finally:
        await manager.close()


@pytest.mark.asyncio
async def test_find_subsumed_memories_skip_paths(mock_manager, mock_llm):
    """No candidates, missing entries, protected memories and rejected candidates never subsumed."""
    mock_manager.search.return_value = []
    assert await find_subsumed_memories(mock_manager, "new skill", mock_llm) == []

    candidates = [
        MemorySearchResult(memory=SemanticMemory(content="gone"), score=0.9, memory_type=MemoryType.SEMANTIC),
        MemorySearchResult(memory=SemanticMemory(content="subsumed"), score=0.8, memory_type=MemoryType.SEMANTIC),
        MemorySearchResult(memory=SemanticMemory(content="locked"), score=0.7, memory_type=MemoryType.SEMANTIC),
        MemorySearchResult(memory=SemanticMemory(content="fresh"), score=0.6, memory_type=MemoryType.SEMANTIC),
    ]
    protected = SemanticMemory(content="locked", is_user_locked=True)
    protected.id = "locked"
    fresh = SemanticMemory(content="fresh")
    fresh.id = "fresh"
    mock_manager.search.return_value = candidates
    mock_manager.get_memory.side_effect = [None, SemanticMemory(content="subsumed", metadata={"subsumed": True}), protected, fresh]

    mock_structured_llm = MagicMock()
    mock_structured_llm.ainvoke = AsyncMock(return_value=MagicMock(subsumed=False, reason="Not covered"))
    mock_llm.with_structured_output = MagicMock(return_value=mock_structured_llm)

    assert await find_subsumed_memories(mock_manager, "new skill", mock_llm) == []


@pytest.mark.asyncio
async def test_apply_and_undo_swallow_backend_errors(mock_manager):
    """A failing backend must never abort the batch: the handler logs and reports zero."""
    memory = SemanticMemory(content="A")
    memory.id = "id1"
    mock_manager.get_memory.return_value = memory
    mock_manager.update_memory.side_effect = RuntimeError("backend down")

    assert await apply_subsumption(mock_manager, ["id1"]) == 0

    memory.metadata["subsumed"] = True
    assert await undo_subsumption(mock_manager, ["id1"]) == 0

    mock_manager.get_memory.return_value = None
    assert await undo_subsumption(mock_manager, ["gone"]) == 0
