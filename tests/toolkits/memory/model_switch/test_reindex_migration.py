"""Embedding-model switch migration against a real embedded Qdrant.

Mock-store tests cannot prove that a migrated memory is still the *same* memory
(id, owner scope, pin, tags, timestamps), that its vector really comes from the new model,
or that the old collections (and their BM25 mirrors) are left clean. Every scenario drives
``MemoryManager.reindex_from_orphans`` over real collections of different embedding
dimensions, with the sparse mirror warmed as in production.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from myrm_agent_harness.toolkits.memory._internal.storage import store_conversations_batch
from myrm_agent_harness.toolkits.memory._manager.reindex import _BATCH_SIZE
from myrm_agent_harness.toolkits.memory.manager import MemoryError as MemoryManagerError
from myrm_agent_harness.toolkits.memory.types import ConversationMemory
from myrm_agent_harness.toolkits.vector.base import VectorDocument
from myrm_agent_harness.toolkits.vector.qdrant.filters import point_id_for

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
    unit,
)


async def _exists(store, name: str) -> bool:
    return await store.collection_exists(name)


class TestSemanticMigration:
    async def test_migrated_memories_keep_identity_scope_and_state(self, store, old_config, new_config) -> None:
        default_agent = semantic("User prefers dark mode", importance=0.9, tags=["UI", "Theme"])
        researcher = semantic("Researcher cites arXiv ids", agent="researcher", importance=0.7)
        pinned = semantic("Never deploy on Friday", pinned=True, access_count=4, user_rating=0.8)
        await seed(store, old_config, semantics=[default_agent, researcher, pinned])

        new_embedder = Embedder(NEW_DIM)
        result = await manager_for(store, new_config, new_embedder).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (3, 0, 0)
        migrated = await scroll_all(store, new_config.semantic_collection)
        assert set(migrated) == {default_agent.id, researcher.id, pinned.id}

        for original in (default_agent, researcher, pinned):
            doc = migrated[original.id]
            assert doc.content == original.content
            assert doc.metadata["primary_namespace"] == original.scope.primary_namespace
            assert doc.metadata["namespaces"] == original.scope.namespaces
            assert doc.metadata["pinned"] is original.pinned
            assert doc.metadata["importance"] == original.importance
            assert doc.metadata["access_count"] == original.access_count
            assert doc.metadata["user_rating"] == original.user_rating
            assert doc.created_at == CREATED_AT
            assert doc.vector == pytest.approx(unit(new_embedder.vector_of(original.content)))
        assert migrated[default_agent.id].metadata["tags"] == ["ui", "theme"]

    async def test_vectors_come_from_new_model_and_the_old_collection_is_retired(
        self, store, old_config, new_config
    ) -> None:
        memory = semantic("Prefers tabs over spaces")
        await seed(store, old_config, semantics=[memory])

        await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        migrated = await scroll_all(store, new_config.semantic_collection)
        assert len(migrated[memory.id].vector or []) == NEW_DIM
        assert not await _exists(store, old_config.semantic_collection)
        assert not await _exists(store, f"{old_config.semantic_collection}_bm25")

    async def test_rerun_finds_nothing_left_to_migrate(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(3)])
        new_embedder = Embedder(NEW_DIM)
        manager = manager_for(store, new_config, new_embedder)

        first = await manager.reindex_from_orphans()
        embedded_after_first = len(new_embedder.embedded_texts)
        second = await manager.reindex_from_orphans()

        assert (first.migrated, first.skipped, first.failed) == (3, 0, 0)
        assert (second.migrated, second.skipped, second.failed) == (0, 0, 0)
        assert len(new_embedder.embedded_texts) == embedded_after_first
        assert len(await scroll_all(store, new_config.semantic_collection)) == 3

    async def test_copies_already_in_the_current_collection_are_cleared_without_embedding(
        self, store, old_config, new_config
    ) -> None:
        memories = [semantic(f"fact {index}") for index in range(3)]
        await seed(store, old_config, semantics=memories)
        new_embedder = Embedder(NEW_DIM)
        manager = manager_for(store, new_config, new_embedder)
        await manager.reindex_from_orphans()
        embedded_after_first = len(new_embedder.embedded_texts)
        await seed(store, old_config, semantics=memories)  # a copy left by an earlier migration

        result = await manager.reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 3, 0)
        assert len(new_embedder.embedded_texts) == embedded_after_first
        assert not await _exists(store, old_config.semantic_collection)

    async def test_migration_does_not_back_off_while_the_new_models_sparse_mirror_is_missing(
        self, store, old_config, new_config, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The new model has no ``_bm25`` mirror until its first backfill; every batch must fail open at once, not retry."""
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(3)])

        with caplog.at_level("WARNING"):
            result = await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (3, 0, 0)
        assert [r.message for r in caplog.records if "Retrying in" in r.message] == []

    async def test_memory_written_after_the_switch_is_never_overwritten(self, store, old_config, new_config) -> None:
        stale = semantic("stale copy", importance=0.1)
        await seed(store, old_config, semantics=[stale])
        fresh = stale.model_copy(update={"content": "edited after the switch", "importance": 0.95})
        await seed(store, new_config, semantics=[fresh], dim=NEW_DIM)

        result = await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 1, 0)
        kept = (await scroll_all(store, new_config.semantic_collection))[stale.id]
        assert kept.content == "edited after the switch"
        assert kept.metadata["importance"] == 0.95
        assert not await _exists(store, old_config.semantic_collection)

    async def test_pagination_embeds_in_batches_and_moves_every_memory(self, store, old_config, new_config) -> None:
        total = _BATCH_SIZE * 2 + 30
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(total)])
        new_embedder = Embedder(NEW_DIM)

        result = await manager_for(store, new_config, new_embedder).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (total, 0, 0)
        assert new_embedder.batch_sizes == [_BATCH_SIZE, _BATCH_SIZE, 30]
        assert len(await scroll_all(store, new_config.semantic_collection)) == total
        assert not await _exists(store, old_config.semantic_collection)

    async def test_blank_memory_is_removed_not_embedded(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic("kept")])
        blank_id = str(uuid4())
        await store.upsert(
            old_config.semantic_collection,
            [VectorDocument(id=blank_id, content="  ", vector=[0.1] * OLD_DIM, metadata={"user_id": "u1"})],
        )
        new_embedder = Embedder(NEW_DIM)

        result = await manager_for(store, new_config, new_embedder).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (1, 1, 0)
        assert new_embedder.embedded_texts == ["kept"]
        assert not await _exists(store, old_config.semantic_collection)

    async def test_no_orphans_is_a_clean_noop(self, store, new_config) -> None:
        result = await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 0, 0)

    async def test_progress_reports_start_running_total_and_completion(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(_BATCH_SIZE + 5)])
        events: list[tuple[int, int, str]] = []

        await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans(
            progress_cb=lambda done, total, phase: events.append((done, total, phase))
        )

        total = _BATCH_SIZE + 5
        assert events[0] == (0, total, "starting")
        assert [e[0] for e in events] == sorted(e[0] for e in events)
        assert (_BATCH_SIZE, total, "migrating") in events
        assert events[-1] == (total, total, "completed")


class TestOrphanDetection:
    async def test_estimate_counts_memories_of_previous_models_not_their_sparse_mirrors(
        self, store, old_config, new_config
    ) -> None:
        await seed(store, old_config, semantics=[semantic("a"), semantic("b")], episodics=[episodic("c")])
        await seed(store, new_config, semantics=[semantic("current")], dim=NEW_DIM)

        manager = manager_for(store, new_config, Embedder(NEW_DIM))
        estimate = await manager.estimate_reindex()

        assert estimate.total_memories == 3
        found = {(o.collection_name, o.memory_type, o.document_count) for o in await manager.detect_orphan_collections()}
        assert found == {
            (old_config.semantic_collection, "semantic", 2),
            (old_config.episodic_collection, "episodic", 1),
        }

    async def test_a_model_that_never_switched_has_no_orphans(self, store, old_config) -> None:
        await seed(store, old_config, semantics=[semantic("a"), semantic("b")], episodics=[episodic("c")])

        manager = manager_for(store, old_config, Embedder(OLD_DIM))

        assert (await manager.estimate_reindex()).total_memories == 0
        assert await manager.detect_orphan_collections() == []

    async def test_a_failing_listing_raises_instead_of_reporting_no_orphans(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await seed(store, old_config, semantics=[semantic("a")])
        monkeypatch.setattr(store, "list_collections", AsyncMock(side_effect=RuntimeError("unreachable")))
        manager = manager_for(store, new_config, Embedder(NEW_DIM))

        with pytest.raises(MemoryManagerError, match="orphan detection"):
            await manager.estimate_reindex()
        with pytest.raises(MemoryManagerError, match="orphan detection"):
            await manager.reindex_from_orphans()

    async def test_a_collection_that_cannot_be_counted_is_reported_not_silently_dropped(
        self, store, old_config, new_config, monkeypatch, caplog
    ) -> None:
        await seed(store, old_config, semantics=[semantic("a")], episodics=[episodic("b")])
        fail_on(monkeypatch, store, "count", old_config.semantic_collection)
        manager = manager_for(store, new_config, Embedder(NEW_DIM))

        with caplog.at_level("WARNING"):
            orphans = await manager.detect_orphan_collections()

        assert [o.collection_name for o in orphans] == [old_config.episodic_collection]
        assert old_config.semantic_collection in caplog.text

    async def test_collections_of_another_prefix_are_not_orphans(self, store, prefix, new_config) -> None:
        foreign = replace(new_config, collection_prefix=f"{prefix}x", embedding_model="old-model")
        await seed(store, foreign, semantics=[semantic("not ours")])

        estimate = await manager_for(store, new_config, Embedder(NEW_DIM)).estimate_reindex()

        assert estimate.total_memories == 0


class TestFailureAccounting:
    async def test_embedding_failure_keeps_the_memory_in_the_old_collection(
        self, store, old_config, new_config
    ) -> None:
        fine = semantic("migrates fine")
        poisoned = episodic("embedding provider rejects POISON")
        await seed(store, old_config, semantics=[fine], episodics=[poisoned])

        result = await manager_for(store, new_config, Embedder(NEW_DIM, fail_marker="POISON")).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (1, 0, 1)
        assert set(await scroll_all(store, new_config.semantic_collection)) == {fine.id}
        assert not await _exists(store, new_config.episodic_collection)
        assert not await _exists(store, old_config.semantic_collection)
        assert set(await scroll_all(store, old_config.episodic_collection)) == {poisoned.id}

    async def test_write_failure_leaves_the_old_collection_untouched(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(4)])
        fail_on(monkeypatch, store, "upsert", new_config.semantic_collection)

        result = await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 0, 4)
        assert await store.count(old_config.semantic_collection) == 4

    async def test_a_write_the_current_collection_does_not_hold_is_never_trusted(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(3)])
        original = store.upsert

        async def lossy(name: str, documents: list[VectorDocument]) -> list[str]:
            return [] if name == new_config.semantic_collection else await original(name, documents)

        monkeypatch.setattr(store, "upsert", lossy)

        result = await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 0, 3)
        assert await store.count(old_config.semantic_collection) == 3

    async def test_failed_removal_is_retried_and_never_duplicates(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(3)])
        new_embedder = Embedder(NEW_DIM)
        manager = manager_for(store, new_config, new_embedder)
        fail_on(monkeypatch, store, "delete_by_filter", old_config.semantic_collection)

        broken = await manager.reindex_from_orphans()
        monkeypatch.undo()
        embedded_after_broken = len(new_embedder.embedded_texts)
        healed = await manager.reindex_from_orphans()

        assert (broken.migrated, broken.failed) == (0, 3)
        assert (healed.migrated, healed.skipped, healed.failed) == (0, 3, 0)
        assert len(new_embedder.embedded_texts) == embedded_after_broken
        assert len(await scroll_all(store, new_config.semantic_collection)) == 3
        assert not await _exists(store, old_config.semantic_collection)

    async def test_read_failure_midway_counts_unread_remainder_as_failed(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        total = _BATCH_SIZE * 2 + 30
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(total)])
        fail_on(monkeypatch, store, "scroll", old_config.semantic_collection, after_calls=1)

        result = await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (_BATCH_SIZE, 0, total - _BATCH_SIZE)
        assert await store.count(old_config.semantic_collection) == total - _BATCH_SIZE

    async def test_failed_memories_migrate_on_the_next_run(self, store, old_config, new_config) -> None:
        await seed(store, old_config, semantics=[semantic(f"fact {index}") for index in range(3)])

        broken = await manager_for(store, new_config, Embedder(NEW_DIM, fail_marker="fact")).reindex_from_orphans()
        still_there = await store.count(old_config.semantic_collection)
        healed = await manager_for(store, new_config, Embedder(NEW_DIM)).reindex_from_orphans()

        assert (broken.migrated, broken.failed, still_there) == (0, 3, 3)
        assert (healed.migrated, healed.skipped, healed.failed) == (3, 0, 0)
        assert not await _exists(store, old_config.semantic_collection)


class TestEpisodicMigration:
    async def test_episodic_keeps_identity_scope_and_does_not_duplicate_graph_nodes(
        self, store, old_config, new_config
    ) -> None:
        episode = episodic(
            "Deployed the billing service", agent="researcher", related_entities=["billing"], importance=0.8
        )
        await seed(store, old_config, episodics=[episode])
        graph = AsyncMock()
        new_embedder = Embedder(NEW_DIM)

        result = await manager_for(store, new_config, new_embedder, graph=graph).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (1, 0, 0)
        doc = (await scroll_all(store, new_config.episodic_collection))[episode.id]
        assert doc.content == episode.content
        assert doc.metadata["primary_namespace"] == "agent:researcher"
        assert doc.metadata["importance"] == 0.8
        assert doc.created_at == CREATED_AT
        assert doc.vector == pytest.approx(unit(new_embedder.vector_of(episode.content)))
        graph.create_node.assert_not_called()
        graph.create_relationship.assert_not_called()
        assert not await _exists(store, old_config.episodic_collection)


class TestConversationMigration:
    async def test_conversation_re_embeds_both_vectors_and_keeps_payload(self, store, old_config, new_config) -> None:
        await create_conversation_collection(store, old_config.conversation_collection, OLD_DIM)
        await create_conversation_collection(store, new_config.conversation_collection, NEW_DIM)
        exchange = ConversationMemory(
            content="Discussed the rollout plan",
            raw_exchange="User: how do we roll out?\nAI: canary first, then 50%.",
            user_id="u1",
            scope=scope_of("researcher"),
            created_at=CREATED_AT,
            timestamp=CREATED_AT + timedelta(minutes=5),
            source_chat_id="chat-1",
            importance=0.7,
        )
        await store_conversations_batch([exchange], store, old_config, Embedder(OLD_DIM), None)
        new_embedder = Embedder(NEW_DIM)

        result = await manager_for(store, new_config, new_embedder).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (1, 0, 0)
        assert set(new_embedder.embedded_texts) == {exchange.raw_exchange, exchange.content}
        points = await store._with_retry(  # type: ignore[attr-defined]
            store._client.retrieve,  # type: ignore[attr-defined]
            collection_name=new_config.conversation_collection,
            ids=[point_id_for(exchange.id)],
            with_payload=True,
            with_vectors=True,
        )
        assert len(points) == 1
        payload = points[0].payload
        assert payload["raw_exchange"] == exchange.raw_exchange
        assert payload["content"] == exchange.content
        assert payload["primary_namespace"] == "agent:researcher"
        assert payload["source_chat_id"] == "chat-1"
        assert payload["importance"] == 0.7
        assert len(points[0].vector["raw"]) == NEW_DIM
        assert len(points[0].vector["summary"]) == NEW_DIM
        assert not await _exists(store, old_config.conversation_collection)

    async def test_a_conversation_write_creates_its_collection_at_the_models_size(self, store, old_config) -> None:
        """No startup step created it: the write sizes raw/summary from the vectors it just embedded."""
        assert not await _exists(store, old_config.conversation_collection)
        exchange = ConversationMemory(
            content="Discussed the rollout plan",
            raw_exchange="User: how do we roll out?\nAI: canary first, then 50%.",
            user_id="u1",
            scope=scope_of("researcher"),
        )

        await store_conversations_batch([exchange], store, old_config, Embedder(OLD_DIM), None)

        assert await _exists(store, old_config.conversation_collection)
        info = await store.get_collection_info(old_config.conversation_collection)
        # Named-vector collections report no single size, so assert through a real read instead.
        assert info is None
        points = await store._with_retry(  # type: ignore[attr-defined]
            store._client.retrieve,  # type: ignore[attr-defined]
            collection_name=old_config.conversation_collection,
            ids=[point_id_for(exchange.id)],
            with_payload=True,
            with_vectors=True,
        )
        assert len(points) == 1
        assert len(points[0].vector["raw"]) == OLD_DIM
        assert len(points[0].vector["summary"]) == OLD_DIM
