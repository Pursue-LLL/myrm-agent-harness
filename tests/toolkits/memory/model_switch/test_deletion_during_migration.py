"""A deletion landing while a migration page is in flight must not be undone by that page.

A page is read, re-embedded and written over several awaits. Without coordination the deletion
wipes the previous model's collection in the middle, and the page then writes the memories it
had already read into the current model's collection: deleted by the user, back on disk.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest

from myrm_agent_harness.toolkits.memory.manager import MemoryError as MemoryManagerError
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import MemoryType

from .support import NEW_DIM, Embedder, episodic, fail_on, manager_for, scroll_all, seed, semantic

_NAMESPACES = ["global", "agent:default"]


class GatedEmbedder(Embedder):
    """Holds every embedding call until released, so a test can act while a page is in flight."""

    def __init__(self, dim: int) -> None:
        super().__init__(dim)
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.entered.set()
        await self.release.wait()
        return await super().embed_batch(texts)


async def _delete_while_a_page_is_in_flight(
    manager: MemoryManager, gated: GatedEmbedder, delete: Callable[[MemoryManager], Awaitable[object]]
):
    migration = asyncio.create_task(manager.reindex_from_orphans())
    await gated.entered.wait()
    deletion = asyncio.create_task(delete(manager))
    await asyncio.sleep(0.2)  # the deletion has reached the lock the page holds
    assert not deletion.done()
    gated.release.set()
    await deletion
    return await migration


class TestDeletionDuringMigration:
    async def test_delete_all_is_not_undone_by_the_page_in_flight(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic(f"memory {i}") for i in range(5)])
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated)

        result = await _delete_while_a_page_is_in_flight(manager, gated, lambda m: m.delete_all())

        assert await scroll_all(store, new_config.semantic_collection) == {}
        assert not await store.collection_exists(old_config.semantic_collection)
        assert result.failed == 0

    async def test_delete_by_type_is_not_undone_by_the_page_in_flight(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic(f"memory {i}") for i in range(5)])
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated, namespaces=_NAMESPACES)

        await _delete_while_a_page_is_in_flight(manager, gated, lambda m: m.delete_by_type(MemoryType.SEMANTIC))

        assert await scroll_all(store, new_config.semantic_collection) == {}

    async def test_a_chat_purge_is_not_undone_by_the_page_in_flight(self, store, old_config, new_config) -> None:
        keep = semantic("keep")
        await seed(
            store,
            old_config,
            semantics=[keep, *[semantic(f"purged {i}", source_chat_id="c1") for i in range(4)]],
        )
        gated = GatedEmbedder(NEW_DIM)
        manager = manager_for(store, new_config, gated, namespaces=_NAMESPACES)

        await _delete_while_a_page_is_in_flight(manager, gated, lambda m: m.purge_by_source_chat_id("c1"))

        assert set(await scroll_all(store, new_config.semantic_collection)) == {keep.id}

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
