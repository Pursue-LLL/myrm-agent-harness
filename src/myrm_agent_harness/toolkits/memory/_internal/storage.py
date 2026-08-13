"""Internal storage facade.

[INPUT]
- storage_converters::{doc_to_*, semantic_to_doc, episodic_to_doc, _user_filter, ...} (POS: stateless conversion layer)
- storage_search::{search_profile, search_semantic, search_episodic, ...} (POS: search-specific storage operations)
- storage_conversation::{store_conversations_batch} (POS: dual-embedding conversation storage)
- storage_context::{load_context, WORKING_STATE_*} (POS: context loading for agent prompt)
- memory.types::{SemanticMemory, EpisodicMemory, ConversationMemory, ...} (POS: memory data models)

[OUTPUT]
- store_semantic, store_episodic, store_conversations_batch: Vector storage write functions
- doc_to_semantic, doc_to_episodic, doc_to_conversation: Vector → memory model converters
- get_from_vector, delete_from_vector, list_by_type, count_by_type, load_context: Read/query functions
- MemoryError, MemoryNotFoundError: Error types

[POS]
Internal storage facade. Coordinates embedding generation, vector store CRUD,
and re-exports converters/search/context/conversation submodules.
Not part of the public API.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage_context import (
    WORKING_STATE_PROFILE_KEY,
    WORKING_STATE_TTL_DAYS,
    WORKING_STATE_UPDATED_AT_KEY,
    load_context,
)
from myrm_agent_harness.toolkits.memory._internal.storage_conversation import (
    store_conversations_batch,
)
from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
    _lifecycle_from_metadata,
    _lifecycle_payload,
    _safe_float,
    _safe_int,
    _scope_from_metadata,
    _scope_payload,
    _user_filter,
    doc_to_conversation,
    doc_to_episodic,
    doc_to_semantic,
    episodic_to_doc,
    semantic_to_doc,
)
from myrm_agent_harness.toolkits.memory._internal.storage_search import (
    _get_adaptive_threshold,
    search_bm25,
    search_conversation,
    search_episodic,
    search_procedural,
    search_profile,
    search_semantic,
)
from myrm_agent_harness.toolkits.memory.types import (
    ConversationMemory,
    EpisodicMemory,
    MemoryType,
    ProceduralMemory,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.retriever.embedding.window_policy import (
    resolve_embed_window_policy,
    token_counter_for_model,
)
from myrm_agent_harness.toolkits.retriever.splitter.embed_budget import (
    split_for_embedding,
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
    from myrm_agent_harness.toolkits.vector.base import VectorDocument


logger = logging.getLogger(__name__)

__all__ = [
    # Constants
    "WORKING_STATE_PROFILE_KEY",
    "WORKING_STATE_TTL_DAYS",
    "WORKING_STATE_UPDATED_AT_KEY",
    # Errors
    "MemoryError",
    "MemoryNotFoundError",
    "_get_adaptive_threshold",
    "_lifecycle_from_metadata",
    "_lifecycle_payload",
    # Converter internals
    "_safe_float",
    "_safe_int",
    "_scope_from_metadata",
    "_scope_payload",
    "_user_filter",
    "count_by_type",
    "delete_by_type",
    "delete_from_vector",
    "doc_to_conversation",
    "doc_to_episodic",
    # Converters
    "doc_to_semantic",
    "embed_batch",
    # Embed
    "embed_single",
    "episodic_to_doc",
    # CRUD
    "get_from_vector",
    "list_by_type",
    "load_context",
    "search_bm25",
    "search_conversation",
    "search_episodic",
    "search_procedural",
    # Search
    "search_profile",
    "search_semantic",
    "semantic_to_doc",
    "store_conversations_batch",
    "store_episodic",
    "store_episodics_batch",
    # Store
    "store_semantic",
    "store_semantics_batch",
    "update_vector_memory",
]


class MemoryError(Exception):
    """Base exception for memory operations."""


class MemoryNotFoundError(MemoryError):
    """Raised when a memory is not found."""


# ======================================================================
# Embedding helpers
# ======================================================================


def _fit_text_for_embedding(text: str, embedding: EmbeddingProtocol) -> str:
    policy = resolve_embed_window_policy(embedding)
    chunks = split_for_embedding(text, policy)
    if not chunks:
        return text
    if len(chunks) > 1:
        # Count in the model's own budget unit: o200k tokens for BPE models,
        # conservative wordpiece tokens (character count) for CJK wordpiece models.
        counter = token_counter_for_model(policy.model)
        logger.warning(
            "Memory embed input truncated to first chunk (%d -> %d tokens)",
            counter(text),
            counter(chunks[0]),
        )
    return chunks[0]


async def embed_single(
    text: str, embedding: EmbeddingProtocol, cache: EmbeddingCacheProtocol | None
) -> list[float]:
    safe_text = _fit_text_for_embedding(text, embedding)
    if cache is not None:
        cached = await cache.get(safe_text)
        if cached is not None:
            return cached
    vec = await embedding.embed(safe_text)
    if cache is not None:
        await cache.put(safe_text, vec)
    return vec


async def embed_batch(
    texts: list[str], embedding: EmbeddingProtocol, cache: EmbeddingCacheProtocol | None
) -> list[list[float]]:
    if not texts:
        return []
    safe_texts = [_fit_text_for_embedding(text, embedding) for text in texts]
    if cache is None:
        return await embedding.embed_batch(safe_texts)

    cached = await cache.get_batch(safe_texts)
    miss_indices = [i for i, v in enumerate(cached) if v is None]
    if not miss_indices:
        return [v for v in cached if v is not None]

    miss_texts = [safe_texts[i] for i in miss_indices]
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
                properties={"id": memory.id},
            )
            for entity in memory.related_entities:
                entity_node = await graph.get_or_create_node(
                    labels=["Entity"],
                    match_keys=["name"],
                    properties={"name": entity},
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
                    properties={"id": m.id},
                )
                for entity in m.related_entities:
                    entity_node = await graph.get_or_create_node(
                        labels=["Entity"],
                        match_keys=["name"],
                        properties={"name": entity},
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
# List / Count / Delete by type (API CRUD helpers)
# ======================================================================


_SORT_FIELD_MAP: dict[str, str] = {
    "created_at": "_created_ts",
    "updated_at": "_updated_ts",
    "importance": "importance",
}


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
    sort_by: str | None = None,
    sort_order: str = "desc",
    tag_filter: str | None = None,
) -> list[SemanticMemory | EpisodicMemory | ConversationMemory | ProceduralMemory]:
    order_by: tuple[str, str] | None = None
    if sort_by and sort_by in _SORT_FIELD_MAP:
        order_by = (_SORT_FIELD_MAP[sort_by], sort_order)

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

    def _build_filters(base_filters: dict) -> dict:
        if tag_filter:
            base_filters["tags"] = tag_filter.lower()
        return base_filters

    async def _scroll_with_offset(
        coll: str, filters: dict, *, fetch_limit: int, skip: int
    ) -> list[VectorDocument]:
        """Qdrant scroll with integer offset emulation.

        Qdrant scroll is cursor-based (point-ID), not offset-based.
        When ``order_by`` is used we fetch ``skip + fetch_limit`` items
        and discard the first ``skip`` in-memory.  Without ``order_by``
        the existing cursor-based behaviour is used (offset=None for
        first page).
        """
        if order_by is not None and skip > 0:
            docs, _ = await vector.scroll(  # type: ignore[union-attr]
                coll, limit=skip + fetch_limit, filters=filters, order_by=order_by
            )
            return docs[skip:]
        docs, _ = await vector.scroll(  # type: ignore[union-attr]
            coll, limit=fetch_limit, filters=filters, order_by=order_by
        )
        return docs

    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = (
            config.semantic_collection
            if memory_type == MemoryType.SEMANTIC
            else config.episodic_collection
        )
        filters = _build_filters(
            _user_filter(namespaces=namespaces, include_archived=include_archived)
        )
        docs = await _scroll_with_offset(coll, filters, fetch_limit=limit, skip=offset)
        converter = (
            doc_to_semantic if memory_type == MemoryType.SEMANTIC else doc_to_episodic
        )
        return [converter(d) for d in docs]
    if memory_type == MemoryType.CONVERSATION and vector:
        filters = _build_filters(
            _user_filter(namespaces=namespaces, include_archived=include_archived)
        )
        docs = await _scroll_with_offset(
            config.conversation_collection, filters, fetch_limit=limit, skip=offset
        )
        return [doc_to_conversation(d, config=config) for d in docs]
    if memory_type == MemoryType.TASK_DIGEST and vector:
        filters = _build_filters(
            _user_filter(namespaces=namespaces, include_archived=include_archived)
        )
        filters["event_type"] = MemoryType.TASK_DIGEST.value
        docs = await _scroll_with_offset(
            config.episodic_collection, filters, fetch_limit=limit, skip=offset
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
    tag_filter: str | None = None,
) -> int:
    def _apply_tag(f: dict) -> dict:
        if tag_filter:
            f["tags"] = tag_filter.lower()
        return f

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
            coll, filters=_apply_tag(_user_filter(namespaces=namespaces, since=since))
        )
    if memory_type == MemoryType.CONVERSATION and vector:
        return await vector.count(
            config.conversation_collection,
            filters=_apply_tag(_user_filter(namespaces=namespaces, since=since)),
        )
    if memory_type == MemoryType.TASK_DIGEST and vector:
        filters = _apply_tag(_user_filter(namespaces=namespaces, since=since))
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
