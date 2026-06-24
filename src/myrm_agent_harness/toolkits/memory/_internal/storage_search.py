"""Search operations for memory retrieval.

[INPUT]
- storage_converters::{doc_to_semantic, doc_to_episodic, doc_to_conversation, _user_filter}
- memory.protocols.vector::VectorStoreProtocol
- memory.types::{MemorySearchResult, MemoryType, SemanticMemory}

[OUTPUT]
- search_profile, search_semantic, search_episodic, search_procedural
- search_bm25, search_conversation

[POS]
Search-specific storage operations. Handles vector similarity search, BM25 keyword
retrieval, profile/procedural text search, and dual-channel conversation search with
RRF fusion.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
    _user_filter,
    doc_to_conversation,
    doc_to_episodic,
    doc_to_semantic,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorDocument
from myrm_agent_harness.toolkits.memory.types import (
    MemorySearchResult,
    MemoryType,
    SemanticMemory,
)
from myrm_agent_harness.utils.coercion import parse_int

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.relational import (
        RelationalStoreProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)


# ======================================================================
# Adaptive threshold
# ======================================================================

_memory_count_cache: dict[str, int] = {}
_count_cache_hits: int = 0


def _safe_int(val: object, default: int = 0) -> int:
    return parse_int(val, default)


async def _get_adaptive_threshold(vector: VectorStoreProtocol, collections: list[str], config: MemoryConfig) -> float:
    """Get adaptive similarity threshold based on memory count.

    Caches memory_count and refreshes every 10 searches to avoid excessive queries.
    Falls back to config.similarity_threshold if adaptive is disabled.
    """
    global _count_cache_hits

    if not config.enable_adaptive_threshold:
        return config.similarity_threshold

    cache_key = "|".join(sorted(collections))

    if _count_cache_hits % 10 == 0 or cache_key not in _memory_count_cache:
        total_count = 0
        for coll in collections:
            try:
                count = _safe_int(await vector.count(collection=coll))
                total_count += count
            except Exception:
                pass
        _memory_count_cache[cache_key] = total_count

    _count_cache_hits += 1
    memory_count = _memory_count_cache.get(cache_key, 0)

    return config.adaptive_threshold_strategy.get_threshold(memory_count)


# ======================================================================
# Search helpers
# ======================================================================


async def search_profile(
    query: str,
    limit: int,
    relational: RelationalStoreProtocol,
    *,
    namespaces: list[str] | None = None,
) -> list[MemorySearchResult]:
    entries = await relational.list_profiles(namespaces=namespaces)
    q_lower = query.lower()
    scored: list[MemorySearchResult] = []
    for entry in entries:
        if q_lower in entry.key.lower() or q_lower in str(entry.value).lower():
            scored.append(
                MemorySearchResult(
                    memory=SemanticMemory(content=f"{entry.key}: {entry.value}", importance=0.8),
                    score=0.8,
                    memory_type=MemoryType.PROFILE,
                )
            )
    return scored[:limit]


async def search_semantic(
    query_vec: list[float],
    limit: int,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    namespaces: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MemorySearchResult]:
    threshold = await _get_adaptive_threshold(vector, [config.semantic_collection], config)
    hits = await vector.search(
        config.semantic_collection,
        query_vec,
        limit=limit,
        filters=_user_filter(namespaces=namespaces, since=since, until=until),
        score_threshold=threshold,
    )
    return [
        MemorySearchResult(
            memory=doc_to_semantic(h.document),
            score=h.score,
            memory_type=MemoryType.SEMANTIC,
        )
        for h in hits
    ]


async def search_episodic(
    query_vec: list[float],
    limit: int,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    namespaces: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MemorySearchResult]:
    threshold = await _get_adaptive_threshold(vector, [config.episodic_collection], config)
    hits = await vector.search(
        config.episodic_collection,
        query_vec,
        limit=limit,
        filters=_user_filter(namespaces=namespaces, since=since, until=until),
        score_threshold=threshold,
    )
    return [
        MemorySearchResult(
            memory=doc_to_episodic(h.document),
            score=h.score,
            memory_type=MemoryType.EPISODIC,
        )
        for h in hits
    ]


async def search_procedural(
    query: str,
    limit: int,
    relational: RelationalStoreProtocol,
    *,
    namespaces: list[str] | None = None,
) -> list[MemorySearchResult]:
    rules = await relational.search_rules(query, limit=limit, namespaces=namespaces)
    return [
        MemorySearchResult(memory=r, score=max(0.5, 1.0 - i * 0.1), memory_type=MemoryType.PROCEDURAL)
        for i, r in enumerate(rules)
    ]


async def _scroll_vector_memories(
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    namespaces: list[str] | None,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> tuple[list[VectorDocument], list[VectorDocument]]:
    """Scroll active semantic and episodic memories in the configured namespace boundary."""
    max_size = config.bm25_max_corpus_size
    uf = _user_filter(namespaces=namespaces, since=since, until=until)
    (sem_docs, _), (epi_docs, _) = await asyncio.gather(
        vector.scroll(config.semantic_collection, limit=max_size, filters=uf),
        vector.scroll(config.episodic_collection, limit=max_size, filters=uf),
    )
    return sem_docs, epi_docs


async def search_bm25(
    query: str,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    namespaces: list[str] | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MemorySearchResult]:
    """BM25 keyword-based retrieval for proper nouns and exact matches.

    Complements vector search by providing keyword matching across Semantic + Episodic
    memories. Results are fused with vector results via RRF in MemoryManager.

    Auto-degrades to empty results when total memory count exceeds bm25_max_corpus_size
    to maintain performance guarantees.
    """
    sem_docs, epi_docs = await _scroll_vector_memories(vector, config, namespaces, since=since, until=until)
    total_count = len(sem_docs) + len(epi_docs)

    if total_count > config.bm25_max_corpus_size:
        logger.warning(
            "BM25 auto-degraded: memory count %d exceeds max_corpus_size %d",
            total_count,
            config.bm25_max_corpus_size,
        )
        return []

    if total_count == 0:
        return []

    all_docs = sem_docs + epi_docs
    if not all_docs:
        return []

    contents = [d.content for d in all_docs]

    from myrm_agent_harness.toolkits.retriever.bm25_retrieval import BM25Retriever

    retriever = BM25Retriever(contents)
    bm25_results = retriever.search(query, top_k=config.bm25_top_k, only_relevant=True)

    if not bm25_results:
        return []

    max_score = max(score for _, score in bm25_results)
    normalizer = max_score if max_score > 0 else 1.0

    results: list[MemorySearchResult] = []
    for idx, score in bm25_results:
        doc = all_docs[idx]
        is_semantic = idx < len(sem_docs)
        memory_type = MemoryType.SEMANTIC if is_semantic else MemoryType.EPISODIC
        converter = doc_to_semantic if is_semantic else doc_to_episodic
        normalized_score = min(score / normalizer, 1.0)
        results.append(MemorySearchResult(memory=converter(doc), score=normalized_score, memory_type=memory_type))

    return results


async def search_conversation(
    query_raw: list[float] | None,
    query_summary: list[float],
    limit: int,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    namespaces: list[str] | None = None,
    include_raw: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[MemorySearchResult]:
    """Adaptive dual-channel conversation search with cost optimization.

    Supports both single-channel (summary only) and dual-channel (raw + summary) modes.
    When query_raw is None, uses summary embedding only for ~50% cost savings.
    """
    from myrm_agent_harness.toolkits.vector.base import VectorStore

    collection = config.conversation_collection
    filters = _user_filter(namespaces=namespaces, since=since, until=until)

    score_threshold = await _get_adaptive_threshold(vector, [collection], config)

    if query_raw is None and isinstance(vector, VectorStore) and hasattr(vector, "search_multi_vector"):
        try:
            search_results = await vector.search_multi_vector(
                collection,
                named_vectors={"summary": query_summary},
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
                fusion="rrf",
            )
            return [
                MemorySearchResult(
                    memory=doc_to_conversation(r.document, include_raw=include_raw, config=config),
                    score=r.score,
                    memory_type=MemoryType.CONVERSATION,
                )
                for r in search_results
            ]
        except NotImplementedError:
            logger.debug("Backend doesn't support search_multi_vector for single channel")

    if query_raw is None:
        summary_hits = await vector.search(
            collection,
            query_summary,
            limit=limit,
            filters=filters,
            score_threshold=score_threshold,
        )
        return [
            MemorySearchResult(
                memory=doc_to_conversation(r.document, include_raw=include_raw, config=config),
                score=r.score,
                memory_type=MemoryType.CONVERSATION,
            )
            for r in summary_hits
        ]

    if isinstance(vector, VectorStore) and hasattr(vector, "search_multi_vector"):
        try:
            search_results = await vector.search_multi_vector(
                collection,
                named_vectors={"raw": query_raw, "summary": query_summary},
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
                fusion="rrf",
            )
            return [
                MemorySearchResult(
                    memory=doc_to_conversation(r.document, include_raw=include_raw, config=config),
                    score=r.score,
                    memory_type=MemoryType.CONVERSATION,
                )
                for r in search_results
            ]
        except NotImplementedError:
            logger.debug("Backend doesn't support search_multi_vector, falling back to 2x search + RRF")

    raw_hits = await vector.search(
        collection,
        query_raw,
        limit=limit * 2,
        filters=filters,
        score_threshold=score_threshold,
    )
    summary_hits = await vector.search(
        collection,
        query_summary,
        limit=limit * 2,
        filters=filters,
        score_threshold=score_threshold,
    )

    from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever

    retriever = MemoryRetriever(config.retrieval)

    raw_results = [
        MemorySearchResult(
            memory=doc_to_conversation(r.document, include_raw=include_raw, config=config),
            score=r.score,
            memory_type=MemoryType.CONVERSATION,
        )
        for r in raw_hits
    ]
    summary_results = [
        MemorySearchResult(
            memory=doc_to_conversation(r.document, include_raw=include_raw, config=config),
            score=r.score,
            memory_type=MemoryType.CONVERSATION,
        )
        for r in summary_hits
    ]

    fused = retriever.fuse([raw_results, summary_results], limit=limit, query="")
    return fused
