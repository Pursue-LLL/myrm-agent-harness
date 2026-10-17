"""A deletion landing while a migration page is in flight must neither wait for the model nor be undone.

A page is read, re-embedded and written over several awaits. The re-embedding is a call to an
external model that can take seconds or hang, so a deletion must not queue behind it; and the page,
which already read the memories, must not write back what the deletion removed in the meantime:
deleted by the user, back on disk.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import store_conversations_batch
from myrm_agent_harness.toolkits.memory.manager import MemoryError as MemoryManagerError
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemoryType

from .support import (
    CREATED_AT,
    NEW_DIM,
    OLD_DIM,
    Embedder,
    GatedEmbedder,
    create_conversation_collection,
    episodic,
    fail_on,
    held_by,
    manager_for,
    scope_of,
    scroll_all,
    seed,
    semantic,
    while_a_page_is_in_flight,
)

_NAMESPACES = ["global", "agent:default"]


def _conversation(content: str, *, chat: str) -> ConversationMemory:
    return ConversationMemory(
        content=content,
        raw_exchange=f"User: {content}\nAI: noted.",
        user_id="u1",
        scope=scope_of("default"),
        created_at=CREATED_AT,
        timestamp=CREATED_AT,
        source_chat_id=chat,
    )


class TestDeletionDuringMigration:
    async def test_delete_all_is_not_undone_by_the_page_in_flight(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic(f"memory {i}") for i in range(5)])
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated)

        result = await while_a_page_is_in_flight(manager, gated, lambda m: m.delete_all())

        assert await held_by(store, new_config.semantic_collection) == {}
        assert not await store.collection_exists(old_config.semantic_collection)
        assert result.failed == 0

    async def test_delete_by_type_is_not_undone_by_the_page_in_flight(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic(f"memory {i}") for i in range(5)])
        await store.create_collection(new_config.semantic_collection, NEW_DIM)  # what memory.setup does at startup
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated, namespaces=_NAMESPACES)

        await while_a_page_is_in_flight(manager, gated, lambda m: m.delete_by_type(MemoryType.SEMANTIC))

        assert await held_by(store, new_config.semantic_collection) == {}

    async def test_a_chat_purge_is_not_undone_by_the_page_in_flight(self, store, old_config, new_config) -> None:
        keep = semantic("keep")
        await seed(
            store,
            old_config,
            semantics=[keep, *[semantic(f"purged {i}", source_chat_id="c1") for i in range(4)]],
        )
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated, namespaces=_NAMESPACES)

        await while_a_page_is_in_flight(manager, gated, lambda m: m.purge_by_source_chat_id("c1"))

        assert set(await scroll_all(store, new_config.semantic_collection)) == {keep.id}

    async def test_a_chat_purge_is_not_undone_by_a_conversation_page_in_flight(
        self, store, old_config, new_config
    ) -> None:
        keep = _conversation("keep", chat="c0")
        purged = [_conversation(f"purged {i}", chat="c1") for i in range(3)]
        await create_conversation_collection(store, old_config.conversation_collection, OLD_DIM)
        await create_conversation_collection(store, new_config.conversation_collection, NEW_DIM)
        await store_conversations_batch([keep, *purged], store, old_config, Embedder(OLD_DIM), None)
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated, namespaces=_NAMESPACES)

        result = await while_a_page_is_in_flight(manager, gated, lambda m: m.purge_by_source_chat_id("c1"))

        assert set(await scroll_all(store, new_config.conversation_collection)) == {keep.id}
        assert (result.migrated, result.failed) == (1, 0)

    async def test_a_deletion_between_pages_ends_the_migration_without_counting_failures(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await seed(store, old_config, semantics=[semantic(f"memory {i}") for i in range(5)])
        manager = manager_for(store, new_config, Embedder(NEW_DIM))
        monkeypatch.setattr("myrm_agent_harness.toolkits.memory._manager.reindex._BATCH_SIZE", 2)
        deletions: list[asyncio.Task[dict[str, int]]] = []

        def delete_after_the_first_page(_done: int, _total: int, phase: str) -> None:
            if phase == "migrating" and not deletions:
                deletions.append(asyncio.create_task(manager.delete_all()))

        result = await manager.reindex_from_orphans(progress_cb=delete_after_the_first_page)
        await asyncio.gather(*deletions)

        assert len(deletions) == 1
        assert result.failed == 0
        assert not await store.collection_exists(old_config.semantic_collection)
        assert await scroll_all(store, new_config.semantic_collection) == {}


class TestCurrentCollectionChangesDuringMigration:
    async def test_a_copy_that_reached_the_current_collection_meanwhile_is_not_overwritten(
        self, store, old_config, new_config
    ) -> None:
        stale, other = semantic("old wording"), semantic("other")
        await seed(store, old_config, semantics=[stale, other])
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated)

        async def written_meanwhile(_: MemoryManager) -> None:
            await seed(store, new_config, semantics=[semantic("newer wording", id=stale.id)], dim=NEW_DIM)

        result = await while_a_page_is_in_flight(manager, gated, written_meanwhile)

        current = await scroll_all(store, new_config.semantic_collection)
        assert current[stale.id].content == "newer wording"
        assert current[other.id].content == "other"
        assert (result.migrated, result.skipped, result.failed) == (1, 1, 0)
        assert not await store.collection_exists(old_config.semantic_collection)

    async def test_a_copy_that_left_the_current_collection_meanwhile_is_kept_for_the_next_run(
        self, store, old_config, new_config
    ) -> None:
        moved, other = semantic("moved earlier"), semantic("other")
        await seed(store, old_config, semantics=[moved, other])
        await seed(store, new_config, semantics=[semantic("moved earlier", id=moved.id)], dim=NEW_DIM)
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated)

        async def removed_meanwhile(_: MemoryManager) -> None:
            await store.delete(new_config.semantic_collection, [moved.id])

        first = await while_a_page_is_in_flight(manager, gated, removed_meanwhile)

        assert (first.migrated, first.failed) == (1, 1)
        assert set(await scroll_all(store, old_config.semantic_collection)) == {moved.id}

        second = await manager.reindex_from_orphans()

        assert (second.migrated, second.failed) == (1, 0)
        assert set(await scroll_all(store, new_config.semantic_collection)) == {moved.id, other.id}
        assert not await store.collection_exists(old_config.semantic_collection)


class TestDeleteByTypeFailure:
    async def test_a_previous_collection_that_cannot_be_emptied_is_reported_after_the_graph_is_cleaned(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await seed(store, old_config, episodics=[episodic("old")])
        await seed(store, new_config, episodics=[episodic("new")], dim=NEW_DIM)
        manager = manager_for(store, new_config, Embedder(NEW_DIM), graph=AsyncMock(), namespaces=_NAMESPACES)
        cascade = AsyncMock()
        monkeypatch.setattr(manager, "_cascade_clean_derived_graph_nodes", cascade)
        fail_on(monkeypatch, store, "delete_by_filter", old_config.episodic_collection)

        with pytest.raises(MemoryManagerError, match=old_config.episodic_collection):
            await manager.delete_by_type(MemoryType.EPISODIC)

        assert cascade.await_count == 2
        assert await store.count(new_config.episodic_collection) == 0
