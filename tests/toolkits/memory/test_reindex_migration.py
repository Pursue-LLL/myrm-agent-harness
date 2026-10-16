"""Embedding-model switch migration against a real embedded Qdrant.

Mock-store tests cannot prove that a migrated memory is still the *same* memory
(id, owner scope, pin, tags, timestamps) and that its vector really comes from the
new model, so every scenario here drives ``MemoryManager.reindex_from_orphans``
over real collections of two different embedding dimensions.
"""

from __future__ import annotations

import asyncio
import math
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio

from myrm_agent_harness.toolkits.memory._internal.storage import (
    store_conversations_batch,
    store_episodics_batch,
    store_semantics_batch,
)
from myrm_agent_harness.toolkits.memory._manager.reindex import _BATCH_SIZE
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.types import (
    ConversationMemory,
    EpisodicMemory,
    MemoryScope,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument, VectorStore
from myrm_agent_harness.toolkits.vector.qdrant.factory import (
    clear_embedded_stores,
    create_embedded_store,
)
from myrm_agent_harness.toolkits.vector.qdrant.filters import point_id_for

OLD_DIM = 8
NEW_DIM = 12
CREATED_AT = datetime(2025, 3, 1, 8, 30, tzinfo=UTC)


class _Embedder:
    """Deterministic embedder whose vector length identifies the model that produced it."""

    def __init__(self, dim: int, *, fail_marker: str | None = None) -> None:
        self.dimension = dim
        self.embedded_texts: list[str] = []
        self.batch_sizes: list[int] = []
        self._fail_marker = fail_marker

    def _vector(self, text: str) -> list[float]:
        return [float(len(text) % 5 + 1)] + [0.5] * (self.dimension - 1)

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if self._fail_marker is not None and any(self._fail_marker in t for t in texts):
            raise RuntimeError("embedding service unavailable")
        self.batch_sizes.append(len(texts))
        self.embedded_texts.extend(texts)
        return [self._vector(t) for t in texts]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def store() -> AsyncIterator[VectorStore]:
    """One embedded Qdrant for the module (cold start dominates); tests isolate by collection prefix."""
    await clear_embedded_stores()
    embedded = await create_embedded_store(path=":memory:")
    try:
        yield embedded
    finally:
        await embedded.close()
        await clear_embedded_stores()


@pytest.fixture
def prefix() -> str:
    return f"reidx{uuid4().hex[:8]}"


@pytest.fixture
def old_config(prefix: str) -> MemoryConfig:
    return MemoryConfig(embedding_model="old-model", collection_prefix=prefix, blob_storage_enabled=False)


@pytest.fixture
def new_config(prefix: str) -> MemoryConfig:
    return MemoryConfig(embedding_model="new-model", collection_prefix=prefix, blob_storage_enabled=False)


def _unit(vector: list[float]) -> list[float]:
    """Cosine collections store unit vectors, so compare direction rather than raw values."""
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector]


def _scope(agent: str) -> MemoryScope:
    return MemoryScope(primary_namespace=f"agent:{agent}", namespaces=["global", f"agent:{agent}"], agent_id=agent)


def _semantic(content: str, *, agent: str = "default", **fields: object) -> SemanticMemory:
    return SemanticMemory(content=content, user_id="u1", scope=_scope(agent), created_at=CREATED_AT, **fields)  # type: ignore[arg-type]


def _episodic(content: str, *, agent: str = "default", **fields: object) -> EpisodicMemory:
    return EpisodicMemory(content=content, user_id="u1", scope=_scope(agent), created_at=CREATED_AT, **fields)  # type: ignore[arg-type]


def _manager(
    store: VectorStore, config: MemoryConfig, embedder: _Embedder, *, graph: AsyncMock | None = None
) -> MemoryManager:
    return MemoryManager(config, user_id="u1", vector=store, embedding=embedder, graph=graph)  # type: ignore[arg-type]


async def _scroll_all(store: VectorStore, collection: str) -> dict[str, VectorDocument]:
    documents: dict[str, VectorDocument] = {}
    cursor: str | None = None
    while True:
        page, cursor = await store.scroll(collection, limit=_BATCH_SIZE, offset=cursor)
        documents.update({doc.id: doc for doc in page})
        if cursor is None:
            return documents


async def _create_conversation_collection(store: VectorStore, name: str, dim: int) -> None:
    """Mirror ``memory.setup``: the conversation collection carries ``raw`` + ``summary`` named vectors."""
    from qdrant_client.models import Distance, VectorParams

    vectors_config = {
        "raw": VectorParams(size=dim, distance=Distance.COSINE),
        "summary": VectorParams(size=dim, distance=Distance.COSINE),
    }
    await asyncio.to_thread(store._client.create_collection, collection_name=name, vectors_config=vectors_config)  # type: ignore[attr-defined]


def _fail_on(
    monkeypatch: pytest.MonkeyPatch, store: VectorStore, method: str, collection: str, *, after_calls: int = 0
) -> None:
    """Make ``store.<method>`` raise for ``collection`` once ``after_calls`` calls succeeded (undone after the test)."""
    original: Callable[..., Awaitable[object]] = getattr(store, method)
    calls = 0

    async def flaky(name: str, *args: object, **kwargs: object) -> object:
        nonlocal calls
        if name == collection:
            calls += 1
            if calls > after_calls:
                raise RuntimeError(f"{method} failed")
        return await original(name, *args, **kwargs)

    monkeypatch.setattr(store, method, flaky)


class TestSemanticMigration:
    async def test_migrated_memories_keep_identity_scope_and_state(self, store, old_config, new_config) -> None:
        default_agent = _semantic("User prefers dark mode", importance=0.9, tags=["UI", "Theme"])
        researcher = _semantic("Researcher cites arXiv ids", agent="researcher", importance=0.7)
        pinned = _semantic("Never deploy on Friday", pinned=True, access_count=4, user_rating=0.8)
        old_embedder = _Embedder(OLD_DIM)
        await store_semantics_batch([default_agent, researcher, pinned], store, old_config, old_embedder, None)

        new_embedder = _Embedder(NEW_DIM)
        result = await _manager(store, new_config, new_embedder).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (3, 0, 0)
        migrated = await _scroll_all(store, new_config.semantic_collection)
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
            assert doc.vector == pytest.approx(_unit(new_embedder._vector(original.content)))
        assert migrated[default_agent.id].metadata["tags"] == ["ui", "theme"]

    async def test_vectors_come_from_new_model_not_the_old_collection(self, store, old_config, new_config) -> None:
        memory = _semantic("Prefers tabs over spaces")
        await store_semantics_batch([memory], store, old_config, _Embedder(OLD_DIM), None)

        await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans()

        migrated = await _scroll_all(store, new_config.semantic_collection)
        assert len(migrated[memory.id].vector or []) == NEW_DIM
        old_docs = await _scroll_all(store, old_config.semantic_collection)
        assert len(old_docs[memory.id].vector or []) == OLD_DIM, "old collection stays untouched as a safety net"

    async def test_rerun_skips_memories_already_present_without_embedding_again(
        self, store, old_config, new_config
    ) -> None:
        memories = [_semantic(f"fact {index}") for index in range(3)]
        await store_semantics_batch(memories, store, old_config, _Embedder(OLD_DIM), None)
        new_embedder = _Embedder(NEW_DIM)
        manager = _manager(store, new_config, new_embedder)

        first = await manager.reindex_from_orphans()
        embedded_after_first = len(new_embedder.embedded_texts)
        second = await manager.reindex_from_orphans()

        assert (first.migrated, first.skipped, first.failed) == (3, 0, 0)
        assert (second.migrated, second.skipped, second.failed) == (0, 3, 0)
        assert len(new_embedder.embedded_texts) == embedded_after_first
        assert len(await _scroll_all(store, new_config.semantic_collection)) == 3

    async def test_migration_does_not_back_off_while_the_new_models_sparse_mirror_is_missing(
        self, store, old_config, new_config, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The new model has no ``_bm25`` mirror until its first backfill; every batch must fail open at once, not retry."""
        memories = [_semantic(f"fact {index}") for index in range(3)]
        await store_semantics_batch(memories, store, old_config, _Embedder(OLD_DIM), None)

        with caplog.at_level("WARNING"):
            result = await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (3, 0, 0)
        assert [r.message for r in caplog.records if "Retrying in" in r.message] == []

    async def test_memory_written_after_the_switch_is_never_overwritten(self, store, old_config, new_config) -> None:
        stale = _semantic("stale copy", importance=0.1)
        await store_semantics_batch([stale], store, old_config, _Embedder(OLD_DIM), None)
        fresh = stale.model_copy(update={"content": "edited after the switch", "importance": 0.95})
        await store_semantics_batch([fresh], store, new_config, _Embedder(NEW_DIM), None)

        result = await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 1, 0)
        kept = (await _scroll_all(store, new_config.semantic_collection))[stale.id]
        assert kept.content == "edited after the switch"
        assert kept.metadata["importance"] == 0.95

    async def test_pagination_embeds_in_batches_and_counts_every_memory(self, store, old_config, new_config) -> None:
        total = _BATCH_SIZE * 2 + 30
        memories = [_semantic(f"fact {index}") for index in range(total)]
        await store_semantics_batch(memories, store, old_config, _Embedder(OLD_DIM), None)
        new_embedder = _Embedder(NEW_DIM)

        result = await _manager(store, new_config, new_embedder).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (total, 0, 0)
        assert new_embedder.batch_sizes == [_BATCH_SIZE, _BATCH_SIZE, 30]
        assert len(await _scroll_all(store, new_config.semantic_collection)) == total

    async def test_blank_memory_is_skipped_not_embedded(self, store, old_config, new_config) -> None:
        await store.upsert(
            old_config.semantic_collection,
            [VectorDocument(id="blank-1", content="  ", vector=[0.1] * OLD_DIM, metadata={"user_id": "u1"})],
        )
        new_embedder = _Embedder(NEW_DIM)

        result = await _manager(store, new_config, new_embedder).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 1, 0)
        assert new_embedder.embedded_texts == []

    async def test_no_orphans_is_a_clean_noop(self, store, new_config) -> None:
        result = await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 0, 0)

    async def test_progress_reports_start_running_total_and_completion(self, store, old_config, new_config) -> None:
        memories = [_semantic(f"fact {index}") for index in range(_BATCH_SIZE + 5)]
        await store_semantics_batch(memories, store, old_config, _Embedder(OLD_DIM), None)
        events: list[tuple[int, int, str]] = []

        await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans(
            progress_cb=lambda done, total, phase: events.append((done, total, phase))
        )

        total = _BATCH_SIZE + 5
        assert events[0] == (0, total, "starting")
        assert [e[0] for e in events] == sorted(e[0] for e in events)
        assert (_BATCH_SIZE, total, "migrating") in events
        assert events[-1] == (total, total, "completed")


class TestOrphanDetection:
    async def test_estimate_lists_previous_model_collections_behind_the_bm25_mirror(
        self, store, old_config, new_config
    ) -> None:
        await store_semantics_batch([_semantic("a"), _semantic("b")], store, old_config, _Embedder(OLD_DIM), None)
        await store_episodics_batch([_episodic("c")], store, old_config, _Embedder(OLD_DIM), None)
        await store_semantics_batch([_semantic("current")], store, new_config, _Embedder(NEW_DIM), None)

        estimate = await _manager(store, new_config, _Embedder(NEW_DIM)).estimate_reindex()

        assert estimate.total_memories == 3
        found = {
            (o.collection_name, o.memory_type, o.old_model_suffix, o.document_count)
            for o in estimate.orphan_collections
        }
        assert found == {
            (old_config.semantic_collection, "semantic", "old-model", 2),
            (old_config.episodic_collection, "episodic", "old-model", 1),
        }


class TestFailureAccounting:
    async def test_embedding_failure_is_failed_and_other_types_still_migrate(
        self, store, old_config, new_config
    ) -> None:
        semantic = _semantic("migrates fine")
        poisoned = _episodic("embedding provider rejects POISON")
        await store_semantics_batch([semantic], store, old_config, _Embedder(OLD_DIM), None)
        await store_episodics_batch([poisoned], store, old_config, _Embedder(OLD_DIM), None)

        manager = _manager(store, new_config, _Embedder(NEW_DIM, fail_marker="POISON"))
        result = await manager.reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (1, 0, 1)
        assert set(await _scroll_all(store, new_config.semantic_collection)) == {semantic.id}
        assert not await store.collection_exists(new_config.episodic_collection)

    async def test_write_failure_is_failed_not_skipped(self, store, old_config, new_config, monkeypatch) -> None:
        memories = [_semantic(f"fact {index}") for index in range(4)]
        await store_semantics_batch(memories, store, old_config, _Embedder(OLD_DIM), None)
        _fail_on(monkeypatch, store, "upsert", new_config.semantic_collection)

        result = await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (0, 0, 4)

    async def test_read_failure_midway_counts_unread_remainder_as_failed(
        self, store, old_config, new_config, monkeypatch
    ) -> None:
        total = _BATCH_SIZE * 2 + 30
        memories = [_semantic(f"fact {index}") for index in range(total)]
        await store_semantics_batch(memories, store, old_config, _Embedder(OLD_DIM), None)
        _fail_on(monkeypatch, store, "scroll", old_config.semantic_collection, after_calls=1)

        result = await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (_BATCH_SIZE, 0, total - _BATCH_SIZE)

    async def test_failed_memories_migrate_on_the_next_run(self, store, old_config, new_config) -> None:
        memories = [_semantic(f"fact {index}") for index in range(3)]
        await store_semantics_batch(memories, store, old_config, _Embedder(OLD_DIM), None)

        broken = await _manager(store, new_config, _Embedder(NEW_DIM, fail_marker="fact")).reindex_from_orphans()
        healed = await _manager(store, new_config, _Embedder(NEW_DIM)).reindex_from_orphans()

        assert (broken.migrated, broken.failed) == (0, 3)
        assert (healed.migrated, healed.skipped, healed.failed) == (3, 0, 0)


class TestEpisodicMigration:
    async def test_episodic_keeps_identity_scope_and_does_not_duplicate_graph_nodes(
        self, store, old_config, new_config
    ) -> None:
        episode = _episodic(
            "Deployed the billing service", agent="researcher", related_entities=["billing"], importance=0.8
        )
        await store_episodics_batch([episode], store, old_config, _Embedder(OLD_DIM), None)
        graph = AsyncMock()
        new_embedder = _Embedder(NEW_DIM)

        result = await _manager(store, new_config, new_embedder, graph=graph).reindex_from_orphans()

        assert (result.migrated, result.skipped, result.failed) == (1, 0, 0)
        doc = (await _scroll_all(store, new_config.episodic_collection))[episode.id]
        assert doc.content == episode.content
        assert doc.metadata["primary_namespace"] == "agent:researcher"
        assert doc.metadata["importance"] == 0.8
        assert doc.created_at == CREATED_AT
        assert doc.vector == pytest.approx(_unit(new_embedder._vector(episode.content)))
        graph.create_node.assert_not_called()
        graph.create_relationship.assert_not_called()


class TestConversationMigration:
    async def test_conversation_re_embeds_both_vectors_and_keeps_payload(self, store, old_config, new_config) -> None:
        await _create_conversation_collection(store, old_config.conversation_collection, OLD_DIM)
        await _create_conversation_collection(store, new_config.conversation_collection, NEW_DIM)
        exchange = ConversationMemory(
            content="Discussed the rollout plan",
            raw_exchange="User: how do we roll out?\nAI: canary first, then 50%.",
            user_id="u1",
            scope=_scope("researcher"),
            created_at=CREATED_AT,
            timestamp=CREATED_AT + timedelta(minutes=5),
            source_chat_id="chat-1",
            importance=0.7,
        )
        await store_conversations_batch([exchange], store, old_config, _Embedder(OLD_DIM), None)
        new_embedder = _Embedder(NEW_DIM)

        result = await _manager(store, new_config, new_embedder).reindex_from_orphans()

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
