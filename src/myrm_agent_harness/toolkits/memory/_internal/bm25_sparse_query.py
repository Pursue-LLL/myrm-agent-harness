"""BM25 Sparse Query — the mirror's fan-out query pipeline.

[INPUT]
- memory.protocols.vector::{VectorStoreProtocol, VectorDocument} (POS: vector protocol)
- memory.config::MemoryConfig (POS: collection names, bm25_top_k)
- memory._internal.bm25_sparse_encoding::{bm25_collection_for, query_to_sparse} (POS: sparse encoding)
- memory._internal.storage_converters::{_user_filter, doc_to_episodic, doc_to_semantic} (POS: converters)
- memory.types::{MemorySearchResult, MemoryType} (POS: memory data models)

[OUTPUT]
- run_bm25_search: BM25 query over the semantic + episodic sparse mirrors,
  fused by raw score and max-normalized against the head hit

[POS]
Query half of the persistent BM25 mirror. Runs both sparse collections in
parallel and keeps query logic out of the wrapper: ``None`` means the backend
failed (the caller degrades to the corpus-scroll path), ``[]`` means the query
tokenizes to nothing or no document matches. Readiness and warmup stay with
the wrapper.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_encoding import (
    bm25_collection_for,
    query_to_sparse,
)
from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
    _user_filter,
    doc_to_episodic,
    doc_to_semantic,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument, VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.types import (
    EpisodicMemory,
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig

logger = logging.getLogger(__name__)


async def run_bm25_search(
    inner: VectorStoreProtocol,
    query: str,
    config: MemoryConfig,
    *,
    limit: int | None = None,
    namespaces: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MemorySearchResult] | None:
    """Fan a BM25 query out over both sparse mirrors of a sparse-capable backend.

    Returns ``None`` when the query tokenizes to nothing or the backend fails
    so the caller can fall back to the corpus-scroll path; ``[]`` when no
    document matches.
    """
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

    async def search_one(collection: str, memory_type: MemoryType) -> list[tuple[float, VectorDocument, MemoryType]]:
        try:
            results = await inner.search_sparse(  # type: ignore[attr-defined]
                bm25_collection_for(collection),
                indices,
                values,
                limit=top_k,
                filters=filters,
            )
        except Exception as exc:
            # A missing sparse collection means "never written in this mode"
            # (embeddings-less deployments ensure it on first write); treat it
            # as empty rather than failing the whole search. Real backend
            # failures still degrade below.
            if "not found" in str(exc).lower():
                logger.debug("BM25 sparse collection absent for %s; skipping", collection)
                return []
            raise
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
