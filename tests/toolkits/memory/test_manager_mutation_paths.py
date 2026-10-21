"""Mutation mixin paths: sparse mutation, archive side effects, exact-fact bookkeeping and write guards."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError, MemoryNotFoundError, MemoryProtectedError
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    ConversationMemory,
    EpisodicMemory,
    MemoryStatus,
    ProceduralMemory,
    SemanticMemory,
)

_STRUCTURED = "name: Alice\ncity: Berlin"
_MUTATIONS = "myrm_agent_harness.toolkits.memory._manager.mutations"


@pytest.fixture
def manager(mock_vector_store, mock_relational_store, mock_embedding, memory_config) -> MemoryManager:
    return MemoryManager(
        memory_config,
        user_id="test_user",
        vector=mock_vector_store,
        relational=mock_relational_store,
        embedding=mock_embedding,
        approval_required=False,
    )


@pytest.fixture
def persisted():
    """Echo whatever the mutation hands to the vector writer so tests can inspect it."""
    with patch(f"{_MUTATIONS}.update_vector_memory", new=AsyncMock(side_effect=lambda memory, *_a, **_k: memory)) as m:
        yield m


def _serve(manager: MemoryManager, memory) -> None:
    manager.get_memory = AsyncMock(return_value=memory)


class TestSparseMutate:
    @pytest.mark.asyncio
    async def test_missing_memory_is_reported(self, manager):
        _serve(manager, None)

        with pytest.raises(MemoryNotFoundError):
            await manager.sparse_mutate_memory("mem-x", "city: Paris")

    @pytest.mark.asyncio
    async def test_only_semantic_memories_can_be_mutated(self, manager):
        _serve(manager, EpisodicMemory(id="mem-e", content="event"))

        with pytest.raises(MemoryError, match="only supports SemanticMemory"):
            await manager.sparse_mutate_memory("mem-e", "city: Paris")

    @pytest.mark.asyncio
    async def test_protected_memory_refuses_automated_mutation(self, manager, persisted):
        _serve(manager, SemanticMemory(id="mem-p", content=_STRUCTURED, pinned=True))

        with pytest.raises(MemoryProtectedError):
            await manager.sparse_mutate_memory("mem-p", "city: Paris")

        persisted.assert_not_called()

    @pytest.mark.asyncio
    async def test_unstructured_prose_is_left_untouched(self, manager, persisted):
        existing = SemanticMemory(id="mem-u", content="Likes tea")
        _serve(manager, existing)

        result = await manager.sparse_mutate_memory("mem-u", "Likes coffee")

        assert result is existing
        persisted.assert_not_called()

    @pytest.mark.asyncio
    async def test_structured_patch_overwrites_one_slot_and_keeps_the_rest(self, manager, persisted):
        _serve(manager, SemanticMemory(id="mem-s", content=_STRUCTURED))

        result = await manager.sparse_mutate_memory("mem-s", "city: Paris")

        assert result.content == "name: Alice\ncity: Paris"
        assert result.metadata["sparse_retained_count"] == 1
        assert result.metadata["sparse_overwritten_count"] == 1
        assert persisted.await_args.args[1] is True


class TestCorrectionKeepsStructure:
    @pytest.mark.asyncio
    async def test_structured_correction_merges_slots_and_records_the_mutation(self, manager, persisted):
        _serve(manager, SemanticMemory(id="mem-s", content=_STRUCTURED))
        manager._store_semantic = AsyncMock(side_effect=lambda memory: memory)

        correction = await manager.correct_memory("mem-s", "city: Paris")

        assert correction.content == "name: Alice\ncity: Paris"
        assert correction.metadata["sparse_retained_count"] == 1
        assert correction.correction_of == "mem-s"


class TestUpdateGuards:
    @pytest.mark.asyncio
    async def test_transient_business_state_is_not_saved_as_memory(self, manager, persisted):
        _serve(manager, SemanticMemory(id="mem-t", content="Likes tea"))

        with pytest.raises(MemoryError, match="transient"):
            await manager.update_memory("mem-t", content="Package SF998877 is in transit at sorting hub")

        persisted.assert_not_called()

    @pytest.mark.asyncio
    async def test_memory_types_without_a_store_are_rejected(self, manager, persisted):
        _serve(manager, ConversationMemory(id="mem-c", raw_exchange="user: hi", content="hi"))

        with pytest.raises(ValueError, match="Cannot update memory type"):
            await manager.update_memory("mem-c", importance=0.9)

    @pytest.mark.asyncio
    async def test_vector_backed_update_needs_a_vector_backend(self, manager, persisted):
        _serve(manager, SemanticMemory(id="mem-v", content="Likes tea"))
        manager._vector = None

        with pytest.raises(MemoryError, match="Vector backend required"):
            await manager.update_memory("mem-v", importance=0.9)


class TestArchiveSideEffects:
    @pytest.mark.asyncio
    async def test_archiving_stamps_retention_cleans_derived_nodes_and_evicts_the_cache(self, manager, persisted):
        _serve(manager, SemanticMemory(id="mem-a", content="Likes tea"))
        manager._cascade_clean_derived_graph_nodes = AsyncMock()
        manager._cache = AsyncMock()

        result = await manager.update_memory("mem-a", status=MemoryStatus.ARCHIVED)

        assert result.metadata["archive_reason"] == "user_deleted"
        assert "archive_expires_at" in result.metadata
        manager._cascade_clean_derived_graph_nodes.assert_awaited_once_with("mem-a")
        manager._cache.evict.assert_awaited_once_with("Likes tea")

    @pytest.mark.asyncio
    async def test_restoring_an_archived_memory_drops_its_retention_stamps(self, manager, persisted):
        archived = SemanticMemory(
            id="mem-a",
            content="Likes tea",
            status=MemoryStatus.ARCHIVED,
            metadata={"archived_at": "t", "archive_expires_at": "t2", "archive_reason": "user_deleted"},
        )
        _serve(manager, archived)

        result = await manager.update_memory("mem-a", status=MemoryStatus.ACTIVE)

        assert not {"archived_at", "archive_expires_at", "archive_reason"} & set(result.metadata)


class TestProceduralToggle:
    @pytest.mark.asyncio
    async def test_deactivating_a_rule_without_a_status_disables_it(self, manager, mock_relational_store):
        rule = ProceduralMemory(id="rule-1", trigger="when asked", action="answer briefly")
        _serve(manager, rule)
        mock_relational_store.update_rule = AsyncMock(side_effect=lambda _id, memory: memory)

        result = await manager.update_memory("rule-1", is_active=False)

        assert result.is_active is False
        assert result.status == MemoryStatus.DISABLED
        mock_relational_store.update_rule.assert_awaited_once()


class TestExactFactBookkeeping:
    @pytest.mark.asyncio
    async def test_marking_a_fact_exact_records_its_identifiers(self, manager, mock_relational_store, persisted):
        _serve(manager, SemanticMemory(id="mem-f", content="Server IP is 10.0.0.1"))
        mock_relational_store.record_exact_fact = AsyncMock()

        result = await manager.update_memory("mem-f", is_exact_fact=True)

        assert result.is_exact_fact is True
        mock_relational_store.record_exact_fact.assert_awaited_once()
        assert mock_relational_store.record_exact_fact.await_args.kwargs["memory_id"] == "mem-f"

    @pytest.mark.asyncio
    async def test_a_failing_exact_fact_index_does_not_block_the_update(
        self, manager, mock_relational_store, persisted
    ):
        _serve(manager, SemanticMemory(id="mem-f", content="Server IP is 10.0.0.1"))
        mock_relational_store.record_exact_fact = AsyncMock(side_effect=RuntimeError("db down"))

        result = await manager.update_memory("mem-f", is_exact_fact=True)

        assert result.is_exact_fact is True

    @pytest.mark.asyncio
    async def test_unmarking_an_exact_fact_removes_its_index_entry(self, manager, mock_relational_store, persisted):
        _serve(manager, SemanticMemory(id="mem-f", content="Server IP is 10.0.0.1", is_exact_fact=True))
        mock_relational_store.delete_exact_fact = AsyncMock()

        result = await manager.update_memory("mem-f", is_exact_fact=False)

        assert result.exact_identifiers == []
        mock_relational_store.delete_exact_fact.assert_awaited_once_with("mem-f")

    @pytest.mark.asyncio
    async def test_a_failing_index_removal_does_not_block_unmarking(self, manager, mock_relational_store, persisted):
        _serve(manager, SemanticMemory(id="mem-f", content="Server IP is 10.0.0.1", is_exact_fact=True))
        mock_relational_store.delete_exact_fact = AsyncMock(side_effect=RuntimeError("db down"))

        result = await manager.update_memory("mem-f", is_exact_fact=False)

        assert result.is_exact_fact is False

    @pytest.mark.asyncio
    async def test_rewording_an_exact_fact_refreshes_its_identifiers(self, manager, mock_relational_store, persisted):
        _serve(manager, SemanticMemory(id="mem-f", content="Server IP is 10.0.0.1", is_exact_fact=True))
        mock_relational_store.record_exact_fact = AsyncMock()

        await manager.update_memory("mem-f", content="Server IP is 10.0.0.2")

        mock_relational_store.record_exact_fact.assert_awaited_once()
        assert mock_relational_store.record_exact_fact.await_args.kwargs["content"] == "Server IP is 10.0.0.2"

    @pytest.mark.asyncio
    async def test_a_failing_refresh_does_not_block_the_reword(self, manager, mock_relational_store, persisted):
        _serve(manager, SemanticMemory(id="mem-f", content="Server IP is 10.0.0.1", is_exact_fact=True))
        mock_relational_store.record_exact_fact = AsyncMock(side_effect=RuntimeError("db down"))

        result = await manager.update_memory("mem-f", content="Server IP is 10.0.0.2")

        assert result.content == "Server IP is 10.0.0.2"
