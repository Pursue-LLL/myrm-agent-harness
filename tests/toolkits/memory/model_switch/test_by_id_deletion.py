"""Deleting a memory by id removes every copy of it, not only the one the current model reads.

An interrupted migration leaves a memory in two places: the old model's collection (it is removed
only after the current collection is read back to hold the copy) and the current one. A delete that
removed only the visible copy would let the next migration bring the memory back, so the other copy
has to go with it.
"""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import bm25_collection_for
from myrm_agent_harness.toolkits.memory.manager import MemoryError as MemoryManagerError

from .support import (
    NEW_DIM,
    Embedder,
    GatedEmbedder,
    fail_on,
    held_by,
    manager_for,
    seed,
    semantic,
    while_a_page_is_in_flight,
)

_NAMESPACES = ["global", "agent:default"]


async def _left_in_both_collections(store, old_config, new_config, *, extra_in_old: int = 0):
    """A memory that exists under both models (what an interrupted migration leaves), plus untouched old ones."""
    doomed = semantic("doomed")
    others = [semantic(f"other {i}") for i in range(extra_in_old)]
    await seed(store, old_config, semantics=[doomed, *others])
    await seed(store, new_config, semantics=[semantic("doomed", id=doomed.id)], dim=NEW_DIM)
    return doomed, others


class TestDeletionByIdReachesPreviousModels:
    async def test_a_memory_deleted_after_an_interrupted_migration_does_not_come_back(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        doomed, kept = semantic("doomed"), semantic("kept")
        await seed(store, old_config, semantics=[doomed, kept])
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)
        fail_on(monkeypatch, store, "delete_by_filter", old_config.semantic_collection)
        interrupted = await manager.reindex_from_orphans()
        monkeypatch.undo()
        assert interrupted.failed == 2  # copied, but not removed from the old collection

        assert await manager.delete_memory(new_config.semantic_collection, [doomed.id]) == 1
        await manager.reindex_from_orphans()

        assert set(await held_by(store, new_config.semantic_collection)) == {kept.id}
        assert not await store.collection_exists(old_config.semantic_collection)

    async def test_delete_memory_by_id_reaches_the_previous_model_too(self, store, old_config, new_config) -> None:
        doomed, (kept,) = await _left_in_both_collections(store, old_config, new_config, extra_in_old=1)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        assert await manager.delete_memory_by_id(doomed.id) == 1

        assert set(await held_by(store, old_config.semantic_collection)) == {kept.id}
        assert await held_by(store, new_config.semantic_collection) == {}

    async def test_the_sparse_mirror_of_the_previous_model_forgets_it_too(self, store, old_config, new_config) -> None:
        doomed, (kept,) = await _left_in_both_collections(store, old_config, new_config, extra_in_old=1)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        await manager.delete_memory(new_config.semantic_collection, [doomed.id])

        mirror = bm25_collection_for(old_config.semantic_collection)
        assert set(await held_by(store, mirror)) == {kept.id}

    async def test_an_emptied_previous_collection_is_retired(self, store, old_config, new_config) -> None:
        doomed, _ = await _left_in_both_collections(store, old_config, new_config)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        await manager.delete_memory(new_config.semantic_collection, [doomed.id])

        assert not await store.collection_exists(old_config.semantic_collection)
        assert not await store.collection_exists(bm25_collection_for(old_config.semantic_collection))

    async def test_a_previous_copy_that_cannot_be_removed_keeps_the_memory_and_can_be_retried(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        doomed, _ = await _left_in_both_collections(store, old_config, new_config)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)
        fail_on(monkeypatch, store, "delete", old_config.semantic_collection)

        with pytest.raises(MemoryManagerError, match=old_config.semantic_collection):
            await manager.delete_memory(new_config.semantic_collection, [doomed.id])

        assert set(await held_by(store, new_config.semantic_collection)) == {doomed.id}  # still listed, so retryable
        monkeypatch.undo()
        assert await manager.delete_memory(new_config.semantic_collection, [doomed.id]) == 1
        assert await held_by(store, new_config.semantic_collection) == {}
        assert not await store.collection_exists(old_config.semantic_collection)

    async def test_a_deletion_while_a_page_is_in_flight_does_not_wait_for_the_model_and_is_not_undone(
        self, store, old_config, new_config
    ) -> None:
        doomed, (other,) = await _left_in_both_collections(store, old_config, new_config, extra_in_old=1)
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated, namespaces=_NAMESPACES)

        result = await while_a_page_is_in_flight(
            manager, gated, lambda m: m.delete_memory(new_config.semantic_collection, [doomed.id])
        )

        assert set(await held_by(store, new_config.semantic_collection)) == {other.id}
        assert (result.migrated, result.skipped, result.failed) == (1, 0, 0)
        assert not await store.collection_exists(old_config.semantic_collection)

    async def test_a_chat_purge_does_not_wait_for_a_lock_it_holds_itself(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic("old", source_chat_id="c1")])
        await seed(store, new_config, semantics=[semantic("new", source_chat_id="c1")], dim=NEW_DIM)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        counts = await asyncio.wait_for(manager.purge_by_source_chat_id("c1"), timeout=5)

        assert counts["semantic"] == 2
        assert await held_by(store, new_config.semantic_collection) == {}
        assert not await store.collection_exists(old_config.semantic_collection)


class TestExactDeletionLeavesOtherModelsAlone:
    async def test_deleting_exact_refs_is_an_undo_that_touches_only_the_current_collection(
        self, store, old_config, new_config
    ) -> None:
        doomed, _ = await _left_in_both_collections(store, old_config, new_config)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        result = await manager.delete_memories_by_ids({"semantic": [doomed.id]})

        assert [ref.memory_id for ref in result.deleted_refs] == [doomed.id]
        assert set(await held_by(store, old_config.semantic_collection)) == {doomed.id}
