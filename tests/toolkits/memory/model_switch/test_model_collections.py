"""Which collections hold memories, which a model switch left behind, and how an emptied one is retired."""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._manager.model_collections import (
    ModelCollection,
    current_collection,
    family_lock,
    memory_collections,
    previous_model_collections,
    retire_if_drained,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryError
from myrm_agent_harness.toolkits.memory.types import MemoryType

from .support import NEW_DIM, Embedder, create_conversation_collection, manager_for, seed, semantic


class TestPreviousModelCollections:
    def test_lists_collections_of_other_models_with_their_type_and_model(self, prefix, new_config) -> None:
        names = [
            f"{prefix}_semantic_old-model",
            f"{prefix}_episodic_old-model",
            f"{prefix}_conversation_older-model",
        ]

        found = previous_model_collections(names, new_config)

        assert found == [
            ModelCollection(f"{prefix}_conversation_older-model", MemoryType.CONVERSATION, "older-model"),
            ModelCollection(f"{prefix}_episodic_old-model", MemoryType.EPISODIC, "old-model"),
            ModelCollection(f"{prefix}_semantic_old-model", MemoryType.SEMANTIC, "old-model"),
        ]

    def test_the_current_models_collections_are_not_previous(self, new_config) -> None:
        names = [current_collection(new_config, t) for t in (MemoryType.SEMANTIC, MemoryType.EPISODIC)]

        assert previous_model_collections(names, new_config) == []

    def test_sparse_mirrors_are_not_model_collections(self, prefix, new_config) -> None:
        names = [f"{prefix}_semantic_old-model_bm25", f"{new_config.semantic_collection}_bm25"]

        assert previous_model_collections(names, new_config) == []

    def test_other_prefixes_and_unrelated_collections_are_not_ours(self, prefix, new_config) -> None:
        names = [
            f"{prefix}x_semantic_old-model",
            f"other_{prefix}_semantic_old-model",
            f"{prefix}_semantic_",
            f"{prefix}_notes_old-model",
            "wiki_chunks",
        ]

        assert previous_model_collections(names, new_config) == []


class TestMemoryCollections:
    async def test_lists_the_current_model_first_then_previous_models_that_exist(
        self, store, old_config, new_config
    ) -> None:
        await seed(store, old_config, semantics=[semantic("old")])
        await seed(store, new_config, semantics=[semantic("new")], dim=NEW_DIM)
        await create_conversation_collection(store, old_config.conversation_collection, 8)
        manager = manager_for(store, new_config, Embedder(NEW_DIM))

        found = await memory_collections(manager._vector, new_config)

        assert found == {
            MemoryType.SEMANTIC: [new_config.semantic_collection, old_config.semantic_collection],
            MemoryType.EPISODIC: [],
            MemoryType.CONVERSATION: [old_config.conversation_collection],
        }

    async def test_a_backend_that_cannot_list_collections_reports_the_current_model_only(self, new_config) -> None:
        found = await memory_collections(AsyncMock(), new_config)

        assert found == {
            MemoryType.SEMANTIC: [new_config.semantic_collection],
            MemoryType.EPISODIC: [new_config.episodic_collection],
            MemoryType.CONVERSATION: [new_config.conversation_collection],
        }

    async def test_a_failing_listing_raises_instead_of_hiding_other_models(
        self, store, new_config, monkeypatch
    ) -> None:
        monkeypatch.setattr(store, "list_collections", AsyncMock(side_effect=RuntimeError("unreachable")))
        manager = manager_for(store, new_config, Embedder(NEW_DIM))

        with pytest.raises(MemoryError, match="list memory collections"):
            await memory_collections(manager._vector, new_config)


class TestRetireIfDrained:
    async def test_drops_an_emptied_collection_with_its_sparse_mirror(self, store, old_config) -> None:
        memory = semantic("only one")
        await seed(store, old_config, semantics=[memory])
        manager = manager_for(store, old_config, Embedder(NEW_DIM))
        await manager._vector.delete(old_config.semantic_collection, [memory.id])  # type: ignore[union-attr]

        await retire_if_drained(manager._vector, old_config.semantic_collection)

        assert not await store.collection_exists(old_config.semantic_collection)
        assert not await store.collection_exists(f"{old_config.semantic_collection}_bm25")

    async def test_leaves_a_collection_that_still_holds_memories(self, store, old_config) -> None:
        await seed(store, old_config, semantics=[semantic("still here")])
        manager = manager_for(store, old_config, Embedder(NEW_DIM))

        await retire_if_drained(manager._vector, old_config.semantic_collection)

        assert await store.count(old_config.semantic_collection) == 1

    async def test_a_backend_that_cannot_list_collections_is_left_alone(self) -> None:
        vector = AsyncMock()

        await retire_if_drained(vector, "memory_semantic_old")

        vector.delete_collection.assert_not_called()


class TestFamilyLock:
    """Managers are built per request over one shared backend, so the lock must follow the backend, not the manager."""

    def test_managers_over_the_same_backend_and_prefix_share_one_lock(self, store, old_config, new_config) -> None:
        first = manager_for(store, old_config, Embedder(NEW_DIM))
        second = manager_for(store, new_config, Embedder(NEW_DIM))

        assert family_lock(first._vector, first._config) is family_lock(second._vector, second._config)

    def test_another_prefix_or_another_backend_has_its_own_lock(self, store, new_config) -> None:
        other_prefix = replace(new_config, collection_prefix=f"{new_config.collection_prefix}x")
        manager = manager_for(store, new_config, Embedder(NEW_DIM))

        assert family_lock(manager._vector, manager._config) is not family_lock(manager._vector, other_prefix)
        assert family_lock(AsyncMock(), new_config) is not family_lock(AsyncMock(), new_config)
