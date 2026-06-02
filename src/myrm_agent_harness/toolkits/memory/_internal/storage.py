"""Internal storage operations for MemoryManager.


[INPUT]
- memory.protocols.vector::{VectorDocument, FilterDict} (POS: vector store protocol and data models)
- memory.types::{SemanticMemory, EpisodicMemory, ConversationMemory, ...} (POS: memory data models)

[OUTPUT]
- store_semantic, store_episodic, store_conversation: Vector storage write functions
- doc_to_semantic, doc_to_episodic, doc_to_conversation: Vector → memory model converters
- get_from_vector, delete_from_vector, list_by_type, count_by_type, load_context: Read/query functions
- MemoryError, MemoryNotFoundError: Error types

[POS]
Internal storage operations. Handles vector ↔ schema conversion, embedding generation,
and direct storage backend calls. Not part of the public API.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.protocols.vector import (
    FilterDict,
    VectorDocument,
)
from myrm_agent_harness.toolkits.memory.types import (
    ClaimConflictState,
    ClaimGraphState,
    ConversationMemory,
    DigestKind,
    EpisodicMemory,
    EvaporationState,
    MemoryLifecycle,
    MemoryScope,
    MemorySearchResult,
    MemoryTier,
    MemoryType,
    ProceduralMemory,
    ProfileEntry,
    RuleSource,
    SemanticMemory,
)

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.cache import (
        EmbeddingCacheProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
    from myrm_agent_harness.toolkits.memory.protocols.relational import (
        RelationalStoreProtocol,
    )
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol


from myrm_agent_harness.utils.coercion import parse_float, parse_int


def _safe_float(val: object, default: float = 0.0) -> float:
    return parse_float(val, default)


def _safe_int(val: object, default: int = 0) -> int:
    return parse_int(val, default)


logger = logging.getLogger(__name__)


_memory_count_cache: dict[str, int] = {}
_count_cache_hits: int = 0


async def _get_adaptive_threshold(
    vector: VectorStoreProtocol, collections: list[str], config: MemoryConfig
) -> float:
    """Get adaptive similarity threshold based on memory count.

    Caches memory_count and refreshes every 10 searches to avoid excessive queries.
    Falls back to config.similarity_threshold if adaptive is disabled.

    Args:
        vector: Vector store protocol
        collections: List of collections to count
        config: Memory configuration

    Returns:
        Adaptive or fixed similarity threshold
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


def _user_filter(
    *,
    namespaces: list[str] | None = None,
    include_archived: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
) -> FilterDict:
    """Build the standard user-scoped filter for vector queries.

    Centralizes archived-exclusion and time-range filtering so every
    query path uses the same logic.
    """
    f: FilterDict = {"archived": False}
    if namespaces:
        f["namespaces"] = namespaces
    if include_archived:
        del f["archived"]
    if since is not None or until is not None:
        time_range: dict[str, str | int | float] = {}
        if since is not None:
            time_range["gte"] = since.isoformat()
        if until is not None:
            time_range["lte"] = until.isoformat()
        f["created_at"] = time_range
    return f


def _scope_payload(scope: MemoryScope) -> dict[str, str | list[str]]:
    return {
        "primary_namespace": scope.primary_namespace,
        "namespaces": list(scope.namespaces),
        "agent_id": scope.agent_id or "",
        "channel_id": scope.channel_id or "",
        "conversation_id": scope.conversation_id or "",
        "task_id": scope.task_id or "",
    }


def _scope_from_metadata(meta: dict[str, object]) -> MemoryScope:
    raw_namespaces = meta.get("namespaces", [])
    namespaces = (
        [value for value in raw_namespaces if isinstance(value, str)]
        if isinstance(raw_namespaces, list)
        else []
    )
    return MemoryScope(
        primary_namespace=str(meta.get("primary_namespace", "")),
        namespaces=namespaces,
        agent_id=str(meta.get("agent_id", "")) or None,
        channel_id=str(meta.get("channel_id", "")) or None,
        conversation_id=str(meta.get("conversation_id", "")) or None,
        task_id=str(meta.get("task_id", "")) or None,
    )


def _lifecycle_payload(lifecycle: MemoryLifecycle | None) -> dict[str, str]:
    if lifecycle is None:
        return {}
    return {
        "memory_tier": lifecycle.tier.value,
        "digest_kind": (
            lifecycle.digest_kind.value if lifecycle.digest_kind is not None else ""
        ),
        "evaporation_state": (
            lifecycle.evaporation_state.value
            if lifecycle.evaporation_state is not None
            else ""
        ),
        "evaporated_at": (
            lifecycle.evaporated_at.isoformat()
            if lifecycle.evaporated_at is not None
            else ""
        ),
        "claim_graph_state": (
            lifecycle.claim_graph_state.value
            if lifecycle.claim_graph_state is not None
            else ""
        ),
        "claim_graph_node_id": lifecycle.claim_graph_node_id or "",
        "claim_graph_updated_at": (
            lifecycle.claim_graph_updated_at.isoformat()
            if lifecycle.claim_graph_updated_at is not None
            else ""
        ),
        "claim_graph_conflict": (
            lifecycle.claim_graph_conflict.value
            if lifecycle.claim_graph_conflict is not None
            else ""
        ),
    }


def _lifecycle_from_metadata(meta: dict[str, object]) -> MemoryLifecycle | None:
    raw_tier = str(meta.get("memory_tier", "")).strip()
    if raw_tier not in {tier.value for tier in MemoryTier}:
        return None

    raw_digest_kind = str(meta.get("digest_kind", "")).strip()
    digest_kind = (
        DigestKind(raw_digest_kind)
        if raw_digest_kind in {kind.value for kind in DigestKind}
        else None
    )

    raw_evaporation_state = str(meta.get("evaporation_state", "")).strip()
    evaporation_state = (
        EvaporationState(raw_evaporation_state)
        if raw_evaporation_state in {state.value for state in EvaporationState}
        else None
    )

    raw_claim_graph_state = str(meta.get("claim_graph_state", "")).strip()
    claim_graph_state = (
        ClaimGraphState(raw_claim_graph_state)
        if raw_claim_graph_state in {state.value for state in ClaimGraphState}
        else None
    )

    raw_claim_graph_conflict = str(meta.get("claim_graph_conflict", "")).strip()
    claim_graph_conflict = (
        ClaimConflictState(raw_claim_graph_conflict)
        if raw_claim_graph_conflict in {state.value for state in ClaimConflictState}
        else None
    )

    raw_evaporated_at = str(meta.get("evaporated_at", "")).strip()
    try:
        evaporated_at = (
            datetime.fromisoformat(raw_evaporated_at) if raw_evaporated_at else None
        )
    except ValueError:
        evaporated_at = None

    raw_claim_graph_updated_at = str(meta.get("claim_graph_updated_at", "")).strip()
    try:
        claim_graph_updated_at = (
            datetime.fromisoformat(raw_claim_graph_updated_at)
            if raw_claim_graph_updated_at
            else None
        )
    except ValueError:
        claim_graph_updated_at = None

    return MemoryLifecycle(
        tier=MemoryTier(raw_tier),
        digest_kind=digest_kind,
        evaporation_state=evaporation_state,
        evaporated_at=evaporated_at,
        claim_graph_state=claim_graph_state,
        claim_graph_node_id=str(meta.get("claim_graph_node_id", "")) or None,
        claim_graph_updated_at=claim_graph_updated_at,
        claim_graph_conflict=claim_graph_conflict,
    )


class MemoryError(Exception):
    """Base exception for memory operations."""


class MemoryNotFoundError(MemoryError):
    """Raised when a memory is not found."""


# ======================================================================
# Embedding helpers
# ======================================================================


async def embed_single(
    text: str, embedding: EmbeddingProtocol, cache: EmbeddingCacheProtocol | None
) -> list[float]:
    if cache is not None:
        cached = await cache.get(text)
        if cached is not None:
            return cached
    vec = await embedding.embed(text)
    if cache is not None:
        await cache.put(text, vec)
    return vec


async def embed_batch(
    texts: list[str], embedding: EmbeddingProtocol, cache: EmbeddingCacheProtocol | None
) -> list[list[float]]:
    if not texts:
        return []
    if cache is None:
        return await embedding.embed_batch(texts)

    cached = await cache.get_batch(texts)
    miss_indices = [i for i, v in enumerate(cached) if v is None]
    if not miss_indices:
        return [v for v in cached if v is not None]

    miss_texts = [texts[i] for i in miss_indices]
    new_vecs = await embedding.embed_batch(miss_texts)
    await cache.put_batch(miss_texts, new_vecs)

    result = list(cached)
    for idx, vec in zip(miss_indices, new_vecs, strict=True):
        result[idx] = vec
    return [v for v in result if v is not None]


# ======================================================================
# Store helpers
# ======================================================================


async def store_semantic(
    memory: SemanticMemory,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    embedding: EmbeddingProtocol,
    cache: EmbeddingCacheProtocol | None,
) -> SemanticMemory:
    if memory.embedding is None:
        memory.embedding = await embed_single(memory.content, embedding, cache)
    await vector.upsert(config.semantic_collection, [semantic_to_doc(memory)])
    return memory


async def store_semantics_batch(
    memories: list[SemanticMemory],
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    embedding: EmbeddingProtocol,
    cache: EmbeddingCacheProtocol | None,
) -> list[SemanticMemory]:
    texts = [m.content for m in memories if m.embedding is None]
    if texts:
        vecs = await embed_batch(texts, embedding, cache)
        idx = 0
        for m in memories:
            if m.embedding is None:
                m.embedding = vecs[idx]
                idx += 1
    await vector.upsert(
        config.semantic_collection, [semantic_to_doc(m) for m in memories]
    )
    return memories


async def store_episodic(
    memory: EpisodicMemory,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    embedding: EmbeddingProtocol,
    cache: EmbeddingCacheProtocol | None,
    graph: GraphStoreProtocol | None,
) -> EpisodicMemory:
    if memory.embedding is None:
        memory.embedding = await embed_single(memory.content, embedding, cache)
    await vector.upsert(config.episodic_collection, [episodic_to_doc(memory)])

    if graph is not None and memory.related_entities:
        try:
            mem_node = await graph.create_node(
                labels=["EpisodicMemory"],
                properties={
                    "id": memory.id,
                },
            )
            for entity in memory.related_entities:
                entity_node = await graph.get_or_create_node(
                    labels=["Entity"],
                    match_keys=["name", "user_id"],
                    properties={
                        "name": entity,
                    },
                )
                await graph.create_relationship(mem_node.id, entity_node.id, "MENTIONS")
        except Exception as e:
            logger.warning("Graph indexing failed (non-fatal): %s", e)
    return memory


async def store_episodics_batch(
    memories: list[EpisodicMemory],
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    embedding: EmbeddingProtocol,
    cache: EmbeddingCacheProtocol | None,
    graph: GraphStoreProtocol | None = None,
) -> list[EpisodicMemory]:
    texts = [m.content for m in memories if m.embedding is None]
    if texts:
        vecs = await embed_batch(texts, embedding, cache)
        idx = 0
        for m in memories:
            if m.embedding is None:
                m.embedding = vecs[idx]
                idx += 1
    await vector.upsert(
        config.episodic_collection, [episodic_to_doc(m) for m in memories]
    )

    if graph is not None:
        for m in memories:
            if not m.related_entities:
                continue
            try:
                mem_node = await graph.create_node(
                    labels=["EpisodicMemory"],
                    properties={
                        "id": m.id,
                    },
                )
                for entity in m.related_entities:
                    entity_node = await graph.get_or_create_node(
                        labels=["Entity"],
                        match_keys=["name", "user_id"],
                        properties={
                            "name": entity,
                        },
                    )
                    await graph.create_relationship(
                        mem_node.id, entity_node.id, "MENTIONS"
                    )
            except Exception as e:
                logger.warning(
                    "Graph indexing failed for batch item (non-fatal): %s", e
                )
    return memories


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
                    memory=SemanticMemory(
                        content=f"{entry.key}: {entry.value}", importance=0.8
                    ),
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
    threshold = await _get_adaptive_threshold(
        vector, [config.semantic_collection], config
    )
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
    threshold = await _get_adaptive_threshold(
        vector, [config.episodic_collection], config
    )
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
        MemorySearchResult(
            memory=r, score=max(0.5, 1.0 - i * 0.1), memory_type=MemoryType.PROCEDURAL
        )
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
    sem_docs, epi_docs = await _scroll_vector_memories(
        vector, config, namespaces, since=since, until=until
    )
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
        results.append(
            MemorySearchResult(
                memory=converter(doc), score=normalized_score, memory_type=memory_type
            )
        )

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

    Args:
        query_raw: Raw embedding query vector (None for single-channel mode).
        query_summary: Summary embedding query vector.
        limit: Maximum results to return after fusion.
        vector: Vector store backend.
        config: Memory configuration.
        include_raw: If True, populate raw_exchange field (default False for lazy loading).
        since: Optional lower bound (inclusive) for created_at time filter.
        until: Optional upper bound (inclusive) for created_at time filter.

    Returns:
        Conversation memory results sorted by score.
    """
    from myrm_agent_harness.toolkits.vector.base import VectorStore

    collection = config.conversation_collection
    filters = _user_filter(namespaces=namespaces, since=since, until=until)

    score_threshold = await _get_adaptive_threshold(vector, [collection], config)

    # Single-channel mode (summary only) - use search_multi_vector with only summary
    if (
        query_raw is None
        and isinstance(vector, VectorStore)
        and hasattr(vector, "search_multi_vector")
    ):
        try:
            search_results = await vector.search_multi_vector(
                collection,
                named_vectors={"summary": query_summary},
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
                fusion="rrf",  # No actual fusion with single vector, but API requires it
            )
            return [
                MemorySearchResult(
                    memory=doc_to_conversation(
                        r.document, include_raw=include_raw, config=config
                    ),
                    score=r.score,
                    memory_type=MemoryType.CONVERSATION,
                )
                for r in search_results
            ]
        except NotImplementedError:
            logger.debug(
                "Backend doesn't support search_multi_vector for single channel"
            )

    # Fallback for single-channel mode without search_multi_vector support
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
                memory=doc_to_conversation(
                    r.document, include_raw=include_raw, config=config
                ),
                score=r.score,
                memory_type=MemoryType.CONVERSATION,
            )
            for r in summary_hits
        ]

    # Dual-channel mode (raw + summary)
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
                    memory=doc_to_conversation(
                        r.document, include_raw=include_raw, config=config
                    ),
                    score=r.score,
                    memory_type=MemoryType.CONVERSATION,
                )
                for r in search_results
            ]
        except NotImplementedError:
            logger.debug(
                "Backend doesn't support search_multi_vector, falling back to 2x search + RRF"
            )

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
            memory=doc_to_conversation(
                r.document, include_raw=include_raw, config=config
            ),
            score=r.score,
            memory_type=MemoryType.CONVERSATION,
        )
        for r in raw_hits
    ]
    summary_results = [
        MemorySearchResult(
            memory=doc_to_conversation(
                r.document, include_raw=include_raw, config=config
            ),
            score=r.score,
            memory_type=MemoryType.CONVERSATION,
        )
        for r in summary_hits
    ]

    fused = retriever.fuse([raw_results, summary_results], limit=limit, query="")
    return fused


# ======================================================================
# Get / Update helpers
# ======================================================================


async def get_from_vector(
    memory_id: str,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    *,
    namespaces: list[str] | None = None,
) -> SemanticMemory | EpisodicMemory | None:
    for coll, converter in (
        (config.semantic_collection, doc_to_semantic),
        (config.episodic_collection, doc_to_episodic),
    ):
        docs = await vector.get(coll, [memory_id])
        if not docs:
            continue
        if namespaces:
            doc_namespaces = docs[0].metadata.get("namespaces")
            if isinstance(doc_namespaces, list) and not any(
                ns in namespaces for ns in doc_namespaces if isinstance(ns, str)
            ):
                continue
        return converter(docs[0])
    return None


async def update_vector_memory(
    memory: SemanticMemory | EpisodicMemory,
    content_changed: bool,
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    embedding: EmbeddingProtocol,
    cache: EmbeddingCacheProtocol | None,
) -> SemanticMemory | EpisodicMemory:
    if content_changed:
        memory.embedding = await embed_single(memory.content, embedding, cache)
    if isinstance(memory, SemanticMemory):
        await vector.upsert(config.semantic_collection, [semantic_to_doc(memory)])
    else:
        await vector.upsert(config.episodic_collection, [episodic_to_doc(memory)])
    return memory


async def delete_from_vector(
    collection: str, ids: list[str], vector: VectorStoreProtocol
) -> int:
    return await vector.delete(collection, ids)


# ======================================================================
# Context loading
# ======================================================================


async def load_context(
    relational: RelationalStoreProtocol,
    *,
    include_profile: bool = True,
    include_rules: bool = True,
    include_agent_instructions: bool = True,
    namespaces: list[str] | None = None,
) -> dict[str, object]:
    ctx: dict[str, object] = {"global_profile": {}, "peer_profile": {}, "rules": [], "agent_instructions": []}

    tasks: dict[str, asyncio.Task[object]] = {}
    if include_profile:
        tasks["profile"] = asyncio.create_task(
            relational.list_profiles(namespaces=namespaces)
        )
    if include_rules:
        tasks["rules"] = asyncio.create_task(
            relational.list_rules(active_only=True, namespaces=namespaces)
        )

    results = dict(
        zip(
            tasks.keys(),
            await asyncio.gather(*tasks.values(), return_exceptions=True),
            strict=True,
        )
    )

    if "profile" in results and not isinstance(results["profile"], Exception):
        entries = results["profile"]
        if isinstance(entries, list):
            global_profile = {}
            peer_profile = {}
            for e in entries:
                if not isinstance(e, ProfileEntry):
                    continue
                if e.scope.primary_namespace == "global":
                    global_profile[e.key] = e.value
                else:
                    peer_profile[e.key] = e.value
            ctx["global_profile"] = global_profile
            ctx["peer_profile"] = peer_profile

    if "rules" in results and not isinstance(results["rules"], Exception):
        rules_raw = results["rules"]
        user_rules: list[dict[str, str | int]] = []
        agent_instrs: list[dict[str, str | int]] = []
        if isinstance(rules_raw, list):
            for r in rules_raw:
                if isinstance(r, ProceduralMemory):
                    if r.source == RuleSource.AGENT_SELF:
                        agent_instrs.append(
                            {"instruction": r.action, "priority": r.priority}
                        )
                    else:
                        user_rules.append(
                            {
                                "trigger": r.trigger,
                                "action": r.action,
                                "priority": r.priority,
                            }
                        )
        ctx["rules"] = user_rules
        if include_agent_instructions:
            ctx["agent_instructions"] = agent_instrs

    return ctx


# ======================================================================
# Document <-> Schema conversion
# ======================================================================


def semantic_to_doc(m: SemanticMemory) -> VectorDocument:
    payload: dict[str, str | int | float | bool | list[str]] = {
        "memory_type": MemoryType.SEMANTIC.value,
        "importance": m.importance,
        "confidence": m.confidence,
        "source_chat_id": m.source_chat_id or "",
        "preference_type": m.preference_type or "",
        "preference_strength": m.preference_strength,
        "correction_of": m.correction_of or "",
        "source_error": m.source_error or "",
        "access_count": m.access_count,
        "user_rating": m.user_rating,
        "language": m.language,
        "merge_count": m.merge_count,
        "merge_history": m.merge_history,
        "pinned": m.pinned,
        "status": m.status,
        "archived": m.status == "archived",
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        **_scope_payload(m.scope),
        **_lifecycle_payload(m.lifecycle),
    }
    for k, v in m.metadata.items():
        if k not in payload:
            payload[k] = v
    return VectorDocument(
        id=m.id,
        content=m.content,
        vector=m.embedding,
        metadata=payload,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


_SEMANTIC_KNOWN_KEYS = frozenset(
    {
        "user_id",
        "memory_type",
        "importance",
        "confidence",
        "source_chat_id",
        "preference_type",
        "preference_strength",
        "correction_of",
        "source_error",
        "access_count",
        "user_rating",
        "tags",
        "merge_count",
        "merge_history",
        "language",
        "pinned",
        "archived",
        "archived_at",
        "archive_reason",
        "created_at",
        "updated_at",
        "primary_namespace",
        "namespaces",
        "agent_id",
        "channel_id",
        "conversation_id",
        "task_id",
        "memory_tier",
        "digest_kind",
        "evaporation_state",
        "evaporated_at",
        "claim_graph_state",
        "claim_graph_node_id",
        "claim_graph_updated_at",
        "claim_graph_conflict",
    }
)


def doc_to_semantic(doc: VectorDocument) -> SemanticMemory:
    meta = doc.metadata
    raw_pref = str(meta.get("preference_type", ""))
    pref_type = raw_pref if raw_pref in ("explicit", "implicit") else None
    raw_corr = str(meta.get("correction_of", ""))
    raw_lang = str(meta.get("language", "en"))
    lang = raw_lang if raw_lang in ("zh", "en") else "en"
    extra: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if k not in _SEMANTIC_KNOWN_KEYS and isinstance(v, (str, int, float, bool)):
            extra[k] = v
    return SemanticMemory(
        id=doc.id,
        user_id=str(meta.get("user_id", "")),
        content=doc.content,
        embedding=doc.vector,
        importance=_safe_float(meta.get("importance", 0.5), 0.5),
        confidence=_safe_float(meta.get("confidence", 1.0), 1.0),
        source_chat_id=str(meta.get("source_chat_id", "")) or None,
        preference_type=pref_type,
        preference_strength=_safe_float(meta.get("preference_strength", 0.0)),
        correction_of=raw_corr or None,
        source_error=str(meta.get("source_error", "")) or None,
        access_count=_safe_int(meta.get("access_count", 0)),
        user_rating=_safe_float(meta.get("user_rating", 0.5), 0.5),
        pinned=bool(meta.get("pinned", False)),
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        language=lang,
        merge_count=_safe_int(meta.get("merge_count", 0)),
        merge_history=str(meta.get("merge_history", "")),
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
    )


_EPISODIC_KNOWN_KEYS = frozenset(
    {
        "user_id",
        "memory_type",
        "event_type",
        "importance",
        "source_chat_id",
        "access_count",
        "user_rating",
        "related_entities",
        "merge_count",
        "merge_history",
        "language",
        "pinned",
        "archived",
        "archived_at",
        "archive_reason",
        "created_at",
        "updated_at",
        "primary_namespace",
        "namespaces",
        "agent_id",
        "channel_id",
        "conversation_id",
        "task_id",
        "memory_tier",
        "digest_kind",
        "evaporation_state",
        "evaporated_at",
        "claim_graph_state",
        "claim_graph_node_id",
        "claim_graph_updated_at",
        "claim_graph_conflict",
    }
)


def episodic_to_doc(m: EpisodicMemory) -> VectorDocument:
    payload: dict[str, str | int | float | bool | list[str]] = {
        "memory_type": MemoryType.EPISODIC.value,
        "event_type": m.event_type,
        "importance": m.importance,
        "source_chat_id": m.source_chat_id or "",
        "access_count": m.access_count,
        "user_rating": m.user_rating,
        "language": m.language,
        "merge_count": m.merge_count,
        "merge_history": m.merge_history,
        "pinned": m.pinned,
        "status": m.status,
        "archived": m.status == "archived",
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        **_scope_payload(m.scope),
        **_lifecycle_payload(m.lifecycle),
    }
    for k, v in m.metadata.items():
        if k not in payload:
            payload[k] = v
    return VectorDocument(
        id=m.id,
        content=m.content,
        vector=m.embedding,
        metadata=payload,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


async def store_conversations_batch(
    memories: list[ConversationMemory],
    vector: VectorStoreProtocol,
    config: MemoryConfig,
    embedding: EmbeddingProtocol,
    cache: EmbeddingCacheProtocol | None,
) -> list[ConversationMemory]:
    """Store conversation memories with dual-embeddings (raw + summary).

    Uses Qdrant named vectors to store both raw_embedding and summary_embedding
    in a single point. For non-Qdrant backends, fallback to summary_embedding only.
    """
    from myrm_agent_harness.toolkits.vector.base import VectorStore

    raw_texts = [m.raw_exchange for m in memories if m.raw_embedding is None]
    summary_texts = [m.content for m in memories if m.summary_embedding is None]

    raw_vecs: list[list[float]] = []
    summary_vecs: list[list[float]] = []

    if raw_texts:
        raw_vecs = await embed_batch(raw_texts, embedding, cache)
    if summary_texts:
        summary_vecs = await embed_batch(summary_texts, embedding, cache)

    raw_idx = 0
    summary_idx = 0
    for m in memories:
        if m.raw_embedding is None:
            m.raw_embedding = raw_vecs[raw_idx]
            raw_idx += 1
        if m.summary_embedding is None:
            m.summary_embedding = summary_vecs[summary_idx]
            summary_idx += 1

    if isinstance(vector, VectorStore) and hasattr(vector, "_client"):
        try:
            from qdrant_client.models import PointStruct

            collection = config.conversation_collection

            import base64

            from myrm_agent_harness.toolkits.memory.compression import (
                externalize_payload,
            )

            points = []
            for m in memories:
                if config.blob_storage_enabled:
                    raw_exchange_value = externalize_payload(
                        m.raw_exchange,
                        threshold=config.blob_storage_threshold,
                        blob_dir=config.blob_storage_path,
                    )
                    was_compressed = (
                        False  # Externalized blobs are not inline compressed
                    )
                else:
                    from myrm_agent_harness.toolkits.memory.compression import (
                        compress_if_needed,
                        is_compressed,
                    )

                    compressed_raw = compress_if_needed(m.raw_exchange)
                    was_compressed = (
                        compressed_raw is not None
                        and isinstance(compressed_raw, bytes)
                        and is_compressed(compressed_raw)
                    )

                    if was_compressed and compressed_raw:
                        raw_exchange_value = base64.b64encode(compressed_raw).decode(
                            "utf-8"
                        )
                    else:
                        raw_exchange_value = m.raw_exchange

                payload: dict[str, str | int | float | bool | list[str]] = {
                    "memory_type": MemoryType.CONVERSATION.value,
                    "content": m.content,
                    "raw_exchange": raw_exchange_value,
                    "raw_exchange_compressed": was_compressed,
                    "timestamp": m.timestamp.isoformat(),
                    "user_turn_only": m.user_turn_only,
                    "related_entities": m.related_entities,
                    "source_chat_id": m.source_chat_id or "",
                    "source_message_id": m.source_message_id or "",
                    "project_id": m.project_id or "",
                    "topic_id": m.topic_id or "",
                    "importance": m.importance,
                    "language": m.language,
                    "status": m.status,
                    "archived": m.status == "archived",
                    "created_at": m.created_at.isoformat(),
                    "updated_at": m.updated_at.isoformat(),
                    **_scope_payload(m.scope),
                    **_lifecycle_payload(m.lifecycle),
                }
                for k, v in m.metadata.items():
                    if k not in payload:
                        payload[k] = v

                point = PointStruct(
                    id=m.id,
                    vector={"raw": m.raw_embedding, "summary": m.summary_embedding},
                    payload=payload,
                )
                points.append(point)

            await vector._with_retry(  # type: ignore[attr-defined]
                vector._client.upsert,  # type: ignore[attr-defined]
                collection_name=collection,
                points=points,
            )
            logger.debug(
                "Stored %d conversation memories with dual-embeddings", len(memories)
            )
            return memories
        except Exception as e:
            logger.error("Failed to store conversations with named vectors: %s", e)
            raise RuntimeError(
                "ConversationMemory requires Qdrant with named vectors. "
                "Ensure collection is created with both 'raw' and 'summary' vector configs."
            ) from e
    else:
        raise NotImplementedError(
            "ConversationMemory storage requires Qdrant backend with named vectors support. "
            "Other vector stores are not currently supported for dual-embedding storage."
        )


def doc_to_episodic(doc: VectorDocument) -> EpisodicMemory:
    meta = doc.metadata
    raw_lang = str(meta.get("language", "en"))
    lang = raw_lang if raw_lang in ("zh", "en") else "en"
    extra: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if k not in _EPISODIC_KNOWN_KEYS and isinstance(v, (str, int, float, bool)):
            extra[k] = v
    return EpisodicMemory(
        id=doc.id,
        user_id=str(meta.get("user_id", "")),
        content=doc.content,
        embedding=doc.vector,
        event_type=str(meta.get("event_type", "conversation")),
        importance=_safe_float(meta.get("importance", 0.5), 0.5),
        source_chat_id=str(meta.get("source_chat_id", "")) or None,
        access_count=_safe_int(meta.get("access_count", 0)),
        user_rating=_safe_float(meta.get("user_rating", 0.5), 0.5),
        pinned=bool(meta.get("pinned", False)),
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        language=lang,
        merge_count=_safe_int(meta.get("merge_count", 0)),
        merge_history=str(meta.get("merge_history", "")),
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
    )


_CONVERSATION_KNOWN_KEYS = frozenset(
    {
        "user_id",
        "archived",
        "content",
        "timestamp",
        "user_turn_only",
        "related_entities",
        "source_chat_id",
        "source_message_id",
        "project_id",
        "topic_id",
        "importance",
        "language",
        "primary_namespace",
        "namespaces",
        "agent_id",
        "channel_id",
        "conversation_id",
        "task_id",
        "memory_tier",
        "digest_kind",
        "evaporation_state",
        "evaporated_at",
        "claim_graph_state",
        "claim_graph_node_id",
        "claim_graph_updated_at",
        "claim_graph_conflict",
    }
)


def doc_to_conversation(
    doc: VectorDocument,
    *,
    include_raw: bool = False,
    config: MemoryConfig | None = None,
) -> ConversationMemory:
    """Convert VectorDocument to ConversationMemory.

    Args:
        doc: Source vector document with conversation metadata.
        include_raw: If True, populate raw_exchange field (default False for lazy loading).

    Returns:
        ConversationMemory instance.

    Note:
        The document must have 'raw_exchange' in metadata for full reconstruction.
        Dual embeddings (raw_embedding, summary_embedding) are stored separately
        in Qdrant named vectors, not in doc.vector.
    """
    from datetime import datetime

    meta = doc.metadata
    raw_lang = str(meta.get("language", "en"))
    lang = raw_lang if raw_lang in ("zh", "en") else "en"
    extra: dict[str, str | int | float | bool] = {}
    for k, v in meta.items():
        if k not in _CONVERSATION_KNOWN_KEYS and isinstance(v, (str, int, float, bool)):
            extra[k] = v

    raw_entities = meta.get("related_entities", [])
    related_entities = raw_entities if isinstance(raw_entities, list) else []

    raw_timestamp = meta.get("timestamp")
    timestamp: datetime
    if isinstance(raw_timestamp, datetime):
        timestamp = raw_timestamp
    elif isinstance(raw_timestamp, str):
        try:
            timestamp = datetime.fromisoformat(raw_timestamp)
        except (ValueError, TypeError):
            timestamp = doc.created_at
    else:
        timestamp = doc.created_at

    raw_exchange_value = ""
    if include_raw:
        raw_data = meta.get("raw_exchange", "")

        # Check if it's an externalized blob pointer
        if isinstance(raw_data, str) and raw_data.startswith("blob://"):
            from myrm_agent_harness.toolkits.memory.compression import (
                internalize_payload,
            )

            blob_dir = config.blob_storage_path if config else "~/.myrm/blobs"
            raw_exchange_value = internalize_payload(raw_data, blob_dir=blob_dir)
        else:
            is_compressed_flag = bool(meta.get("raw_exchange_compressed", False))
            if is_compressed_flag and isinstance(raw_data, str):
                import base64

                from myrm_agent_harness.toolkits.memory.compression import (
                    decompress_payload,
                )

                try:
                    compressed_bytes = base64.b64decode(raw_data)
                    raw_exchange_value = decompress_payload(compressed_bytes)
                except Exception:
                    raw_exchange_value = raw_data
            else:
                raw_exchange_value = str(raw_data) if raw_data else ""

    return ConversationMemory(
        id=doc.id,
        user_id=str(meta.get("user_id", "")),
        content=doc.content,
        raw_exchange=raw_exchange_value,
        raw_embedding=None,
        summary_embedding=doc.vector,
        timestamp=timestamp,
        user_turn_only=bool(meta.get("user_turn_only", True)),
        related_entities=related_entities,
        source_chat_id=str(meta.get("source_chat_id", "")) or None,
        source_message_id=str(meta.get("source_message_id", "")) or None,
        project_id=str(meta.get("project_id", "")) or None,
        topic_id=str(meta.get("topic_id", "")) or None,
        importance=_safe_float(meta.get("importance", 0.5), 0.5),
        language=lang,  # type: ignore[arg-type]
        metadata=extra,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        scope=_scope_from_metadata(meta),
        lifecycle=_lifecycle_from_metadata(meta),
    )


# ======================================================================
# List / Count / Delete by type (API CRUD helpers)
# ======================================================================


async def list_by_type(
    memory_type: MemoryType,
    *,
    limit: int,
    offset: int,
    relational: RelationalStoreProtocol | None,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    namespaces: list[str] | None = None,
    include_archived: bool = False,
) -> list[SemanticMemory | EpisodicMemory | ConversationMemory | ProceduralMemory]:
    if memory_type == MemoryType.PROFILE and relational:
        entries = await relational.list_profiles(
            limit=limit, offset=offset, namespaces=namespaces
        )
        visible_entries = [
            entry for entry in entries if not entry.key.startswith("_system_")
        ]
        return [
            SemanticMemory(
                id=e.id,
                content=f"{e.key}: {e.value}",
                importance=0.8,
                metadata={"key": e.key, "value": str(e.value)},
                created_at=e.created_at,
                updated_at=e.updated_at,
                scope=e.scope,
            )
            for e in visible_entries
        ]
    if memory_type == MemoryType.PROCEDURAL and relational:
        return list(
            await relational.list_rules(
                active_only=True, limit=limit, offset=offset, namespaces=namespaces
            )
        )
    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = (
            config.semantic_collection
            if memory_type == MemoryType.SEMANTIC
            else config.episodic_collection
        )
        docs, _ = await vector.scroll(
            coll,
            limit=limit,
            offset=offset,
            filters=_user_filter(
                namespaces=namespaces, include_archived=include_archived
            ),
        )
        converter = (
            doc_to_semantic if memory_type == MemoryType.SEMANTIC else doc_to_episodic
        )
        return [converter(d) for d in docs]
    if memory_type == MemoryType.CONVERSATION and vector:
        docs, _ = await vector.scroll(
            config.conversation_collection,
            limit=limit,
            offset=offset,
            filters=_user_filter(
                namespaces=namespaces, include_archived=include_archived
            ),
        )
        return [doc_to_conversation(d, config=config) for d in docs]
    if memory_type == MemoryType.TASK_DIGEST and vector:
        filters = _user_filter(namespaces=namespaces, include_archived=include_archived)
        filters["event_type"] = MemoryType.TASK_DIGEST.value
        docs, _ = await vector.scroll(
            config.episodic_collection,
            limit=limit,
            offset=offset,
            filters=filters,
        )
        return [doc_to_episodic(d) for d in docs]
    return []


async def count_by_type(
    memory_type: MemoryType,
    *,
    relational: RelationalStoreProtocol | None,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    namespaces: list[str] | None = None,
    since: datetime | None = None,
) -> int:
    if memory_type == MemoryType.PROFILE and relational:
        return await relational.count_profiles(namespaces=namespaces)
    if memory_type == MemoryType.PROCEDURAL and relational:
        return await relational.count_rules(namespaces=namespaces)
    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = (
            config.semantic_collection
            if memory_type == MemoryType.SEMANTIC
            else config.episodic_collection
        )
        return await vector.count(
            coll, filters=_user_filter(namespaces=namespaces, since=since)
        )
    if memory_type == MemoryType.CONVERSATION and vector:
        return await vector.count(
            config.conversation_collection,
            filters=_user_filter(namespaces=namespaces, since=since),
        )
    if memory_type == MemoryType.TASK_DIGEST and vector:
        filters = _user_filter(namespaces=namespaces, since=since)
        filters["event_type"] = MemoryType.TASK_DIGEST.value
        return await vector.count(config.episodic_collection, filters=filters)
    return 0


async def delete_by_type(
    memory_type: MemoryType,
    *,
    relational: RelationalStoreProtocol | None,
    vector: VectorStoreProtocol | None,
    config: MemoryConfig,
    namespaces: list[str] | None = None,
) -> int:
    if memory_type == MemoryType.PROFILE and relational:
        entries = await relational.list_profiles(namespaces=namespaces)
        count = 0
        for e in entries:
            if await relational.delete_profile(e.key, namespaces=namespaces):
                count += 1
        return count
    if memory_type == MemoryType.PROCEDURAL and relational:
        return await relational.delete_all()
    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = (
            config.semantic_collection
            if memory_type == MemoryType.SEMANTIC
            else config.episodic_collection
        )
        return await vector.delete_by_filter(
            coll, _user_filter(namespaces=namespaces, include_archived=True)
        )
    return 0
