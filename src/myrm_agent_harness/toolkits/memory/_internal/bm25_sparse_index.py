"""BM25 Sparse Index — persistent, incrementally-maintained inverted index.

[INPUT]
- memory.protocols.vector::{VectorStoreProtocol, VectorDocument, FilterDict} (POS: vector protocol)
- memory._internal.storage_converters::{doc_to_semantic, doc_to_episodic, _user_filter} (POS: converters)
- memory.types::{MemorySearchResult, MemoryType} (POS: memory data models)
- retriever.bm25_retrieval::preprocess_text (POS: shared CJK/latin tokenizer)

[OUTPUT]
- token_index: stable u31 token hash (zero-vocabulary, no term dictionary)
- content_to_sparse / query_to_sparse: token stream -> (indices, values)
- BM25SparseIndexStore: VectorStoreProtocol wrapper that mirrors every
  upsert/delete into a ``{collection}_bm25`` sparse collection and serves
  BM25 queries from it; pure pass-through when the backend lacks sparse
- wrap_with_bm25_sparse_index: factory used at manager assembly

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
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.protocols.vector import (
    FilterDict,
    VectorDocument,
    VectorStoreProtocol,
)
from myrm_agent_harness.toolkits.vector.base import SparsePoint

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.types import MemorySearchResult

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

    Every upsert/delete/delete_by_filter is mirrored (fail-open) into
    ``{collection}_bm25`` once the index is warm; ``bm25_backfill`` warms it
    from the dense collections; ``bm25_search`` serves BM25 queries from it.
    Backends without sparse support get a pure pass-through wrapper.
    """

    def __init__(self, inner: VectorStoreProtocol) -> None:
        self._inner = inner
        self._sparse_capable = hasattr(inner, "upsert_sparse") and hasattr(inner, "search_sparse")
        self._sparse_ready = False
        self._backfill_scheduled = False

    @property
    def bm25_sparse_enabled(self) -> bool:
        """True when the backend can serve persistent BM25 sparse queries."""
        return self._sparse_capable

    def _schedule_backfill_once(self, config: MemoryConfig) -> None:
        """Kick off the one-time warmup from the first BM25 query.

        Called from async query paths only, so a running loop is guaranteed;
        a sync manager construction never touches asyncio.create_task here.
        Re-scheduling is suppressed for the process lifetime; failures log
        and leave the wrapper on the legacy corpus-scroll path.
        """
        if self._backfill_scheduled or not self._sparse_capable:
            return
        self._backfill_scheduled = True
        task = asyncio.get_running_loop().create_task(self._backfill_task(config))
        task.add_done_callback(_log_task_failure)
    # ── Write interception (fail-open sparse sync) ──────────────────────

    async def upsert(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        ids = await self._inner.upsert(collection, documents)
        if self._sparse_capable and self._sparse_ready and documents:
            try:
                points = [doc_to_sparse_point(doc) for doc in documents]
                await self._inner.upsert_sparse(bm25_collection_for(collection), points)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("BM25 sparse index sync failed for %s (non-fatal): %s", collection, exc)
        return ids

    async def delete(self, collection: str, ids: list[str]) -> int:
        deleted = await self._inner.delete(collection, ids)
        if self._sparse_capable and self._sparse_ready and deleted:
            try:
                await self._inner.delete(bm25_collection_for(collection), ids)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("BM25 sparse index delete sync failed for %s (non-fatal): %s", collection, exc)
        return deleted

    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int:
        deleted = await self._inner.delete_by_filter(collection, filters)
        if self._sparse_capable and self._sparse_ready:
            try:
                await self._inner.delete_by_filter(bm25_collection_for(collection), filters)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("BM25 sparse index filter-delete sync failed (non-fatal): %s", exc)
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
        if not self._sparse_capable:
            return 0

        ensure = getattr(self._inner, "ensure_sparse_collection", None)
        if ensure is None:
            return 0

        total = 0
        for collection in (config.semantic_collection, config.episodic_collection):
            if not await self._inner.collection_exists(collection):
                continue
            sparse_name = bm25_collection_for(collection)
            try:
                await ensure(sparse_name)
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
        if not self._sparse_capable:
            return None
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
        from myrm_agent_harness.toolkits.memory.types import MemorySearchResult, MemoryType

        indices, values = query_to_sparse(query)
        if not indices:
            return None

        filters = _user_filter(namespaces=namespaces, since=since, until=until)
        top_k = limit if limit is not None else config.bm25_top_k

        hits: list[tuple[float, VectorDocument, object]] = []
        for collection, memory_type, converter in (
            (config.semantic_collection, MemoryType.SEMANTIC, doc_to_semantic),
            (config.episodic_collection, MemoryType.EPISODIC, doc_to_episodic),
        ):
            try:
                results = await self._inner.search_sparse(  # type: ignore[attr-defined]
                    bm25_collection_for(collection),
                    indices,
                    values,
                    limit=top_k,
                    filters=filters,
                )
            except Exception as exc:
                logger.warning("BM25 sparse search degraded for %s (non-fatal): %s", collection, exc)
                return None
            for r in results:
                hits.append((r.score, r.document, memory_type))

        if not hits:
            return []

        hits.sort(key=lambda h: h[0], reverse=True)
        hits = hits[:top_k]
        normalizer = hits[0][0] if hits[0][0] > 0 else 1.0
        converted: list[MemorySearchResult] = []
        for score, doc, memory_type in hits:
            converted.append(
                MemorySearchResult(
                    memory=converter(doc),  # type: ignore[arg-type]
                    score=min(score / normalizer, 1.0),
                    memory_type=memory_type,  # type: ignore[arg-type]
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
    ) -> list:
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
    """Wrap a vector backend with the BM25 sparse mirror (no-op when None)."""
    if vector is None:
        return None
    if isinstance(vector, BM25SparseIndexStore):
        return vector
    return BM25SparseIndexStore(vector)
