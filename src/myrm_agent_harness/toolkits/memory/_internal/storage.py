"""Internal storage operations for MemoryManager.

[INPUT]
- storage_converters::{doc_to_*, semantic_to_doc, episodic_to_doc, _user_filter, ...} (POS: stateless conversion layer)
- storage_search::{search_profile, search_semantic, search_episodic, ...} (POS: search-specific storage operations)
- memory.types::{SemanticMemory, EpisodicMemory, ConversationMemory, ...} (POS: memory data models)

[OUTPUT]
- store_semantic, store_episodic, store_conversation: Vector storage write functions
- doc_to_semantic, doc_to_episodic, doc_to_conversation: Vector → memory model converters
- get_from_vector, delete_from_vector, list_by_type, count_by_type, load_context: Read/query functions
- MemoryError, MemoryNotFoundError: Error types

[POS]
Internal storage facade. Coordinates embedding generation, vector store CRUD,
inline compression, external BLOB storage, and re-exports converters/search.
Not part of the public API.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

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


logger = logging.getLogger(__name__)

__all__ = [
    # Converters
    "doc_to_semantic",
    "doc_to_episodic",
    "doc_to_conversation",
    "semantic_to_doc",
    "episodic_to_doc",
    # Converter internals
    "_safe_float",
    "_safe_int",
    "_user_filter",
    "_scope_payload",
    "_scope_from_metadata",
    "_lifecycle_payload",
    "_lifecycle_from_metadata",
    # Search
    "search_profile",
    "search_semantic",
    "search_episodic",
    "search_procedural",
    "search_bm25",
    "search_conversation",
    "_get_adaptive_threshold",
    # Embed
    "embed_single",
    "embed_batch",
    # Store
    "store_semantic",
    "store_semantics_batch",
    "store_episodic",
    "store_episodics_batch",
    "store_conversations_batch",
    # CRUD
    "get_from_vector",
    "update_vector_memory",
    "delete_from_vector",
    "list_by_type",
    "count_by_type",
    "delete_by_type",
    "load_context",
    # Errors
    "MemoryError",
    "MemoryNotFoundError",
    # Constants
    "WORKING_STATE_PROFILE_KEY",
    "WORKING_STATE_UPDATED_AT_KEY",
    "WORKING_STATE_TTL_DAYS",
]


class MemoryError(Exception):
    """Base exception for memory operations."""


class MemoryNotFoundError(MemoryError):
    """Raised when a memory is not found."""


# ======================================================================
# Embedding helpers
# ======================================================================


async def embed_single(text: str, embedding: EmbeddingProtocol, cache: EmbeddingCacheProtocol | None) -> list[float]:
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
                    match_keys=["name", "user_id"],
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
                        match_keys=["name", "user_id"],
                        properties={"name": entity},
                    )
                    await graph.create_relationship(mem_node.id, entity_node.id, "MENTIONS")
            except Exception as e:
                logger.warning("Graph indexing failed for batch item (non-fatal): %s", e)
    return memories


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
    from myrm_agent_harness.toolkits.memory._internal.storage_converters import (
        _lifecycle_payload as lc_payload,
        _scope_payload as sc_payload,
    )
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
                    was_compressed = False
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
                        raw_exchange_value = base64.b64encode(compressed_raw).decode("utf-8")
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
                    **sc_payload(m.scope),
                    **lc_payload(m.lifecycle),
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
            logger.debug("Stored %d conversation memories with dual-embeddings", len(memories))
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


async def delete_from_vector(collection: str, ids: list[str], vector: VectorStoreProtocol) -> int:
    return await vector.delete(collection, ids)


# ======================================================================
# Context loading
# ======================================================================


WORKING_STATE_PROFILE_KEY = "__working_state"
WORKING_STATE_UPDATED_AT_KEY = "__working_state_updated_at"
WORKING_STATE_TTL_DAYS = 7


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
        tasks["profile"] = asyncio.create_task(relational.list_profiles(namespaces=namespaces))
    if include_rules:
        tasks["rules"] = asyncio.create_task(relational.list_rules(active_only=True, namespaces=namespaces))

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
            working_state: str | None = None
            working_state_updated_at: str | None = None
            for e in entries:
                if not isinstance(e, ProfileEntry):
                    continue
                if e.key == WORKING_STATE_PROFILE_KEY:
                    working_state = e.value
                    continue
                if e.key == WORKING_STATE_UPDATED_AT_KEY:
                    working_state_updated_at = e.value
                    continue
                if e.scope.primary_namespace == "global":
                    global_profile[e.key] = e.value
                else:
                    peer_profile[e.key] = e.value
            ctx["global_profile"] = global_profile
            ctx["peer_profile"] = peer_profile

            if working_state and working_state_updated_at:
                try:
                    updated_at = datetime.fromisoformat(working_state_updated_at)
                    if updated_at.tzinfo is None:
                        updated_at = updated_at.replace(tzinfo=UTC)
                    if (datetime.now(UTC) - updated_at).days < WORKING_STATE_TTL_DAYS:
                        ctx["working_state"] = working_state
                except (ValueError, TypeError):
                    ctx["working_state"] = working_state
            elif working_state:
                ctx["working_state"] = working_state

    if "rules" in results and not isinstance(results["rules"], Exception):
        rules_raw = results["rules"]
        user_rules: list[dict[str, str | int]] = []
        agent_instrs: list[dict[str, str | int]] = []
        if isinstance(rules_raw, list):
            for r in rules_raw:
                if isinstance(r, ProceduralMemory):
                    if r.source == RuleSource.AGENT_SELF:
                        agent_instrs.append({"instruction": r.action, "priority": r.priority})
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
        entries = await relational.list_profiles(limit=limit, offset=offset, namespaces=namespaces)
        visible_entries = [entry for entry in entries if not entry.key.startswith("_system_")]
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
        return list(await relational.list_rules(active_only=True, limit=limit, offset=offset, namespaces=namespaces))
    if memory_type in (MemoryType.SEMANTIC, MemoryType.EPISODIC) and vector:
        coll = config.semantic_collection if memory_type == MemoryType.SEMANTIC else config.episodic_collection
        docs, _ = await vector.scroll(
            coll,
            limit=limit,
            offset=offset,
            filters=_user_filter(namespaces=namespaces, include_archived=include_archived),
        )
        converter = doc_to_semantic if memory_type == MemoryType.SEMANTIC else doc_to_episodic
        return [converter(d) for d in docs]
    if memory_type == MemoryType.CONVERSATION and vector:
        docs, _ = await vector.scroll(
            config.conversation_collection,
            limit=limit,
            offset=offset,
            filters=_user_filter(namespaces=namespaces, include_archived=include_archived),
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
        coll = config.semantic_collection if memory_type == MemoryType.SEMANTIC else config.episodic_collection
        return await vector.count(coll, filters=_user_filter(namespaces=namespaces, since=since))
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
        coll = config.semantic_collection if memory_type == MemoryType.SEMANTIC else config.episodic_collection
        return await vector.delete_by_filter(coll, _user_filter(namespaces=namespaces, include_archived=True))
    return 0
