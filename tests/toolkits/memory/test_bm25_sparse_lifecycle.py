"""BM25 sparse-index lifecycle tests — scheduling, backfill paging, search edges.

Covers the wrapper's fail-open write interception for delete and
delete_by_filter (including the debug-level "missing collection" path),
one-shot backfill scheduling with suppression and task-failure logging,
multi-page scroll backfill, missing-collection skip, search boundary
conditions (empty query, sparse-store failure degradation, score
normalization, limit and namespace filter forwarding), dense-surface
pass-through delegation, and factory edge cases — all against an
in-memory lifecycle stub (no embedded qdrant, no IO).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import (
    BM25SparseIndexStore,
    _log_task_failure,
    wrap_with_bm25_sparse_index,
)
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.vector import FilterDict, VectorDocument
from myrm_agent_harness.toolkits.vector.base import SearchResult, SparsePoint

logging.getLogger("myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index")


CONFIG = MemoryConfig(embedding_model="test-model", collection_prefix="bml")


def make_doc(content: str, created_at: datetime) -> VectorDocument:
    """Build a dense-path document with the payload keys converters need."""
    return VectorDocument(
        id=str(uuid4()),
        content=content,
        vector=[0.1] * 8,
        metadata={"user_id": "u1", "memory_type": "semantic"},
        created_at=created_at,
        updated_at=created_at,
    )


class _LifecycleStub:
    """Full-protocol backend double with controllable failure switches.

    Records every call (dense surface, sparse hooks, scroll offsets) so the
    wrapper's interception, delegation, and paging behavior stays assertable
    without a real vector backend.
    """

    def __init__(
        self,
        *,
        existing: set[str] | None = None,
        sparse_delete_error: Exception | None = None,
        sparse_filter_delete_error: Exception | None = None,
        sparse_search_error: Exception | None = None,
        scroll_error: Exception | None = None,
    ) -> None:
        self.existing: set[str] = (
            existing
            if existing is not None
            else {
                CONFIG.semantic_collection,
                CONFIG.episodic_collection,
            }
        )
        self.pages: dict[str, list[list[VectorDocument]]] = {}
        self.sparse_delete_error = sparse_delete_error
        self.sparse_filter_delete_error = sparse_filter_delete_error
        self.sparse_search_error = sparse_search_error
        self.scroll_error = scroll_error

        self.calls: list[tuple[str, str]] = []
        self.ensure_calls: list[str] = []
        self.sparse_upsert_batches: list[tuple[str, int]] = []
        self.sparse_deleted_ids: list[str] = []
        self.sparse_filter_deletes: list[str] = []
        self.sparse_search_calls: list[dict[str, object]] = []
        self.scroll_offsets: list[str | None] = []
        # Per-collection results: a real backend answers each sparse collection
        # independently, so hits are keyed the same way here.
        self.sparse_hits_by_collection: dict[str, list[SearchResult]] = {}

    # ── dense surface ────────────────────────────────────────────────

    async def upsert(self, collection: str, documents: list[VectorDocument]) -> list[str]:
        self.calls.append(("upsert", collection))
        return [d.id for d in documents]

    async def delete(self, collection: str, ids: list[str]) -> int:
        if collection.endswith("_bm25"):
            if self.sparse_delete_error is not None:
                raise self.sparse_delete_error
            self.sparse_deleted_ids.extend(ids)
            return len(ids)
        self.calls.append(("delete", collection))
        return len(ids)

    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int:
        if collection.endswith("_bm25"):
            if self.sparse_filter_delete_error is not None:
                raise self.sparse_filter_delete_error
            self.sparse_filter_deletes.append(collection)
            return 1
        self.calls.append(("filter_delete", collection))
        return 1

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[object]:
        self.calls.append(("search", collection))
        return []

    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        self.calls.append(("get", collection))
        return []

    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
        order_by: tuple[str, str] | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        self.calls.append(("scroll", collection))
        self.scroll_offsets.append(offset)
        if self.scroll_error is not None:
            raise self.scroll_error
        pages = self.pages.get(collection, [[]])
        index = 0 if offset is None else int(offset)
        page = pages[index] if index < len(pages) else []
        next_index = index + 1
        cursor = str(next_index) if next_index < len(pages) else None
        return page, cursor

    async def ensure_collection(self, name: str, dimension: int, *, distance: str = "cosine") -> None:
        self.calls.append(("ensure_collection", name))

    async def create_collection(self, name: str, dimension: int, *, distance: str = "cosine") -> None:
        self.calls.append(("create_collection", name))

    async def collection_exists(self, name: str) -> bool:
        self.calls.append(("exists", name))
        return name in self.existing or name in self.pages

    async def count(self, collection: str, filters: FilterDict | None = None) -> int:
        self.calls.append(("count", collection))
        return 0

    async def health_check(self) -> bool:
        self.calls.append(("health", ""))
        return True

    async def close(self) -> None:
        self.calls.append(("close", ""))

    @property
    def is_persistent(self) -> bool:
        return True

    # ── sparse hooks ────────────────────────────────────────────────

    async def ensure_sparse_collection(self, name: str) -> bool:
        self.ensure_calls.append(name)
        return True

    async def upsert_sparse(self, collection: str, points: Sequence[SparsePoint]) -> list[str]:
        self.sparse_upsert_batches.append((collection, len(points)))
        return [p.id for p in points]

    async def search_sparse(
        self,
        collection: str,
        indices: list[int],
        values: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[object]:
        if self.sparse_search_error is not None:
            raise self.sparse_search_error
        self.sparse_search_calls.append({"collection": collection, "limit": limit, "filters": filters})
        return list(self.sparse_hits_by_collection.get(collection, []))


def warm(stub: _LifecycleStub) -> BM25SparseIndexStore:
    """Build a wrapper with the sparse channel already warmed."""
    wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]
    wrapped._sparse_ready = True
    return wrapped


# ── Write interception (fail-open sparse sync) ─────────────────────


class TestWriteInterception:
    @pytest.mark.asyncio
    async def test_delete_mirrors_into_sparse_collection(self) -> None:
        stub = _LifecycleStub()
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        deleted = await wrapped.delete(CONFIG.semantic_collection, ["d1", "d2"])

        assert deleted == 2
        assert stub.sparse_deleted_ids == ["d1", "d2"]

    @pytest.mark.asyncio
    async def test_delete_sparse_failure_fails_open_with_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        stub = _LifecycleStub(sparse_delete_error=RuntimeError("sparse store down"))
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        with caplog.at_level(logging.WARNING):
            deleted = await wrapped.delete(CONFIG.semantic_collection, ["d1"])

        # Dense delete result untouched; the mirror failure only warns.
        assert deleted == 1
        assert any("delete sync failed" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_missing_sparse_collection_logs_debug_not_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        stub = _LifecycleStub(sparse_delete_error=RuntimeError("Collection `x_bm25` not found!"))
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        with caplog.at_level(logging.DEBUG):
            deleted = await wrapped.delete(CONFIG.semantic_collection, ["d1"])

        assert deleted == 1
        assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
        assert any("mirror absent" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_delete_by_filter_mirrors_into_sparse_collection(self) -> None:
        stub = _LifecycleStub()
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        deleted = await wrapped.delete_by_filter(CONFIG.semantic_collection, {"archived": True})

        assert deleted == 1
        assert len(stub.sparse_filter_deletes) == 1
        assert stub.sparse_filter_deletes[0].endswith("_bm25")

    @pytest.mark.asyncio
    async def test_delete_by_filter_sparse_failure_fails_open(self, caplog: pytest.LogCaptureFixture) -> None:
        stub = _LifecycleStub(sparse_filter_delete_error=RuntimeError("sparse filter down"))
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        with caplog.at_level(logging.WARNING):
            deleted = await wrapped.delete_by_filter(CONFIG.semantic_collection, {"archived": True})

        assert deleted == 1
        assert any("filter-delete sync failed" in r.message for r in caplog.records)


# ── Backfill lifecycle ──────────────────────────────────────────────


class TestBackfillLifecycle:
    @pytest.mark.asyncio
    async def test_backfill_skips_absent_collections_and_warms_empty(self) -> None:
        stub = _LifecycleStub(existing=set())
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        total = await wrapped.bm25_backfill(CONFIG)

        # Nothing to index: skip both collections, but an empty index counts
        # as warmed — later queries take the sparse path instead of rescrolling.
        assert total == 0
        assert wrapped._sparse_ready is True
        assert stub.ensure_calls == []
        assert [c for op, c in stub.calls if op == "scroll"] == []

    @pytest.mark.asyncio
    async def test_backfill_paginates_multi_page_scroll(self) -> None:
        now = datetime.now(UTC)
        stub = _LifecycleStub()
        stub.pages[CONFIG.semantic_collection] = [
            [make_doc("alpha", now), make_doc("beta", now), make_doc("gamma", now)],
            [make_doc("delta", now), make_doc("epsilon", now)],
        ]
        stub.pages[CONFIG.episodic_collection] = [[make_doc("zeta", now)]]
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        total = await wrapped.bm25_backfill(CONFIG)

        assert total == 6
        # Three sparse batches: two semantic pages + one episodic page.
        assert stub.sparse_upsert_batches == [
            (f"{CONFIG.semantic_collection}_bm25", 3),
            (f"{CONFIG.semantic_collection}_bm25", 2),
            (f"{CONFIG.episodic_collection}_bm25", 1),
        ]
        # Cursor chaining: page 0 (no offset) → page 1 (offset "1") → done.
        assert stub.scroll_offsets == [None, "1", None]
        assert wrapped._sparse_ready is True

    @pytest.mark.asyncio
    async def test_backfill_is_idempotent_on_rerun(self) -> None:
        now = datetime.now(UTC)
        stub = _LifecycleStub()
        stub.pages[CONFIG.semantic_collection] = [[make_doc("alpha", now), make_doc("beta", now)]]
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        first = await wrapped.bm25_backfill(CONFIG)
        second = await wrapped.bm25_backfill(CONFIG)

        # Re-running mirrors again per-point (idempotent replace): a partially
        # failed rerun cannot double-count or duplicate points.
        assert first == second == 2
        assert wrapped._sparse_ready is True

    @pytest.mark.asyncio
    async def test_backfill_scroll_failure_returns_zero_and_stays_cold(self, caplog: pytest.LogCaptureFixture) -> None:
        stub = _LifecycleStub(scroll_error=RuntimeError("scroll backend down"))
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        with caplog.at_level(logging.WARNING):
            total = await wrapped.bm25_backfill(CONFIG)

        assert total == 0
        # Cold on failure: queries keep the legacy corpus-scroll path.
        assert wrapped._sparse_ready is False
        assert any("backfill failed" in r.message for r in caplog.records)


# ── One-shot scheduling ─────────────────────────────────────────────


class TestBackfillScheduling:
    @pytest.mark.asyncio
    async def test_schedule_backfill_once_suppresses_reschedules(self) -> None:
        stub = _LifecycleStub()
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        # Second schedule must be suppressed: one warmup per process. A
        # rescheduling bug would duplicate both mirror-collection ensures.
        wrapped._schedule_backfill_once(CONFIG)
        wrapped._schedule_backfill_once(CONFIG)
        await asyncio.sleep(0.05)  # let the background task finish

        assert stub.ensure_calls == [
            f"{CONFIG.semantic_collection}_bm25",
            f"{CONFIG.episodic_collection}_bm25",
        ]

    def test_log_task_failure_silent_on_cancelled_task(self, caplog: pytest.LogCaptureFixture) -> None:
        async def noop() -> None:
            return None

        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(noop())
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                loop.run_until_complete(task)
            with caplog.at_level(logging.WARNING):
                _log_task_failure(task)  # must not raise inside the callback
        finally:
            loop.close()
        assert caplog.records == []

    def test_log_task_failure_warns_on_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        async def boom() -> None:
            raise RuntimeError("backfill exploded")

        loop = asyncio.new_event_loop()
        try:
            task = loop.create_task(boom())
            with contextlib.suppress(RuntimeError):
                loop.run_until_complete(task)
            with caplog.at_level(logging.WARNING):
                _log_task_failure(task)
        finally:
            loop.close()
        assert any("backfill task failed" in r.message for r in caplog.records)


# ── Search edges ────────────────────────────────────────────────────


class TestSearchEdges:
    @pytest.mark.asyncio
    async def test_bm25_search_empty_query_returns_none(self) -> None:
        wrapped = warm(_LifecycleStub())
        assert await wrapped.bm25_search("", CONFIG) is None

    @pytest.mark.asyncio
    async def test_bm25_search_degrades_to_none_when_sparse_store_down(self, caplog: pytest.LogCaptureFixture) -> None:
        stub = _LifecycleStub(sparse_search_error=RuntimeError("sparse query down"))
        wrapped = warm(stub)

        with caplog.at_level(logging.WARNING):
            hits = await wrapped.bm25_search("litellm", CONFIG)

        assert hits is None  # caller falls back to the legacy corpus path
        assert any("degraded" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_bm25_search_normalizes_scores(self) -> None:
        now = datetime.now(UTC)
        stub = _LifecycleStub()
        stub.sparse_hits_by_collection[f"{CONFIG.semantic_collection}_bm25"] = [
            SearchResult(document=make_doc("alpha litellm", now), score=4.0),
            SearchResult(document=make_doc("beta litellm", now), score=2.0),
            SearchResult(document=make_doc("gamma litellm", now), score=1.0),
        ]
        wrapped = warm(stub)

        hits = await wrapped.bm25_search("litellm", CONFIG)
        assert hits is not None

        assert [h.score for h in hits] == [1.0, 0.5, 0.25]
        assert hits[0].memory.content == "alpha litellm"

    @pytest.mark.asyncio
    async def test_bm25_search_flat_normalizer_when_top_score_nonpositive(self) -> None:
        now = datetime.now(UTC)
        stub = _LifecycleStub()
        stub.sparse_hits_by_collection[f"{CONFIG.semantic_collection}_bm25"] = [
            SearchResult(document=make_doc("alpha litellm", now), score=0.0),
            SearchResult(document=make_doc("beta litellm", now), score=0.0),
        ]
        wrapped = warm(stub)

        hits = await wrapped.bm25_search("litellm", CONFIG)
        assert hits is not None

        # top score 0 → normalizer 1.0 → zero scores survive as 0.0, not div-by-zero.
        assert [h.score for h in hits] == [0.0, 0.0]

    @pytest.mark.asyncio
    async def test_bm25_search_forwards_limit_and_namespace_filters(self) -> None:
        stub = _LifecycleStub()
        wrapped = warm(stub)

        await wrapped.bm25_search("litellm", CONFIG, limit=2, namespaces=["work"])

        call = stub.sparse_search_calls[0]
        assert call["limit"] == 2
        filters = call["filters"]
        assert isinstance(filters, dict)
        assert filters["primary_namespace"] == ["work"]
        assert filters["archived"] == {"not": True}


# ── Dense-surface pass-through ──────────────────────────────────────


class TestPassthrough:
    @pytest.mark.asyncio
    async def test_dense_surface_delegates_to_inner(self) -> None:
        stub = _LifecycleStub()
        wrapped = BM25SparseIndexStore(stub)  # type: ignore[arg-type]

        await wrapped.search(CONFIG.semantic_collection, [0.1] * 8, limit=3)
        await wrapped.get(CONFIG.semantic_collection, ["d1"])
        await wrapped.scroll(CONFIG.semantic_collection, limit=5)
        await wrapped.ensure_collection("fresh", 8)
        await wrapped.create_collection("created", 8)
        assert await wrapped.collection_exists(CONFIG.semantic_collection) is True
        assert await wrapped.count(CONFIG.semantic_collection) == 0
        assert await wrapped.health_check() is True
        assert wrapped.is_persistent is True
        await wrapped.close()

        assert stub.calls == [
            ("search", CONFIG.semantic_collection),
            ("get", CONFIG.semantic_collection),
            ("scroll", CONFIG.semantic_collection),
            ("ensure_collection", "fresh"),
            ("create_collection", "created"),
            ("exists", CONFIG.semantic_collection),
            ("count", CONFIG.semantic_collection),
            ("health", ""),
            ("close", ""),
        ]


# ── Factory edges ───────────────────────────────────────────────────


class TestFactoryEdges:
    def test_factory_returns_none_for_none_backend(self) -> None:
        assert wrap_with_bm25_sparse_index(None) is None

    def test_factory_rewrap_is_identity(self) -> None:
        wrapped = BM25SparseIndexStore(_LifecycleStub())  # type: ignore[arg-type]
        assert wrap_with_bm25_sparse_index(wrapped) is wrapped
