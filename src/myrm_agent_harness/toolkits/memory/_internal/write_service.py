"""Write-side orchestration for memory persistence.


[INPUT]
- memory._internal.storage::{store_*} (POS: internal vector storage operations)
- memory._internal.memory_scanner::scan_and_clean_memory (POS: content safety scanner)
- memory.transient_fact_boundary::filter_transient_business_memories (POS: L3 write gate for transient business facts)
- memory.strategies.deduplicator::Deduplicator (POS: three-layer dedup: hash→vector→LLM)

[OUTPUT]
- MemoryWriter: Write-side orchestrator (scan, transient business fact L3 write gate, approval routing, explicit/inferred write gates, batch dedup, persistence)

[POS]
Write-side orchestration for memory persistence. Handles memory scanning, transient business fact filtering at the L3 write gate, approval routing,
explicit bypass vs inferred force-pending gates, batch deduplication, and persistence.
Not part of the public API.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal

from myrm_agent_harness.toolkits.memory._internal.maintenance import dedup_semantics
from myrm_agent_harness.toolkits.memory._internal.memory_scanner import (
    MemoryTaintedError,
    scan_and_clean_memory,
)
from myrm_agent_harness.toolkits.memory._internal.scope import (
    MemoryWriteTarget,
    scope_for_write_target,
)
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
    ToolRulePriority,
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

    def _routes_to_pending(self, *, bypass_approval: bool, force_pending: bool) -> bool:
        if bypass_approval:
            return False
        if force_pending:
            return True
        return self._approval_required

    async def store(
        self,
        memory: AnyMemory,
        *,
        bypass_approval: bool = False,
        force_pending: bool = False,
    ) -> AnyMemory:
        self._validate_supported_memory(memory)
        self._attach_current_trace_id(memory)
        bound_memory = self._bind_scope(memory)
        self._validate_write_scope(bound_memory)
        if self._config.security_scan_enabled:
            scan_and_clean_memory(bound_memory, block_threshold=self._config.injection_block_threshold)

        if isinstance(bound_memory, ProceduralMemory):
            self._enforce_agent_self_priority_ceiling(bound_memory)

        if force_pending:
            bound_memory.metadata["write_intent"] = "inferred"

        bound_memory = self._require_transient_fact_allowed(bound_memory)

        if self._routes_to_pending(bypass_approval=bypass_approval, force_pending=force_pending):
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

    async def store_batch(
        self,
        memories: Sequence[AnyMemory],
        *,
        bypass_approval: bool = False,
        force_pending: bool = False,
    ) -> list[AnyMemory]:
        if not memories:
            return []

        for memory in memories:
            self._validate_supported_memory(memory)
            self._attach_current_trace_id(memory)
        bound_memories = [self._bind_scope(memory) for memory in memories]
        for bound_memory in bound_memories:
            self._validate_write_scope(bound_memory)
        safe_memories = self._scan_batch(bound_memories)
        if not safe_memories:
            return []

        for mem in safe_memories:
            if isinstance(mem, ProceduralMemory):
                self._enforce_agent_self_priority_ceiling(mem)
            if force_pending:
                mem.metadata["write_intent"] = "inferred"

        safe_memories = self._filter_transient_business_batch(safe_memories)
        if not safe_memories:
            return []

        if self._routes_to_pending(bypass_approval=bypass_approval, force_pending=force_pending):
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
        subtask_phase: Literal["analyze", "locate", "edit", "verify"] | None = None,
        is_failure_attempt: bool = False,
        failure_reason: str | None = None,
        negative_lesson: str | None = None,
        confidence_tier: Literal["strong", "weak", "shadow"] = "strong",
        write_target: MemoryWriteTarget = "bound",
    ) -> EpisodicMemory:
        return EpisodicMemory(
            content=content,
            event_type=event_type,
            related_entities=related_entities or [],
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            subtask_phase=subtask_phase,
            is_failure_attempt=is_failure_attempt,
            failure_reason=failure_reason,
            negative_lesson=negative_lesson,
            confidence_tier=confidence_tier,
            scope=scope_for_write_target(self._scope, self._namespaces, write_target),
        )

    def build_pitfall(
        self,
        content: str,
        *,
        failure_reason: str,
        negative_lesson: str,
        subtask_phase: Literal["analyze", "locate", "edit", "verify"] | None = None,
        confidence_tier: Literal["strong", "weak", "shadow"] = "strong",
        related_entities: list[str] | None = None,
        source_chat_id: str | None = None,
        source_message_id: str | None = None,
        write_target: MemoryWriteTarget = "bound",
    ) -> EpisodicMemory:
        cleaned_reason = failure_reason.strip() if failure_reason else ""
        cleaned_lesson = negative_lesson.strip() if negative_lesson else ""
        fallback_lesson = cleaned_lesson or cleaned_reason or content.strip()

        return EpisodicMemory(
            content=content,
            event_type="failed_attempt",
            related_entities=related_entities or [],
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            subtask_phase=subtask_phase,
            is_failure_attempt=True,
            failure_reason=cleaned_reason or "Unspecified failure cause",
            negative_lesson=fallback_lesson,
            confidence_tier=confidence_tier,
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

    def _filter_transient_business_batch(self, memories: Sequence[AnyMemory]) -> list[AnyMemory]:
        from myrm_agent_harness.toolkits.memory.agent_surface.transient_fact_boundary import (
            filter_transient_business_memories,
        )

        filtered, dropped = filter_transient_business_memories(list(memories))
        if dropped:
            logger.info(
                "Transient business fact write gate dropped %d memories before persist",
                dropped,
            )
        return filtered

    def _require_transient_fact_allowed(self, memory: AnyMemory) -> AnyMemory:
        filtered = self._filter_transient_business_batch([memory])
        if not filtered:
            from myrm_agent_harness.toolkits.memory.agent_surface.transient_fact_boundary import (
                transient_fact_save_rejection_message,
            )

            raise MemoryError(transient_fact_save_rejection_message())
        return filtered[0]

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
                logger.warning(
                    "[MEMORY_SCAN] Blocked tainted memory in batch: %s...",
                    memory.content[:80],
                )
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
            semantic=semantic,
            episodic=episodic,
            procedural=procedural,
            conversation=conversation,
        )

    def _validate_supported_memory(self, memory: AnyMemory) -> None:
        if not isinstance(
            memory,
            (SemanticMemory, EpisodicMemory, ProceduralMemory, ConversationMemory),
        ):
            raise ValueError(f"Unknown memory type: {type(memory).__name__}")

    def _validate_write_scope(self, memory: AnyMemory) -> None:
        """Refuse writes whose namespaces fall outside this writer's grant.

        A memory may only target the writer's own write scope plus
        shared-capable read namespaces (``global`` or ``shared:*``). Any other
        read-only namespace (e.g. another agent's private space) must not be
        written into; fail loud instead of silently persisting.
        """
        allowed = set(self._scope.namespaces) | {
            ns for ns in self._namespaces if ns == "global" or ns.startswith("shared:")
        }
        if not allowed:
            return
        memory_namespaces = set(memory.scope.namespaces)
        if not memory_namespaces.issubset(allowed):
            raise MemoryError(f"Memory write scope {sorted(memory_namespaces)} exceeds allowed scope {sorted(allowed)}")

    @staticmethod
    def _attach_current_trace_id(memory: AnyMemory) -> None:
        """Inject active execution trace ID into memory if not already set."""
        if hasattr(memory, "trace_id") and not getattr(memory, "trace_id", None):
            try:
                from myrm_agent_harness.observability.tracing import resolve_current_trace_id

                tid = resolve_current_trace_id()
                if tid:
                    memory.trace_id = tid
            except Exception:
                pass

    @staticmethod
    def _enforce_agent_self_priority_ceiling(memory: ProceduralMemory) -> None:
        """Prevent AGENT_SELF rules from claiming CRITICAL priority."""
        if memory.source == RuleSource.AGENT_SELF and memory.tool_rule_priority == ToolRulePriority.CRITICAL:
            memory.tool_rule_priority = ToolRulePriority.HIGH
            logger.warning(
                "Downgraded AGENT_SELF rule from CRITICAL to HIGH: %s",
                memory.content[:60],
            )


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
