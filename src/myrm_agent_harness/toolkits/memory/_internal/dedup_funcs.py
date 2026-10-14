"""Batch deduplication callables injected into the memory write path.

[INPUT]
- memory._internal.maintenance::dedup_semantics (POS: stateless background maintenance operations)
- memory.protocols::{EmbeddingCacheProtocol, EmbeddingProtocol, VectorStoreProtocol} (POS: backend contracts)
- memory.config::MemoryConfig (POS: memory configuration)
- memory.types::{SemanticMemory, EpisodicMemory} (POS: memory data models)

[OUTPUT]
- SemanticDedupFunc, EpisodicDedupFunc: Batch deduplication callable types
- build_semantic_deduplicator, build_episodic_deduplicator: Bind the stores to a batch deduplication callable

[POS]
Builds the semantic and episodic batch deduplication callables that MemoryWriter receives.
Not part of the public API.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from myrm_agent_harness.toolkits.memory._internal.maintenance import dedup_semantics
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.types import EpisodicMemory, SemanticMemory

SemanticDedupFunc = Callable[[list[SemanticMemory]], Awaitable[list[SemanticMemory]]]
EpisodicDedupFunc = Callable[[list[EpisodicMemory]], Awaitable[list[EpisodicMemory]]]


def build_semantic_deduplicator(
    *,
    vector: VectorStoreProtocol | None,
    embedding: EmbeddingProtocol | None,
    config: MemoryConfig,
    cache: EmbeddingCacheProtocol | None,
    deduplicator: object | None,
) -> SemanticDedupFunc:
    async def deduplicate(memories: list[SemanticMemory]) -> list[SemanticMemory]:
        if not memories or vector is None or embedding is None:
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
        if not memories or vector is None or embedding is None or deduplicator is None:
            return memories
        return await deduplicator.deduplicate_batch(memories, vector, embedding, config, cache)

    return deduplicate
