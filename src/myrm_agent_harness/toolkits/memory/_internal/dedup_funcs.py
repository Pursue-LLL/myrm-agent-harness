"""Batch deduplication callables injected into the memory write path.

[INPUT]
- memory._internal.maintenance::dedup_semantics (POS: stateless background maintenance operations)
- memory._internal.bm25_sparse_encoding::{bm25_collection_for, content_to_sparse} (POS: sparse mirror naming and encoding)
- memory._internal.bm25_sparse_index::{is_sparse_authoritative, unwrap_sparse_mirror} (POS: the mirror beneath the wrapper)
- memory._internal.hash_utils::compute_normalized_hash (POS: content normalization and hashing)
- memory._internal.storage::_user_filter (POS: standard user-scoped filter)
- memory.protocols::{EmbeddingCacheProtocol, EmbeddingProtocol, VectorStoreProtocol} (POS: backend contracts)
- memory.config::MemoryConfig (POS: memory configuration)
- memory.types::{SemanticMemory, EpisodicMemory} (POS: memory data models)

[OUTPUT]
- SemanticDedupFunc, EpisodicDedupFunc: Batch deduplication callable types
- build_semantic_deduplicator, build_episodic_deduplicator: Bind the stores to a batch deduplication callable

[POS]
Builds the semantic and episodic batch deduplication callables that MemoryWriter receives.
With an embedding backend the semantic (or LLM-assisted) dedup runs; without one the deployment is
sparse-authoritative, the mirror is the store, and exact normalized-content duplicates are dropped
so repeated extraction of the same fact does not pile up copies. Not part of the public API.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_encoding import (
    bm25_collection_for,
    content_to_sparse,
)
from myrm_agent_harness.toolkits.memory._internal.bm25_sparse_index import (
    is_sparse_authoritative,
    unwrap_sparse_mirror,
)
from myrm_agent_harness.toolkits.memory._internal.hash_utils import compute_normalized_hash
from myrm_agent_harness.toolkits.memory._internal.maintenance import dedup_semantics
from myrm_agent_harness.toolkits.memory._internal.storage import _user_filter
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

logger = logging.getLogger(__name__)

SemanticDedupFunc = Callable[[list[SemanticMemory]], Awaitable[list[SemanticMemory]]]
EpisodicDedupFunc = Callable[[list[EpisodicMemory]], Awaitable[list[EpisodicMemory]]]

# Candidates fetched from the mirror per incoming memory. An exact duplicate always ranks
# (identical text tokenizes identically), so the cap only bounds the work for other content.
_SPARSE_DEDUP_CANDIDATES = 5


async def _drop_sparse_exact_duplicates[MemoryT: (SemanticMemory, EpisodicMemory)](
    memories: list[MemoryT],
    vector: VectorStoreProtocol,
    collection: str,
) -> list[MemoryT]:
    """Drop entries whose normalized content already exists in the sparse mirror.

    Without an embedding backend the mirror is the only store, so the dense similarity
    dedup cannot run. Candidates come from the content's own sparse encoding, and the
    decision is the normalized content hash: an exact duplicate is dropped, while two
    distinct memories are never merged by a similarity threshold. A failing lookup keeps
    the memory, like the dense path.
    """
    inner = unwrap_sparse_mirror(vector)
    mirror = bm25_collection_for(collection)
    kept: list[MemoryT] = []
    seen: set[str] = set()
    for memory in memories:
        namespaces = list(memory.scope.namespaces)
        digest = compute_normalized_hash(memory.content)
        batch_key = f"{','.join(sorted(namespaces))}|{digest}"
        if batch_key in seen:
            continue
        indices, values = content_to_sparse(memory.content)
        duplicated = False
        if indices:
            try:
                hits = await inner.search_sparse(  # type: ignore[attr-defined]
                    mirror,
                    indices,
                    values,
                    limit=_SPARSE_DEDUP_CANDIDATES,
                    filters=_user_filter(namespaces=namespaces or None),
                )
                duplicated = any(compute_normalized_hash(hit.document.content) == digest for hit in hits)
            except Exception as exc:
                # The mirror is created by the first write; a lookup before it is expected.
                if "not found" not in str(exc).lower():
                    logger.warning("Sparse dedup search failed (non-fatal): %s", exc)
        if duplicated:
            continue
        seen.add(batch_key)
        kept.append(memory)
    skipped = len(memories) - len(kept)
    if skipped:
        logger.info("Dedup (sparse mirror): skipped %d/%d exact duplicates", skipped, len(memories))
    return kept


def build_semantic_deduplicator(
    *,
    vector: VectorStoreProtocol | None,
    embedding: EmbeddingProtocol | None,
    config: MemoryConfig,
    cache: EmbeddingCacheProtocol | None,
    deduplicator: object | None,
) -> SemanticDedupFunc:
    async def deduplicate(memories: list[SemanticMemory]) -> list[SemanticMemory]:
        if not memories or vector is None:
            return memories
        if embedding is None:
            if is_sparse_authoritative(vector):
                return await _drop_sparse_exact_duplicates(memories, vector, config.semantic_collection)
            return memories
        if deduplicator is not None:
            return await deduplicator.deduplicate_batch(memories, vector, embedding, config, cache)
        return await dedup_semantics(memories, vector, embedding, config, cache)

    return deduplicate


def build_episodic_deduplicator(
    *,
    vector: VectorStoreProtocol | None,
    embedding: EmbeddingProtocol | None,
    config: MemoryConfig,
    cache: EmbeddingCacheProtocol | None,
    deduplicator: object | None,
) -> EpisodicDedupFunc:
    async def deduplicate(memories: list[EpisodicMemory]) -> list[EpisodicMemory]:
        if not memories or vector is None:
            return memories
        if embedding is None:
            if is_sparse_authoritative(vector):
                return await _drop_sparse_exact_duplicates(memories, vector, config.episodic_collection)
            return memories
        if deduplicator is None:
            return memories
        return await deduplicator.deduplicate_batch(memories, vector, embedding, config, cache)

    return deduplicate
