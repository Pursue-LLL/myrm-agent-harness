"""Deleting memories reaches every embedding model's collections, against a real embedded Qdrant.

A model switch leaves the previous model's memories in collections the current model never
reads. A deletion that only looked at the current collections would report success while
those memories stayed on disk, and a later migration would bring them back.
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import store_conversations_batch
from myrm_agent_harness.toolkits.memory.manager import MemoryError as MemoryManagerError
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemoryType

from .support import (
    CREATED_AT,
    NEW_DIM,
    OLD_DIM,
    Embedder,
    create_conversation_collection,
    episodic,
    fail_on,
    manager_for,
    scope_of,
    scroll_all,
    seed,
    semantic,
)

_NAMESPACES = ["global", "agent:default"]


async def _count(store, collection: str) -> int:
    return await store.count(collection) if await store.collection_exists(collection) else 0


async def _seed_two_generations(store, old_config, new_config) -> None:
    await seed(store, old_config, semantics=[semantic("old a"), semantic("old b")], episodics=[episodic("old c")])
    await seed(store, new_config, semantics=[semantic("new a")], episodics=[episodic("new b")], dim=NEW_DIM)


class TestDeleteAll:
    async def test_erases_every_models_memories_and_drops_the_previous_collections(
        self, store, old_config, new_config
    ) -> None:
        await _seed_two_generations(store, old_config, new_config)
        for config, dim in ((old_config, OLD_DIM), (new_config, NEW_DIM)):
            await create_conversation_collection(store, config.conversation_collection, dim)
            chat = ConversationMemory(
                content="a chat",
                raw_exchange="User: hi",
                user_id="u1",
                scope=scope_of("default"),
                created_at=CREATED_AT,
            )
            await store_conversations_batch([chat], store, config, Embedder(dim), None)

        counts = await manager_for(store, new_config, Embedder(NEW_DIM)).delete_all()

        assert counts[new_config.semantic_collection] == 1
        assert counts[old_config.semantic_collection] == 2
        assert counts[old_config.conversation_collection] == 1
        for config in (new_config,):
            for collection in (config.semantic_collection, config.episodic_collection, config.conversation_collection):
                assert await _count(store, collection) == 0
            assert await _count(store, f"{config.semantic_collection}_bm25") == 0
        for collection in (
            old_config.semantic_collection,
            old_config.episodic_collection,
            old_config.conversation_collection,
            f"{old_config.semantic_collection}_bm25",
        ):
            assert not await store.collection_exists(collection)

    async def test_a_store_without_memory_collections_is_a_noop(self, store, new_config) -> None:
        assert await manager_for(store, new_config, Embedder(NEW_DIM)).delete_all() == {}

    async def test_a_failed_collection_is_reported_after_the_others_are_cleared(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await _seed_two_generations(store, old_config, new_config)
        fail_on(monkeypatch, store, "delete_by_filter", old_config.semantic_collection)

        with pytest.raises(MemoryManagerError, match=old_config.semantic_collection):
            await manager_for(store, new_config, Embedder(NEW_DIM)).delete_all()

        assert await _count(store, new_config.semantic_collection) == 0
        assert await _count(store, old_config.semantic_collection) == 2

    async def test_a_listing_failure_reports_a_failure_instead_of_claiming_success(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await _seed_two_generations(store, old_config, new_config)
        monkeypatch.setattr(store, "list_collections", AsyncMock(side_effect=RuntimeError("unreachable")))

        with pytest.raises(MemoryManagerError):
            await manager_for(store, new_config, Embedder(NEW_DIM)).delete_all()

        # The previous model's copies survive: the caller must not read the raise as "nothing was there".
        assert await _count(store, old_config.semantic_collection) == 2


class TestDeleteByType:
    async def test_clears_that_type_in_every_model_and_leaves_the_others(self, store, old_config, new_config) -> None:
        await _seed_two_generations(store, old_config, new_config)

        deleted = await manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES).delete_by_type(
            MemoryType.SEMANTIC
        )

        assert deleted == 3
        assert await _count(store, new_config.semantic_collection) == 0
        assert not await store.collection_exists(old_config.semantic_collection)
        assert await _count(store, new_config.episodic_collection) == 1
        assert await _count(store, old_config.episodic_collection) == 1

    async def test_the_current_model_alone_can_be_replaced_without_touching_the_previous_one(
        self, store, old_config, new_config
    ) -> None:
        await _seed_two_generations(store, old_config, new_config)

        deleted = await manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES).delete_by_type(
            MemoryType.SEMANTIC, include_previous_models=False
        )

        assert deleted == 1
        assert await _count(store, new_config.semantic_collection) == 0
        assert await _count(store, old_config.semantic_collection) == 2

    async def test_a_listing_failure_reports_a_failure_instead_of_a_partial_clear(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await _seed_two_generations(store, old_config, new_config)
        monkeypatch.setattr(store, "list_collections", AsyncMock(side_effect=RuntimeError("unreachable")))

        with pytest.raises(MemoryManagerError):
            await manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES).delete_by_type(
                MemoryType.SEMANTIC
            )

        # The previous model's copies survive and the raise says so: the caller retries rather than
        # believing the family is clean.
        assert await _count(store, old_config.semantic_collection) == 2


class TestChatCascade:
    async def test_purge_reaches_memories_the_previous_model_still_holds(self, store, old_config, new_config) -> None:
        keep, drop_old, drop_new = (
            semantic("keep"),
            semantic("old", source_chat_id="c1"),
            semantic("new", source_chat_id="c1"),
        )
        await seed(store, old_config, semantics=[keep, drop_old])
        await seed(store, new_config, semantics=[drop_new], dim=NEW_DIM)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        counts = await manager.purge_by_source_chat_id("c1")

        assert counts["semantic"] == 2
        assert set(await scroll_all(store, old_config.semantic_collection)) == {keep.id}
        assert await _count(store, new_config.semantic_collection) == 0

    async def test_the_deletion_preview_counts_what_the_purge_removes(self, store, old_config, new_config) -> None:
        await seed(
            store,
            old_config,
            semantics=[semantic("old", source_chat_id="c1")],
            episodics=[episodic("e", source_chat_id="c1")],
        )
        await seed(store, new_config, semantics=[semantic("new", source_chat_id="c1")], dim=NEW_DIM)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        preview = await manager.count_by_source_chat_id("c1")
        purged = await manager.purge_by_source_chat_id("c1")

        assert preview == {"semantic": 2, "episodic": 1}
        assert {k: v for k, v in purged.items() if v} == preview

    async def test_a_cascade_manager_that_names_no_real_model_reaches_every_collection(
        self, store, old_config, new_config
    ) -> None:
        await seed(store, old_config, semantics=[semantic("old", source_chat_id="c1")])
        await seed(store, new_config, semantics=[semantic("new", source_chat_id="c1")], dim=NEW_DIM)
        cascade_config = replace(new_config, embedding_model="cascade-deletion")
        manager = manager_for(store, cascade_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)

        counts = await manager.purge_by_source_chat_id("c1")

        assert counts["semantic"] == 2
        assert await _count(store, new_config.semantic_collection) == 0
        assert await _count(store, old_config.semantic_collection) == 0


class TestChainedSwitches:
    async def test_a_deleted_memory_does_not_come_back_with_the_next_switch(
        self, store, old_config, new_config, third_config
    ) -> None:
        forgotten, kept = semantic("forget me"), semantic("keep me")
        await seed(store, old_config, semantics=[forgotten, kept])
        second = manager_for(store, new_config, Embedder(NEW_DIM), namespaces=_NAMESPACES)
        await second.reindex_from_orphans()

        result = await second.delete_memories_by_ids({"semantic": [forgotten.id]})
        assert [ref.memory_id for ref in result.deleted_refs] == [forgotten.id]
        await manager_for(store, third_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert set(await scroll_all(store, third_config.semantic_collection)) == {kept.id}
        assert not await store.collection_exists(old_config.semantic_collection)
        assert not await store.collection_exists(new_config.semantic_collection)
