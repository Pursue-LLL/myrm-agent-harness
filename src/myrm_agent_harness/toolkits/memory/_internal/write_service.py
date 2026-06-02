"""Write-side orchestration for memory persistence.


[INPUT]
- memory._internal.storage::{store_*} (POS: internal vector storage operations)
- memory._internal.memory_scanner::scan_and_clean_memory (POS: content safety scanner)
- memory.strategies.deduplicator::Deduplicator (POS: three-layer dedup: hash→vector→LLM)

[OUTPUT]
- MemoryWriteService: Write-side orchestrator (scan, approval routing, batch dedup, persistence)

[POS]
Write-side orchestration for memory persistence. Handles memory scanning, approval routing,
batch deduplication, and persistence. Not part of the public API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from myrm_agent_harness.toolkits.memory._internal.maintenance import dedup_semantics
from myrm_agent_harness.toolkits.memory._internal.memory_scanner import MemoryTaintedError, scan_and_clean_memory
from myrm_agent_harness.toolkits.memory._internal.scope import MemoryWriteTarget, scope_for_write_target
from myrm_agent_harness.toolkits.memory._internal.storage import MemoryError
from myrm_agent_harness.toolkits.memory.config import MemoryConfig
from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    ConversationMemory,
    EpisodicMemory,
    MemoryScope,
    ProceduralMemory,
    RuleSource,
    SemanticMemory,
)

logger = logging.getLogger(__name__)

ApprovalSubmitFunc = Callable[[AnyMemory], Awaitable[str]]
BindScopeFunc = Callable[[AnyMemory], AnyMemory]
SemanticDedupFunc = Callable[[list[SemanticMemory]], Awaitable[list[SemanticMemory]]]
EpisodicDedupFunc = Callable[[list[EpisodicMemory]], Awaitable[list[EpisodicMemory]]]


@dataclass(slots=True)
class PartitionedMemories:
    semantic: list[SemanticMemory]
    episodic: list[EpisodicMemory]
    procedural: list[ProceduralMemory]
    conversation: list[ConversationMemory]


class MemoryWriter:
    """Owns write-side validation, batching, and convenience constructors."""

    __slots__ = (
        "_approval_required",
        "_bind_scope",
        "_config",
        "_deduplicate_episodic_batch",
        "_deduplicate_semantic_batch",
        "_namespaces",
        "_scope",
        "_store_conversations_batch",
        "_store_episodic",
        "_store_episodics_batch",
        "_store_procedural",
        "_store_procedurals_batch",
        "_store_semantic",
        "_store_semantics_batch",
        "_submit_pending",
        "_user_id",
    )

    def __init__(
        self,
        *,
        config: MemoryConfig,
        scope: MemoryScope,
        namespaces: list[str],
        approval_required: bool,
        bind_scope_func: BindScopeFunc,
        submit_pending_func: ApprovalSubmitFunc,
        store_semantic_func: Callable[[SemanticMemory], Awaitable[SemanticMemory]],
        store_episodic_func: Callable[[EpisodicMemory], Awaitable[EpisodicMemory]],
        store_procedural_func: Callable[[ProceduralMemory], Awaitable[ProceduralMemory]],
        store_semantics_batch_func: Callable[[list[SemanticMemory]], Awaitable[list[SemanticMemory]]],
        store_episodics_batch_func: Callable[[list[EpisodicMemory]], Awaitable[list[EpisodicMemory]]],
        store_procedurals_batch_func: Callable[[list[ProceduralMemory]], Awaitable[list[ProceduralMemory]]],
        store_conversations_batch_func: Callable[[list[ConversationMemory]], Awaitable[list[ConversationMemory]]],
        deduplicate_semantic_batch_func: SemanticDedupFunc,
        deduplicate_episodic_batch_func: EpisodicDedupFunc,
    ) -> None:
        self._config = config
        self._scope = scope
        self._namespaces = list(namespaces)
        self._approval_required = approval_required
        self._bind_scope = bind_scope_func
        self._submit_pending = submit_pending_func
        self._store_semantic = store_semantic_func
        self._store_episodic = store_episodic_func
        self._store_procedural = store_procedural_func
        self._store_semantics_batch = store_semantics_batch_func
        self._store_episodics_batch = store_episodics_batch_func
        self._store_procedurals_batch = store_procedurals_batch_func
        self._store_conversations_batch = store_conversations_batch_func
        self._deduplicate_semantic_batch = deduplicate_semantic_batch_func
        self._deduplicate_episodic_batch = deduplicate_episodic_batch_func

    async def store(self, memory: AnyMemory, *, bypass_approval: bool = False) -> AnyMemory:
        self._validate_supported_memory(memory)
        bound_memory = self._bind_scope(memory)
        if self._config.security_scan_enabled:
            scan_and_clean_memory(bound_memory, block_threshold=self._config.injection_block_threshold)

        if self._approval_required and not bypass_approval:
            pending_id = await self._submit_pending(bound_memory)
            if not pending_id:
                raise MemoryError("Duplicate pending memory (already awaiting approval)")
            bound_memory.metadata["_pending_id"] = pending_id
            return bound_memory

        if isinstance(bound_memory, SemanticMemory):
            return await self._store_semantic(bound_memory)
        if isinstance(bound_memory, EpisodicMemory):
            return await self._store_episodic(bound_memory)
        if isinstance(bound_memory, ProceduralMemory):
            return await self._store_procedural(bound_memory)
        raise ValueError(f"Unknown memory type: {type(bound_memory).__name__}")

    async def store_batch(self, memories: Sequence[AnyMemory], *, bypass_approval: bool = False) -> list[AnyMemory]:
        if not memories:
            return []

        for memory in memories:
            self._validate_supported_memory(memory)
        bound_memories = [self._bind_scope(memory) for memory in memories]
        safe_memories = self._scan_batch(bound_memories)
        if not safe_memories:
            return []

        if self._approval_required and not bypass_approval:
            results: list[AnyMemory] = []
            for memory in safe_memories:
                pending_id = await self._submit_pending(memory)
                if pending_id:
                    memory.metadata["_pending_id"] = pending_id
                    results.append(memory)
            return results

        partitioned = self._partition_memories(safe_memories)
        if partitioned.semantic:
            partitioned.semantic = await self._deduplicate_semantic_batch(partitioned.semantic)
        if partitioned.episodic:
            partitioned.episodic = await self._deduplicate_episodic_batch(partitioned.episodic)

        tasks: list[asyncio.Task[Sequence[AnyMemory]]] = []
        if partitioned.semantic:
            tasks.append(asyncio.create_task(self._store_semantics_batch(partitioned.semantic)))
        if partitioned.episodic:
            tasks.append(asyncio.create_task(self._store_episodics_batch(partitioned.episodic)))
        if partitioned.procedural:
            tasks.append(asyncio.create_task(self._store_procedurals_batch(partitioned.procedural)))
        if partitioned.conversation:
            tasks.append(asyncio.create_task(self._store_conversations_batch(partitioned.conversation)))

        results = await asyncio.gather(*tasks)
        return [memory for batch in results for memory in batch]

    def build_knowledge(
        self,
        content: str,
        *,
        importance: float = 0.5,
        tags: list[str] | None = None,
        source_chat_id: str | None = None,
        write_target: MemoryWriteTarget = "bound",
    ) -> SemanticMemory:
        return SemanticMemory(
            content=content,
            importance=importance,
            tags=tags or [],
            source_chat_id=source_chat_id,
            scope=scope_for_write_target(self._scope, self._namespaces, write_target),
        )

    def build_event(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        related_entities: list[str] | None = None,
        source_chat_id: str | None = None,
        source_message_id: str | None = None,
        write_target: MemoryWriteTarget = "bound",
    ) -> EpisodicMemory:
        return EpisodicMemory(
            content=content,
            event_type=event_type,
            related_entities=related_entities or [],
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            scope=scope_for_write_target(self._scope, self._namespaces, write_target),
        )

    def build_rule(
        self,
        trigger: str,
        action: str,
        *,
        priority: int = 0,
        trigger_keywords: list[str] | None = None,
        source: RuleSource = RuleSource.USER_EXTRACTED,
    ) -> ProceduralMemory:
        return ProceduralMemory(
            content=f"When: {trigger} → Do: {action}",
            trigger=trigger,
            action=action,
            priority=priority,
            trigger_keywords=trigger_keywords or [],
            source=source,
            scope=self._scope.model_copy(deep=True),
        )

    def _scan_batch(self, memories: Sequence[AnyMemory]) -> list[AnyMemory]:
        if not self._config.security_scan_enabled:
            return list(memories)

        safe_memories: list[AnyMemory] = []
        threshold = self._config.injection_block_threshold
        for memory in memories:
            try:
                scan_and_clean_memory(memory, block_threshold=threshold)
                safe_memories.append(memory)
            except MemoryTaintedError:
                logger.warning("[MEMORY_SCAN] Blocked tainted memory in batch: %s...", memory.content[:80])
        return safe_memories

    def _partition_memories(self, memories: Sequence[AnyMemory]) -> PartitionedMemories:
        semantic: list[SemanticMemory] = []
        episodic: list[EpisodicMemory] = []
        procedural: list[ProceduralMemory] = []
        conversation: list[ConversationMemory] = []

        for memory in memories:
            if isinstance(memory, SemanticMemory):
                semantic.append(memory)
            elif isinstance(memory, EpisodicMemory):
                episodic.append(memory)
            elif isinstance(memory, ProceduralMemory):
                procedural.append(memory)
            elif isinstance(memory, ConversationMemory):
                conversation.append(memory)
            else:
                raise ValueError(f"Unknown memory type: {type(memory).__name__}")

        return PartitionedMemories(
            semantic=semantic, episodic=episodic, procedural=procedural, conversation=conversation
        )

    def _validate_supported_memory(self, memory: AnyMemory) -> None:
        if not isinstance(memory, (SemanticMemory, EpisodicMemory, ProceduralMemory, ConversationMemory)):
            raise ValueError(f"Unknown memory type: {type(memory).__name__}")


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
