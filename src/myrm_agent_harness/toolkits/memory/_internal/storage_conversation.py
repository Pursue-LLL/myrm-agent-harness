"""Conversation memory storage with dual-embedding support.

[INPUT]
- storage::{embed_batch} (POS: embedding generation with cache)
- storage_converters::{_lifecycle_payload, _scope_payload} (POS: metadata serialization)
- memory.types::{ConversationMemory, MemoryType} (POS: memory data models)

[OUTPUT]
- store_conversations_batch: Batch store with Qdrant named vectors (raw + summary)

[POS]
Conversation memory persistence. Handles dual-embedding generation,
Qdrant named-vector storage, inline compression / external BLOB offloading.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory.types import ConversationMemory, MemoryType

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.config import MemoryConfig
    from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
    from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
    from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol

logger = logging.getLogger(__name__)


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
    from myrm_agent_harness.toolkits.memory._internal.storage import embed_batch
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
