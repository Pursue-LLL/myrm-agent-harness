"""BM25 Sparse Index — persistent, incrementally-maintained inverted index.

[INPUT]
- memory.protocols.vector::{VectorStoreProtocol, VectorDocument, FilterDict} (POS: vector protocol)
- memory._internal.storage_converters::{doc_to_semantic, doc_to_episodic, _user_filter} (POS: converters)
- memory.types::{MemorySearchResult, MemoryType} (POS: memory data models)
- retriever.bm25_retrieval::preprocess_text (POS: shared CJK/latin tokenizer)

[OUTPUT]
- token_index: stable u31 token hash (zero-vocabulary, no term dictionary)
- content_to_sparse / query_to_sparse: token stream -> (indices, values)
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
sparse index: tokens are hashed (crc32 & 0x7FFFFFFF), term frequency saturates
via ``1 + ln(tf)``, and IDF weighting happens server-side (Qdrant sparse
scoring). Sparse sync is fail-open — a broken index never blocks dense writes,
the same guarantee graph indexing already follows.
"""

from __future__ import annotations

import asyncio
import logging
import math
import zlib
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.protocols.vector import (
    FilterDict,
    VectorDocument,
    VectorSearchResult,
    VectorStoreProtocol,
)
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.vector.base import SparsePoint
from myrm_agent_harness.toolkits.vector.qdrant.sparse import QdrantSparseMixin

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig

logger = logging.getLogger(__name__)

BM25_COLLECTION_SUFFIX = "_bm25"


def _log_task_failure(task: asyncio.Task[object]) -> None:
    """Surface a dead backfill task without raising inside the loop callback."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.warning("BM25 sparse backfill task failed: %s", exc)


def token_index(token: str) -> int:
    """Stable u31 token hash — zero vocabulary, no term dictionary to persist.

    crc32 over the utf-8 token keeps hashing allocation-light; collisions merge
    two rare terms' frequencies, a bounded-quality tradeoff standard for
    hash-based sparse retrieval.
    """
    return zlib.crc32(token.encode("utf-8")) & 0x7FFFFFFF


def content_to_sparse(text: str) -> tuple[list[int], list[float]]:
    """Tokenize content into a saturated term-frequency sparse vector."""
    from myrm_agent_harness.toolkits.retriever.bm25_retrieval import preprocess_text

    # dedupe=False keeps term frequencies (default dedupe would flatten tf to 1)
    frequencies = Counter(preprocess_text(text, dedupe=False))
    if not frequencies:
        return [], []
    pairs = sorted((token_index(token), 1.0 + math.log(count)) for token, count in frequencies.items())
    indices, values = zip(*pairs, strict=True)
    return list(indices), list(values)


def query_to_sparse(text: str) -> tuple[list[int], list[float]]:
    """Tokenize a query into uniform-weight sparse indices (no tf on query side)."""
    from myrm_agent_harness.toolkits.retriever.bm25_retrieval import preprocess_text

    tokens = {t for t in preprocess_text(text) if t}
    if not tokens:
        return [], []
    indices = sorted(token_index(t) for t in tokens)
    return indices, [1.0] * len(indices)


def bm25_collection_for(collection: str) -> str:
    """Sparse mirror collection name for a dense collection."""
    return f"{collection}{BM25_COLLECTION_SUFFIX}"


def doc_to_sparse_point(doc: VectorDocument) -> SparsePoint:
    """Convert a dense-path document into its sparse mirror point.

    Payload stays identical to the dense upsert layout (same metadata and
    timestamps), so FilterDict semantics filter sparse results exactly like
    dense results.
    """
    indices, values = content_to_sparse(doc.content)
    return SparsePoint(
        id=doc.id,
        indices=indices,
        values=values,
        content=doc.content,
        metadata=dict(doc.metadata),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


class BM25SparseIndexStore:
    """VectorStoreProtocol wrapper maintaining a persistent BM25 sparse mirror.

    Only sparse-capable backends (qdrant with the sparse mixin) are wrapped —
    ``wrap_with_bm25_sparse_index`` decides capability at assembly time, so
    this class can assume the sparse hooks exist. Every upsert/delete/
    delete_by_filter is mirrored (fail-open) into ``{collection}_bm25`` once
    the index is warm; ``bm25_backfill`` warms it from the dense collections;
    ``bm25_search`` serves BM25 queries from it.
    """

    def __init__(self, inner: VectorStoreProtocol) -> None:
        self._inner = inner
        self._sparse_ready = False
        self._backfill_scheduled = False

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
        deleted = await self._inner.delete(collection, ids)
        if deleted:
            try:
                await self._inner.delete(bm25_collection_for(collection), ids)
            except Exception as exc:
                self._log_sync_failure("delete", collection, exc)
        return deleted

    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int:
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

        Returns ``None`` when the sparse channel is unavailable or not yet
        warmed so the caller can fall back to the corpus-scroll path; raises
        nothing — transient sparse failures also degrade to ``None``.
        """
        if not self._sparse_ready:
            # First BM25 query in an async context: warm the index in the
            # background; this query (and any racing ones) use the legacy
            # corpus-scroll path until the backfill lands.
            self._schedule_backfill_once(config)
            return None

        from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
            _user_filter,
            doc_to_episodic,
            doc_to_semantic,
        )

        indices, values = query_to_sparse(query)
        if not indices:
            return None

        filters = _user_filter(namespaces=namespaces, since=since, until=until)
        top_k = limit if limit is not None else config.bm25_top_k

        # converters produce concrete memory models; the record type is the
        # same union MemorySearchResult.memory accepts, so no cast is needed.
        targets: list[tuple[str, MemoryType, Callable[[VectorDocument], SemanticMemory | EpisodicMemory]]] = [
            (config.semantic_collection, MemoryType.SEMANTIC, doc_to_semantic),
            (config.episodic_collection, MemoryType.EPISODIC, doc_to_episodic),
        ]

        async def search_one(
            collection: str, memory_type: MemoryType
        ) -> list[tuple[float, VectorDocument, MemoryType]]:
            results = await self._inner.search_sparse(  # type: ignore[attr-defined]
                bm25_collection_for(collection),
                indices,
                values,
                limit=top_k,
                filters=filters,
            )
            return [(r.score, r.document, memory_type) for r in results]

        # Both collections queried in parallel, mirroring the legacy dual-scroll.
        try:
            outcomes = await asyncio.gather(*(search_one(c, mt) for c, mt, _ in targets))
        except Exception as exc:
            logger.warning("BM25 sparse search degraded (non-fatal): %s", exc)
            return None
        hits = [hit for outcome in outcomes for hit in outcome]

        if not hits:
            return []

        hits.sort(key=lambda h: h[0], reverse=True)
        hits = hits[:top_k]
        normalizer = hits[0][0] if hits[0][0] > 0 else 1.0
        converters: dict[MemoryType, Callable[[VectorDocument], SemanticMemory | EpisodicMemory]] = {
            MemoryType.SEMANTIC: doc_to_semantic,
            MemoryType.EPISODIC: doc_to_episodic,
        }
        converted: list[MemorySearchResult] = []
        for score, doc, memory_type in hits:
            converted.append(
                MemorySearchResult(
                    memory=converters[memory_type](doc),
                    score=min(score / normalizer, 1.0),
                    memory_type=memory_type,
                )
            )
        return converted

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
        return await self._inner.scroll(collection, limit=limit, offset=offset, filters=filters, order_by=order_by)

    async def ensure_collection(self, name: str, dimension: int, *, distance: str = "cosine") -> None:
        await self._inner.ensure_collection(name, dimension, distance=distance)

    async def create_collection(self, name: str, dimension: int, *, distance: str = "cosine") -> None:
        await self._inner.create_collection(name, dimension, distance=distance)

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
) -> VectorStoreProtocol | None:
    """Wrap a sparse-capable backend with the BM25 sparse mirror.

    Capability is decided here and exactly once, by exact class membership —
    qdrant with the sparse mixin is the only sparse backend, and an isinstance
    check (unlike hasattr duck-probing) cannot be spoofed by mock stand-ins,
    so tests keep direct attribute reach into their store.
    """
    if vector is None:
        return None
    if isinstance(vector, BM25SparseIndexStore):
        return vector
    if isinstance(vector, QdrantSparseMixin):
        return BM25SparseIndexStore(vector)
    return vector


def unwrap_sparse_mirror(vector: VectorStoreProtocol) -> VectorStoreProtocol:
    """Return the backend beneath the BM25 mirror (a bare store passes through).

    The mirror covers the semantic and episodic collections only. The
    conversation collection holds named vectors (raw/summary), which the
    wrapper's single-vector pass-through can neither write nor query, so its
    reads and writes address the backend directly.
    """
    return vector._inner if isinstance(vector, BM25SparseIndexStore) else vector
