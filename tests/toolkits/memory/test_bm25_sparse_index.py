"""BM25 sparse index tests — tokenization, wrapper sync, E2E on embedded Qdrant.

Covers the persistent BM25 channel end-to-end: hash tokenization, saturated
term-frequency vectors, capability decision at the factory, wrapper write
interception (fail-open), backfill warmup, sparse retrieval with time
bounds, incremental upsert/delete sync, and degradation to the legacy
corpus-scroll path before warmup or on non-sparse backends.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import (
    BM25SparseIndexStore,
    bm25_collection_for,
    content_to_sparse,
    query_to_sparse,
    token_index,
    wrap_with_bm25_sparse_index,
)
from myrm_agent_harness.toolkits.memory._internal.storage_search import search_bm25
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import FilterDict, VectorDocument
from myrm_agent_harness.toolkits.vector.base import SparsePoint


CONFIG = MemoryConfig(embedding_model="test-model", collection_prefix="bmi")


def make_doc(content: str, created_at: datetime) -> VectorDocument:
    """Build a dense-path document with the payload keys doc_to_semantic needs."""
    return VectorDocument(
        id=str(uuid4()),
        content=content,
        vector=[0.1] * 8,
        metadata={
            "user_id": "u1",
            "memory_type": "semantic",
            "archived": False,
        },
        created_at=created_at,
        updated_at=created_at,
    )


class _SparseCapableStub:
    """Hand-rolled backend stub exposing sparse capability hooks."""

    def __init__(self, *, sparse_broken: bool = False) -> None:
        self.sparse_broken = sparse_broken
        self.upsert_calls: list[str] = []
        self.sparse_upsert_calls: list[str] = []

    async def upsert(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        self.upsert_calls.append(collection)
        return [d.id for d in documents]

    async def upsert_sparse(self, collection: str, points: Sequence[SparsePoint]) -> list[str]:
        if self.sparse_broken:
            raise RuntimeError("sparse store down")
        self.sparse_upsert_calls.append(collection)
        return [p.id for p in points]

    async def search_sparse(self, *args: object, **kwargs: object) -> list[object]:
        raise RuntimeError("sparse query path not wired in stub")

    async def ensure_sparse_collection(self, name: str) -> bool:
        return True


class _ScrollOnlyStub:
    """Backend stub without any sparse capability (legacy backend)."""

    def __init__(self) -> None:
        self.scrolled: list[str] = []

    async def upsert(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        return [d.id for d in documents]

    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
        order_by: tuple[str, str] | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        self.scrolled.append(collection)
        return [], None


# ── Tokenization primitives ──────────────────────────────────────────


class TestSparseTokenization:
    def test_token_index_is_stable_and_u31(self) -> None:
        assert token_index("litellm") == token_index("litellm")
        assert token_index("litellm") != token_index("fastapi")
        assert 0 <= token_index("litellm") < 2**31

    def test_content_to_sparse_saturates_term_frequency(self) -> None:
        indices, values = content_to_sparse("gate gate gate gateway")
        freqs = dict(zip(indices, values, strict=True))
        single = 1.0 + math.log(1)
        repeated = 1.0 + math.log(3)
        assert sorted(freqs.values()) == sorted([single, repeated])

    def test_content_to_sparse_empty_text(self) -> None:
        assert content_to_sparse("") == ([], [])
        assert content_to_sparse("   ") == ([], [])

    def test_query_to_sparse_uniform_weights(self) -> None:
        indices, values = query_to_sparse("litellm gateway litellm")
        assert len(indices) == len(set(indices)) == 2
        assert values == [1.0, 1.0]

    def test_bm25_collection_name(self) -> None:
        assert bm25_collection_for("x_semantic") == "x_semantic_bm25"


# ── Wrapper degradation & interception ──────────────────────────────


class TestWrapperDegradation:
    def test_legacy_backend_passes_through_unwrapped(self) -> None:
        stub = _ScrollOnlyStub()
        wrapped = wrap_with_bm25_sparse_index(stub)  # type: ignore[arg-type]

        # Identity: legacy backends (no sparse hooks) are not wrapped at all.
        assert wrapped is stub

    @pytest.mark.asyncio
    async def test_bm25_search_returns_none_until_backfilled(self) -> None:
        wrapped = BM25SparseIndexStore(_SparseCapableStub())  # type: ignore[arg-type]

        assert await wrapped.bm25_search("litellm", CONFIG) is None

    @pytest.mark.asyncio
    async def test_fail_open_sparse_sync_does_not_block_dense_upsert(self) -> None:
        stub = _SparseCapableStub(sparse_broken=True)
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]
        wrapped._sparse_ready = True

        ids = await wrapped.upsert(CONFIG.semantic_collection, [make_doc("hello", datetime.now(UTC))])
        assert ids is not None and len(ids) == 1
        assert stub.upsert_calls == [CONFIG.semantic_collection]
        # sparse sync raised, dense upsert still succeeded

    @pytest.mark.asyncio
    async def test_search_bm25_falls_back_to_corpus_scroll_before_warm(self) -> None:
        """search_bm25 must degrade to the legacy scroll path pre-warmup."""
        stub = _ScrollOnlyStub()
        wrapped = wrap_with_bm25_sparse_index(stub)  # type: ignore[arg-type]

        results = await search_bm25("litellm", wrapped, CONFIG)  # type: ignore[arg-type]
        assert results == []
        assert set(stub.scrolled) == {CONFIG.semantic_collection, CONFIG.episodic_collection}


# ── E2E on embedded Qdrant ───────────────────────────────────────────


@pytest.mark.slow
class TestBM25SparseE2E:
    @pytest.mark.asyncio
    async def test_backfill_search_incremental_delete_time_bounds(self, tmp_path: Path) -> None:
        from myrm_agent_harness.toolkits.vector.qdrant import create_embedded_store

        store = await create_embedded_store(path=str(tmp_path / "qdrant"))
        wrapped = wrap_with_bm25_sparse_index(store)
        assert isinstance(wrapped, BM25SparseIndexStore)

        try:
            now = datetime.now(UTC)
            old = now - timedelta(days=800)
            docs = [
                make_doc("User deployed LiteLLM 1.77.2 gateway on prod cluster", old),
                make_doc("User prefers FastAPI for internal services", now),
                make_doc("unrelated note about coffee beans", now),
            ]
            await wrapped.upsert(CONFIG.semantic_collection, docs)
            await wrapped.upsert(
                CONFIG.episodic_collection,
                [make_doc("Outage postmortem litellm retry storm", now)],
            )

            backfilled = await wrapped.bm25_backfill(CONFIG)
            assert backfilled == 4

            hits = await wrapped.bm25_search("litellm", CONFIG)
            assert hits is not None
            assert len(hits) == 2
            assert {h.memory_type.value for h in hits} == {"semantic", "episodic"}
            assert all(h.score <= 1.0 for h in hits)

            # Time bounds on the sparse channel
            fresh = await wrapped.bm25_search("litellm", CONFIG, since=now - timedelta(days=30))
            assert fresh is not None
            assert [h.memory.content for h in fresh] == ["Outage postmortem litellm retry storm"]

            stale = await wrapped.bm25_search("litellm", CONFIG, until=now - timedelta(days=400))
            assert stale is not None
            assert [h.memory.content for h in stale] == [
                "User deployed LiteLLM 1.77.2 gateway on prod cluster"
            ]

            # Incremental sync after warmup
            extra = make_doc("Fresh note about pytorch training run", now)
            await wrapped.upsert(CONFIG.semantic_collection, [extra])
            fresh_hits = await wrapped.bm25_search("pytorch training", CONFIG)
            assert fresh_hits is not None
            assert [h.memory.content for h in fresh_hits] == ["Fresh note about pytorch training run"]

            # Delete sync
            await wrapped.delete(CONFIG.semantic_collection, [extra.id])
            gone = await wrapped.bm25_search("pytorch training", CONFIG)
            assert gone == []

            # search_bm25 entry point picks the sparse channel (no corpus ceiling)
            from myrm_agent_harness.toolkits.memory.metrics import get_search_metrics

            overflow_before = get_search_metrics().snapshot().degradation_corpus_overflow_count
            routed = await search_bm25("litellm", wrapped, CONFIG)
            assert routed is not None and len(routed) == 2
            assert (
                get_search_metrics().snapshot().degradation_corpus_overflow_count == overflow_before
            )
        finally:
            await wrapped.close()
