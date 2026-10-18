"""BM25 Sparse Index — persistent, incrementally-maintained inverted index.

[INPUT]
- memory.protocols.vector::{FilterDict, VectorDocument, VectorSearchResult, VectorStoreProtocol} (POS: vector protocol)
- memory._internal.bm25_sparse_encoding::{bm25_collection_for, doc_to_sparse_point} (POS: sparse encoding)
- memory._internal.bm25_sparse_query::run_bm25_search (POS: sparse query pipeline)
- toolkits.vector.qdrant.sparse::QdrantSparseMixin (POS: sparse-capable backend)

[OUTPUT]
- BM25SparseIndexStore: VectorStoreProtocol wrapper (sparse-capable backends
  only) that mirrors every upsert/delete into a ``{collection}_bm25`` sparse
  collection and serves BM25 queries from it
- wrap_with_bm25_sparse_index: factory deciding capability at assembly time;
  legacy backends stay unwrapped on the corpus-scroll fallback path
- unwrap_sparse_mirror: backend beneath the wrapper, for the named-vector
  conversation collection the mirror does not cover

[POS]
Replaces the per-query full-corpus scroll + BM25Okapi rebuild (24x build/query
cost ratio, silent recall loss past ``bm25_max_corpus_size``) with a persisted
sparse index. This module owns the mirror's lifecycle — write interception,
one-shot backfill, and sparse-only routing for embeddings-less deployments —
while encoding and query execution live in the sibling modules. Sparse sync is
fail-open — a broken index never blocks dense writes, the same guarantee graph
indexing already follows.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_encoding import (
    bm25_collection_for,
    doc_to_sparse_point,
)
from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_query import run_bm25_search
from myrm_agent_harness.toolkits.memory.protocols.vector import (
    FilterDict,
    VectorDocument,
    VectorSearchResult,
    VectorStoreProtocol,
)
from myrm_agent_harness.toolkits.memory.types import MemorySearchResult
from myrm_agent_harness.toolkits.vector.qdrant.sparse import QdrantSparseMixin

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


def _log_task_failure(task: asyncio.Task[object]) -> None:
    """Surface a dead backfill task without raising inside the loop callback."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("BM25 sparse backfill task failed: %s", exc)


class BM25SparseIndexStore:
    """VectorStoreProtocol wrapper maintaining a persistent BM25 sparse mirror.

    Only sparse-capable backends (qdrant with the sparse mixin) are wrapped —
    ``wrap_with_bm25_sparse_index`` decides capability at assembly time, so
    this class can assume the sparse hooks exist. Every upsert/delete/
    delete_by_filter is mirrored (fail-open) into ``{collection}_bm25`` once
    the index is warm; ``bm25_backfill`` warms it from the dense collections;
    ``bm25_search`` serves BM25 queries from it.
    """

    def __init__(self, inner: VectorStoreProtocol, *, sparse_authoritative: bool = False) -> None:
        self._inner = inner
        self._sparse_ready = False
        self._backfill_scheduled = False
        # Embeddings-less deployments keep the sparse mirror as the only
        # store: dense reads/writes have no collection to reach, so they are
        # routed to the mirror here once and every caller stays unchanged.
        self._sparse_authoritative = sparse_authoritative

    def _schedule_backfill_once(self, config: MemoryConfig) -> None:
        """Kick off the one-time warmup from the first BM25 query.

        Called from async query paths only, so a running loop is guaranteed;
        a sync manager construction never touches asyncio.create_task here.
        Re-scheduling is suppressed for the process lifetime; failures log
        and leave the wrapper on the legacy corpus-scroll path.
        """
        if self._backfill_scheduled:
            return
        self._backfill_scheduled = True
        task = asyncio.get_running_loop().create_task(self._backfill_task(config))
        task.add_done_callback(_log_task_failure)

    # ── Write interception (fail-open sparse sync) ──────────────────────

    def _log_sync_failure(self, op: str, collection: str, exc: Exception) -> None:
        """Fail-open mirror logging.

        A missing sparse collection is expected before the backfill ensures
        it (debug, no operator action needed); anything else is a real sync
        failure (warning).
        """
        if "not found" in str(exc).lower():
            logger.debug("BM25 sparse mirror absent pre-backfill; skipped %s sync for %s", op, collection)
            return
        logger.warning("BM25 sparse index %s sync failed for %s (non-fatal): %s", op, collection, exc)

    async def upsert(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        if self._sparse_authoritative:
            # Embeddings-less deployments never created the dense collection;
            # the sparse mirror is the authoritative store for the write.
            return await self.upsert_sparse_only(collection, documents)
        ids = await self._inner.upsert(collection, documents)
        # Unconditional mirror attempt (no readiness gate): a write landing
        # mid-backfill must not fall through a scroll snapshot gap, and a
        # pre-backfill attempt just fails open on the missing collection.
        if documents:
            try:
                points = [doc_to_sparse_point(doc) for doc in documents]
                await self._inner.upsert_sparse(bm25_collection_for(collection), points)  # type: ignore[attr-defined]
            except Exception as exc:
                self._log_sync_failure("upsert", collection, exc)
        return ids

    async def delete(self, collection: str, ids: list[str]) -> int:
        if self._sparse_authoritative:
            return await self.delete_sparse_only(collection, ids)
        deleted = await self._inner.delete(collection, ids)
        if deleted:
            try:
                await self._inner.delete(bm25_collection_for(collection), ids)
            except Exception as exc:
                self._log_sync_failure("delete", collection, exc)
        return deleted

    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int:
        if self._sparse_authoritative:
            try:
                return await self._inner.delete_by_filter(bm25_collection_for(collection), filters)
            except Exception as exc:
                self._log_sync_failure("filter-delete", collection, exc)
                return 0
        deleted = await self._inner.delete_by_filter(collection, filters)
        if deleted:
            try:
                await self._inner.delete_by_filter(bm25_collection_for(collection), filters)
            except Exception as exc:
                self._log_sync_failure("filter-delete", collection, exc)
        return deleted

    # ── BM25 sparse lifecycle ────────────────────────────────────────────

    async def _backfill_task(self, config: MemoryConfig) -> None:
        """Guarded backfill entry for the lazily scheduled warmup task."""
        try:
            await self.bm25_backfill(config)
        except Exception as exc:
            logger.warning("BM25 sparse backfill failed (non-fatal): %s", exc)

    async def bm25_backfill(self, config: MemoryConfig) -> int:
        """Warm the sparse mirror from dense collections (idempotent replace).

        Scrolls each dense collection fully and mirrors it into the sparse
        collection; upserts are per-point replaces, so re-running only costs
        a re-write, never a duplicate. Returns the number of indexed documents.
        """
        total = 0
        for collection in (config.semantic_collection, config.episodic_collection):
            if not await self._inner.collection_exists(collection):
                continue
            sparse_name = bm25_collection_for(collection)
            try:
                await self._inner.ensure_sparse_collection(sparse_name)  # type: ignore[attr-defined]
                docs, cursor = await self._inner.scroll(collection, limit=500)
                while True:
                    if docs:
                        points = [doc_to_sparse_point(doc) for doc in docs]
                        await self._inner.upsert_sparse(sparse_name, points)  # type: ignore[attr-defined]
                        total += len(points)
                    if not cursor:
                        break
                    docs, cursor = await self._inner.scroll(collection, limit=500, offset=cursor)
            except Exception as exc:
                logger.warning("BM25 sparse backfill failed for %s (non-fatal): %s", collection, exc)
                return 0
        self._sparse_ready = True
        if total:
            logger.info("BM25 sparse backfill mirrored %d documents into persistent index", total)
        return total

    async def bm25_search(
        self,
        query: str,
        config: MemoryConfig,
        *,
        limit: int | None = None,
        namespaces: list[str] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[MemorySearchResult] | None:
        """Serve a BM25 query from the persistent sparse index.

        Returns ``None`` while the index is not yet warmed so the caller can
        fall back to the corpus-scroll path; the first call also schedules the
        one-shot backfill. Query execution lives in ``run_bm25_search``.
        """
        if not self._sparse_ready:
            # First BM25 query in an async context: warm the index in the
            # background; this query (and any racing ones) use the legacy
            # corpus-scroll path until the backfill lands.
            self._schedule_backfill_once(config)
            return None
        return await run_bm25_search(
            self._inner,
            query,
            config,
            limit=limit,
            namespaces=namespaces,
            since=since,
            until=until,
        )

    # ── Sparse-only lifecycle (embeddings-less deployments) ─────────────

    async def upsert_sparse_only(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        """Persist documents into the sparse mirror alone (dense upsert skipped).

        Used when the deployment runs without an embedding backend: the
        sparse channel becomes the authoritative store for the collection,
        so the mirror is ensured and marked ready on the first write and
        ``bm25_search`` serves these documents without a dense backfill.
        Failures propagate: this is the only store for the write.
        """
        if not documents:
            return []
        sparse_name = bm25_collection_for(collection)
        await self._inner.ensure_sparse_collection(sparse_name)  # type: ignore[attr-defined]
        points = [doc_to_sparse_point(doc) for doc in documents]
        await self._inner.upsert_sparse(sparse_name, points)  # type: ignore[attr-defined]
        self._sparse_ready = True
        return [doc.id for doc in documents]

    async def delete_sparse_only(self, collection: str, ids: list[str]) -> int:
        """Delete ids from the sparse mirror alone (dense delete skipped).

        Companion to ``upsert_sparse_only`` for embeddings-less deployments
        whose documents never reached the dense collection. Deletions stay
        fail-open like the mirror syncs: a failed delete logs and reports 0.
        """
        if not ids:
            return 0
        try:
            return await self._inner.delete(bm25_collection_for(collection), ids)
        except Exception as exc:
            self._log_sync_failure("sparse-only-delete", collection, exc)
            return 0

    async def get_sparse_only(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        """Get documents by id from the sparse mirror alone (embeddings-less reads).

        Companion to ``upsert_sparse_only``: the ownership-gated delete paths
        read the documents they are about to remove, and without embeddings
        the dense collection holds none of them. A failed read logs and
        reports an empty list, matching the mirror's fail-open posture.
        """
        if not ids:
            return []
        try:
            return await self._inner.get(bm25_collection_for(collection), ids)
        except Exception as exc:
            self._log_sync_failure("sparse-only-get", collection, exc)
            return []

    # ── Pure pass-through of the VectorStoreProtocol surface ────────────

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[VectorSearchResult]:
        return await self._inner.search(
            collection,
            query_vector,
            limit=limit,
            filters=filters,
            score_threshold=score_threshold,
        )

    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        if self._sparse_authoritative:
            return await self.get_sparse_only(collection, ids)
        return await self._inner.get(collection, ids)

    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
        order_by: tuple[str, str] | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        if self._sparse_authoritative:
            return await self._inner.scroll(
                bm25_collection_for(collection), limit=limit, offset=offset, filters=filters, order_by=order_by
            )
        return await self._inner.scroll(collection, limit=limit, offset=offset, filters=filters, order_by=order_by)

    async def ensure_collection(self, name: str, dimension: int, *, distance: str = "cosine") -> None:
        await self._inner.ensure_collection(name, dimension, distance=distance)

    async def create_collection(self, name: str, dimension: int, *, distance: str = "cosine") -> None:
        await self._inner.create_collection(name, dimension, distance=distance)

    async def create_named_vector_collection(
        self, name: str, dimension: int, *, names: Sequence[str], distance: str = "cosine"
    ) -> bool:
        return await self._inner.create_named_vector_collection(name, dimension, names=names, distance=distance)

    async def collection_exists(self, name: str) -> bool:
        return await self._inner.collection_exists(name)

    async def count(self, collection: str, filters: FilterDict | None = None) -> int:
        return await self._inner.count(collection, filters=filters)

    async def health_check(self) -> bool:
        return await self._inner.health_check()

    async def close(self) -> None:
        await self._inner.close()

    @property
    def is_persistent(self) -> bool:
        return self._inner.is_persistent


def wrap_with_bm25_sparse_index(
    vector: VectorStoreProtocol | None,
    *,
    sparse_authoritative: bool = False,
) -> VectorStoreProtocol | None:
    """Wrap a sparse-capable backend with the BM25 sparse mirror.

    Capability is decided here and exactly once, by exact class membership —
    qdrant with the sparse mixin is the only sparse backend, and an isinstance
    check (unlike hasattr duck-probing) cannot be spoofed by mock stand-ins,
    so tests keep direct attribute reach into their store.

    ``sparse_authoritative`` marks embeddings-less deployments: the dense
    collection does not exist, so reads/writes route straight to the mirror
    and every caller keeps its dense-path code unchanged.
    """
    if vector is None:
        return None
    if isinstance(vector, BM25SparseIndexStore):
        return vector
    if isinstance(vector, QdrantSparseMixin):
        return BM25SparseIndexStore(vector, sparse_authoritative=sparse_authoritative)
    return vector


def unwrap_sparse_mirror(vector: VectorStoreProtocol) -> VectorStoreProtocol:
    """Return the backend beneath the BM25 mirror (a bare store passes through).

    The mirror covers the semantic and episodic collections only. The
    conversation collection holds named vectors (raw/summary), which the
    wrapper's single-vector pass-through can neither write nor query, so its
    reads and writes address the backend directly.
    """
    return vector._inner if isinstance(vector, BM25SparseIndexStore) else vector
