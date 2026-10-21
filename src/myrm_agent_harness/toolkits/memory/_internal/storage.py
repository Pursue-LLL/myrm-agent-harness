"""Internal storage facade.

[INPUT]
- storage_converters::{doc_to_*, semantic_to_doc, episodic_to_doc, _user_filter, ...} (POS: stateless conversion layer)
- storage_by_type::{list_by_type, count_by_type, delete_by_type} (POS: per-type CRUD dispatch)
- storage_search::{search_profile, search_semantic, search_episodic, ...} (POS: search-specific storage operations)
- storage_conversation::{embed_conversations, store_conversations_batch} (POS: dual-embedding conversation storage)
- storage_context::{load_context, WORKING_STATE_*} (POS: context loading for agent prompt)
- bm25_sparse_index::is_sparse_authoritative (POS: embeddings-less content rewrites)
- memory.types::{SemanticMemory, EpisodicMemory, ConversationMemory, ...} (POS: memory data models)

[OUTPUT]
- store_semantic, store_episodic, store_conversations_batch: Vector storage write functions
- embed_conversations: conversation vectors computed ahead of the write
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
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import is_sparse_authoritative
from myrm_agent_harness.toolkits.memory._internal.storage_by_type import (
    count_by_type,
    delete_by_type,
    list_by_type,
)
from myrm_agent_harness.toolkits.memory._internal.storage_context import (
    WORKING_STATE_PROFILE_KEY,
    WORKING_STATE_TTL_DAYS,
    WORKING_STATE_UPDATED_AT_KEY,
    load_context,
)
from myrm_agent_harness.toolkits.memory._internal.storage_conversation import (
    embed_conversations,
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
    EpisodicMemory,
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
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol


logger = logging.getLogger(__name__)

__all__ = [
    # Constants
    "WORKING_STATE_PROFILE_KEY",
    "WORKING_STATE_TTL_DAYS",
    "WORKING_STATE_UPDATED_AT_KEY",
    # Errors
    "MemoryError",
    "MemoryNotFoundError",
    "MemoryProtectedError",
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
    "embed_conversations",
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


class MemoryProtectedError(MemoryError):
    """Raised when a user-protected memory is written without explicit consent."""


class InvalidPendingEditError(MemoryError):
    """Raised when a reviewer edit cannot be applied to a pending proposal."""


class PendingTargetChangedError(MemoryError):
    """Raised when a proposal's target memory is no longer what the reviewer was shown."""


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


async def embed_single(text: str, embedding: EmbeddingProtocol, cache: EmbeddingCacheProtocol | None) -> list[float]:
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
    await vector.upsert(config.semantic_collection, [semantic_to_doc(m) for m in memories])
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
    await vector.upsert(config.episodic_collection, [episodic_to_doc(m) for m in memories])

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
                    await graph.create_relationship(mem_node.id, entity_node.id, "MENTIONS")
            except Exception as e:
                logger.warning("Graph indexing failed for batch item (non-fatal): %s", e)
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
    embedding: EmbeddingProtocol | None = None,
    cache: EmbeddingCacheProtocol | None = None,
) -> SemanticMemory | EpisodicMemory:
    if content_changed:
        if embedding is not None:
            memory.embedding = await embed_single(memory.content, embedding, cache)
        elif not is_sparse_authoritative(vector):
            raise MemoryError("Embedding backend required when content changed")
    if isinstance(memory, SemanticMemory):
        await vector.upsert(config.semantic_collection, [semantic_to_doc(memory)])
    else:
        await vector.upsert(config.episodic_collection, [episodic_to_doc(memory)])
    return memory


async def delete_from_vector(collection: str, ids: list[str], vector: VectorStoreProtocol) -> int:
    return await vector.delete(collection, ids)
