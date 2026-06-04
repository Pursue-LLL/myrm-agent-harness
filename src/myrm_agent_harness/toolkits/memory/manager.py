"""Unified Memory Manager — pure DI, zero concrete backends.


[INPUT]
- memory._internal.governance_service::GovernanceService (POS: governance orchestration for approvals and profile updates)
- memory._internal.maintenance_service::MaintenanceService (POS: maintenance orchestration for health and cycles)
- memory._internal.scope::{derive_namespaces, bind_scope, build_scope, apply_channel_affinity} (POS: namespace derivation and scope helpers)
- memory._internal.search_service::MemorySearchService (POS: search-side orchestration for retrieval)
- memory._internal.storage::{store_*, doc_to_*, count_by_type, ...} (POS: vector/schema storage operations)
- memory._internal.write_service::MemoryWriteService (POS: write-side orchestration for persistence)
- memory.config::MemoryConfig (POS: memory configuration and policy definitions)

[OUTPUT]
- MemoryManager: Unified facade for all memory operations (store, search, correct, delete, maintain, metadata-scoped id/ref listing, retrieval trace access)

[POS]
Unified memory manager and core facade of the Memory Toolkit. Orchestrates all memory
operations via pure dependency injection — no concrete backends, only protocols.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel

from myrm_agent_harness.core.hooks import HookRegistryProtocol
from myrm_agent_harness.toolkits.memory._internal.governance_service import (
    GovernanceService,
)
from myrm_agent_harness.toolkits.memory._internal.maintenance import run_forgetting
from myrm_agent_harness.toolkits.memory._internal.maintenance_service import (
    MaintenanceConsolidationResult,
    MaintenanceService,
)
from myrm_agent_harness.toolkits.memory._internal.memory_scanner import (
    MemoryTaintedError,
    scan_and_clean_memory,
)
from myrm_agent_harness.toolkits.memory._internal.scope import (
    MemoryWriteTarget,
    apply_channel_affinity,
    bind_scope,
    build_scope,
    derive_namespaces,
)
from myrm_agent_harness.toolkits.memory._internal.search_service import (
    MemorySearchService,
)
from myrm_agent_harness.toolkits.memory._internal.storage import (
    MemoryError,
    MemoryNotFoundError,
    count_by_type,
    delete_from_vector,
    doc_to_episodic,
    doc_to_semantic,
    get_from_vector,
    list_by_type,
    load_context,
    store_episodic,
    store_episodics_batch,
    store_semantic,
    store_semantics_batch,
    update_vector_memory,
)
from myrm_agent_harness.toolkits.memory._internal.storage import (
    delete_by_type as _delete_by_type,
)
from myrm_agent_harness.toolkits.memory._internal.write_service import (
    MemoryWriter,
    build_episodic_deduplicator,
    build_semantic_deduplicator,
)
from myrm_agent_harness.toolkits.memory.archival import ArchivalResult
from myrm_agent_harness.toolkits.memory.backup import (
    BackupMetadata,
    BackupResult,
    MemoryBackupStrategy,
    RestoreResult,
)
from myrm_agent_harness.toolkits.memory.config import (
    AgentMemoryPolicy,
    ConsolidationConfig,
    MemoryConfig,
    RecallMode,
)
from myrm_agent_harness.toolkits.memory.health import (
    HealthScore,
    MaintenanceReport,
    MemorySnapshot,
)
from myrm_agent_harness.toolkits.memory.observability import MemoryRetrievalTrace
from myrm_agent_harness.toolkits.memory.protocols.cache import EmbeddingCacheProtocol
from myrm_agent_harness.toolkits.memory.protocols.embedding import EmbeddingProtocol
from myrm_agent_harness.toolkits.memory.protocols.graph import GraphStoreProtocol
from myrm_agent_harness.toolkits.memory.protocols.relational import (
    RelationalStoreProtocol,
)
from myrm_agent_harness.toolkits.memory.protocols.vector import VectorStoreProtocol
from myrm_agent_harness.toolkits.memory.retriever import MemoryRetriever
from myrm_agent_harness.toolkits.memory.strategies.preference_stability import (
    CueFamily,
    PreferenceCandidate,
    PreferenceCategory,
    PreferenceStabilityStrategy,
)
from myrm_agent_harness.toolkits.memory.strategies.recurrence import (
    RecurrenceDetector,
)
from myrm_agent_harness.toolkits.memory.types import (
    AnyMemory,
    ConversationMemory,
    EpisodicMemory,
    MemoryMutationRef,
    MemoryMutationResult,
    MemoryScope,
    MemorySearchResult,
    MemoryStatus,
    MemoryType,
    PendingRecord,
    ProceduralMemory,
    ProfileAttributeSnapshot,
    RuleSource,
    SemanticMemory,
)
from myrm_agent_harness.toolkits.vector.base import VectorDocument

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from myrm_agent_harness.toolkits.memory.session import MemorySession
    from myrm_agent_harness.toolkits.memory.strategies.preference_stability_store import (
        PreferenceFacetStoreProtocol,
    )

    ConsolidationLLMFunc = Callable[[str, str], Awaitable[str]]
    FTS5SearcherFunc = Callable[[str, int], Awaitable[list[MemorySearchResult]]]

logger = logging.getLogger(__name__)

__all__ = ["MemoryError", "MemoryManager", "MemoryNotFoundError", "MemoryTaintedError"]


def _log_background_task_failure(task: asyncio.Task[object]) -> None:
    if task.cancelled():
        return
    try:
        exc = task.exception()
    except Exception as err:
        logger.warning("Memory manager background task exception lookup failed: %s", err)
        return
    if exc is not None:
        logger.warning("Memory manager background task failed: %s", exc)


class MemoryManager:
    """Orchestrates all memory operations. Bound to a single user via ``user_id``."""

    __slots__ = (
        "_active_session",
        "_approval_required",
        "_cache",
        "_config",
        "_consolidation_llm",
        "_deduplicator",
        "_embedding",
        "_fts5_searcher",
        "_governance",
        "_graph",
        "_last_cited_memory_ids",
        "_maintenance_lock",
        "_maintenance_service",
        "_memory_policy",
        "_namespaces",
        "_preference_strategy",
        "_recall_mode",
        "_recurrence_detector",
        "_relational",
        "_retriever",
        "_scope",
        "_search_service",
        "_session_count",
        "_stores_since_consolidation",
        "_user_id",
        "_vector",
        "_writer",
    )

    def __init__(
        self,
        config: MemoryConfig,
        user_id: str,
        relational: RelationalStoreProtocol | None = None,
        vector: VectorStoreProtocol | None = None,
        graph: GraphStoreProtocol | None = None,
        embedding: EmbeddingProtocol | None = None,
        cache: EmbeddingCacheProtocol | None = None,
        approval_required: bool = False,
        dedup_llm: object | None = None,
        consolidation_llm: BaseChatModel | None = None,
        fts5_searcher: FTS5SearcherFunc | None = None,
        auto_warmup: bool = True,
        namespaces: list[str] | None = None,
        agent_id: str | None = None,
        channel_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
        memory_policy: AgentMemoryPolicy | None = None,
        recall_mode: RecallMode = RecallMode.HYBRID,
        preference_facet_store: PreferenceFacetStoreProtocol | None = None,
    ) -> None:
        self._user_id = user_id
        self._recall_mode = recall_mode
        self._memory_policy = memory_policy
        self._namespaces = derive_namespaces(
            namespaces=namespaces,
            agent_id=agent_id,
            channel_id=channel_id,
            conversation_id=conversation_id,
            task_id=task_id,
            memory_policy=memory_policy,
        )
        self._scope = build_scope(
            namespaces=self._namespaces,
            agent_id=agent_id,
            channel_id=channel_id,
            conversation_id=conversation_id,
            task_id=task_id,
            memory_policy=memory_policy,
        )
        self._config = config
        self._relational = relational
        self._vector = vector
        self._graph = graph
        self._embedding = embedding
        self._cache = cache
        if approval_required and relational is None:
            raise MemoryError("approval_required=True requires a relational backend")
        self._approval_required = approval_required
        self._retriever = MemoryRetriever(config.retrieval)
        self._active_session: MemorySession | None = None
        self._session_count: int = 0
        self._stores_since_consolidation: int = 0
        self._last_cited_memory_ids: list[str] = []
        self._deduplicator = self._init_deduplicator(dedup_llm) if dedup_llm else None
        self._writer = MemoryWriter(
            config=config,
            scope=self._scope,
            namespaces=self._namespaces,
            approval_required=approval_required,
            bind_scope_func=self._bind_scope,
            submit_pending_func=self.submit_pending,
            store_semantic_func=self._store_semantic,
            store_episodic_func=self._store_episodic,
            store_procedural_func=self._store_procedural,
            store_semantics_batch_func=self._store_semantics_batch,
            store_episodics_batch_func=self._store_episodics_batch,
            store_procedurals_batch_func=self._store_procedurals_batch,
            store_conversations_batch_func=self._store_conversations_batch,
            deduplicate_semantic_batch_func=build_semantic_deduplicator(
                vector=vector,
                embedding=embedding,
                config=config,
                cache=cache,
                deduplicator=self._deduplicator,
            ),
            deduplicate_episodic_batch_func=build_episodic_deduplicator(
                vector=vector,
                embedding=embedding,
                config=config,
                cache=cache,
                deduplicator=self._deduplicator,
            ),
        )
        self._search_service = MemorySearchService(
            namespaces=self._namespaces,
            current_channel_id=self._scope.channel_id,
            config=config,
            vector=vector,
            graph=graph,
            relational=relational,
            embedding=embedding,
            cache=cache,
            retriever=self._retriever,
            fts5_searcher=fts5_searcher,
        )
        self._governance = GovernanceService(
            user_id=self._user_id,
            config=config,
            relational=relational,
            namespaces=self._namespaces,
            scope=self._scope,
        )
        self._maintenance_service = MaintenanceService(
            config=config, vector=vector, graph=graph
        )
        self._consolidation_llm: BaseChatModel | None = consolidation_llm
        self._fts5_searcher: FTS5SearcherFunc | None = fts5_searcher
        self._maintenance_lock = asyncio.Lock()
        self._preference_strategy: PreferenceStabilityStrategy | None = (
            PreferenceStabilityStrategy(preference_facet_store)
            if preference_facet_store is not None
            else None
        )
        self._recurrence_detector: RecurrenceDetector | None = (
            self._init_recurrence_detector(config)
            if config.recurrence.enabled and vector is not None and embedding is not None
            else None
        )

        if (
            auto_warmup
            and config.dedup.warmup_cache
            and cache is not None
            and vector is not None
            and embedding is not None
        ):
            task = asyncio.create_task(self._warmup_embedding_cache())
            task.add_done_callback(_log_background_task_failure)

    def _init_deduplicator(self, llm: object) -> object | None:
        try:
            from myrm_agent_harness.toolkits.memory.strategies.deduplicator import (
                SmartDeduplicator,
            )

            dedup_params = self._config.dedup
            return SmartDeduplicator(
                llm,
                high_threshold=dedup_params.high_threshold,
                low_threshold=dedup_params.low_threshold,
                time_window_hours=dedup_params.time_window_hours,
                max_cache_size=dedup_params.hash_cache_capacity,
                normalization_level=int(dedup_params.normalization_level),
                adaptive_capacity=dedup_params.adaptive_capacity,
                capacity_multiplier=dedup_params.capacity_multiplier,
                persist_hash_cache=dedup_params.persist_hash_cache,
                hash_cache_path=dedup_params.hash_cache_path,
            )
        except Exception as e:
            logger.warning("Failed to initialize deduplicator: %s", e)
            return None

    def _init_recurrence_detector(self, config: MemoryConfig) -> RecurrenceDetector:
        """Initialize recurrence detector with config params."""
        rc = config.recurrence
        return RecurrenceDetector(
            embedding=self._embedding,  # type: ignore[arg-type]
            vector=self._vector,  # type: ignore[arg-type]
            collection_prefix=config.collection_prefix,
            similarity_threshold=rc.similarity_threshold,
            recurrence_k=rc.recurrence_k,
            buffer_capacity=rc.buffer_capacity,
            importance_preemption=rc.importance_preemption,
        )

    @property
    def user_id(self) -> str | None:
        return self._user_id

    @property
    def namespaces(self) -> list[str]:
        return self._namespaces

    @property
    def scope(self) -> MemoryScope:
        return self._scope.model_copy(deep=True)

    @property
    def memory_policy(self) -> AgentMemoryPolicy | None:
        return self._memory_policy

    @property
    def config(self) -> MemoryConfig:
        return self._config

    @property
    def recall_mode(self) -> RecallMode:
        return self._recall_mode

    @property
    def last_cited_memory_ids(self) -> list[str]:
        """Memory IDs cited in the most recent memory_recall tool call."""
        return self._last_cited_memory_ids

    @property
    def last_retrieval_trace(self) -> MemoryRetrievalTrace | None:
        """Retrieval trace from the most recent search call."""
        return self._search_service.last_trace

    def set_last_cited_memory_ids(self, ids: list[str]) -> None:
        """Record cited memory IDs from the latest memory_recall result."""
        self._last_cited_memory_ids = ids

    @property
    def has_relational(self) -> bool:
        return self._relational is not None

    @property
    def has_vector(self) -> bool:
        return self._vector is not None and self._embedding is not None

    @property
    def has_graph(self) -> bool:
        return self._graph is not None

    def get_enabled_types(self) -> list[MemoryType]:
        types: list[MemoryType] = []
        if self.has_relational:
            types.extend([MemoryType.PROFILE, MemoryType.PROCEDURAL])
        if self.has_vector:
            types.extend([MemoryType.SEMANTIC, MemoryType.EPISODIC])
        return types

    @property
    def approval_required(self) -> bool:
        return self._approval_required

    async def submit_pending(self, memory: AnyMemory) -> str:
        """Submit a memory for approval. Returns pending ID, or '' if duplicate."""
        return await self._governance.submit_pending(memory)

    async def approve(self, pending_id: str) -> AnyMemory | None:
        """Approve a pending memory and persist to permanent storage."""
        return await self._governance.approve(
            pending_id,
            store_func=lambda memory: self.store(memory, _bypass_approval=True),
        )

    async def reject(self, pending_id: str) -> None:
        await self._governance.reject(pending_id)

    async def list_pending(self, *, limit: int = 50) -> list[PendingRecord]:
        return await self._governance.list_pending(limit=limit)

    async def count_pending(self) -> int:
        return await self._governance.count_pending()

    async def batch_approve(self, pending_ids: list[str]) -> tuple[int, list[str]]:
        """Returns (success_count, failed_ids)."""
        return await self._governance.batch_approve(
            pending_ids, approve_func=self.approve
        )

    async def batch_reject(self, pending_ids: list[str]) -> int:
        return await self._governance.batch_reject(pending_ids)

    def begin_session(
        self,
        chat_id: str,
        hook_registry: HookRegistryProtocol | None = None,
    ) -> MemorySession:
        from myrm_agent_harness.core.hooks.types import CallableHookDefinition, HookEvent
        from myrm_agent_harness.toolkits.memory.session import MemorySession
        from myrm_agent_harness.toolkits.memory.tool_capture import ToolMemoryCaptureHook

        if self._active_session is not None:
            self._active_session.discard()
        self._last_cited_memory_ids = []

        hook = ToolMemoryCaptureHook()
        if hook_registry is not None:
            if not any(isinstance(h, CallableHookDefinition) and h.fn.__name__ == "on_post_tool_failure" for h in hook_registry._hooks.get(HookEvent.POST_TOOL_USE_FAILURE, [])):
                hook_registry.register(HookEvent.POST_TOOL_USE_FAILURE, CallableHookDefinition(fn=hook.on_post_tool_failure))
            if not any(isinstance(h, CallableHookDefinition) and h.fn.__name__ == "on_post_tool_use" for h in hook_registry._hooks.get(HookEvent.POST_TOOL_USE, [])):
                hook_registry.register(HookEvent.POST_TOOL_USE, CallableHookDefinition(fn=hook.on_post_tool_use))
            if not any(isinstance(h, CallableHookDefinition) and h.fn.__name__ == "on_user_turn" for h in hook_registry._hooks.get(HookEvent.USER_TURN, [])):
                hook_registry.register(HookEvent.USER_TURN, CallableHookDefinition(fn=hook.on_user_turn))

        self._active_session = MemorySession(manager=self, chat_id=chat_id, tool_capture_hook=hook)
        return self._active_session

    async def end_session(self) -> list[AnyMemory]:
        if self._active_session is None:
            return []
        session = self._active_session
        self._active_session = None
        persisted = await session.flush()
        self._session_count += 1
        if self._preference_strategy is not None:
            try:
                promoted = await self._preference_strategy.micro_rebuild()
                if promoted:
                    logger.info(
                        "Preference micro-rebuild: %d promoted to Active", promoted
                    )
            except Exception as e:
                logger.warning("Preference micro-rebuild failed (non-fatal): %s", e)
        if (
            self._session_count % self._config.forgetting_interval == 0
            and self._vector is not None
        ):
            task = asyncio.create_task(self._guarded_forgetting())
            task.add_done_callback(_log_background_task_failure)
        self._maybe_consolidate()
        return persisted

    async def check_session_recurrence(self, session_summary: str) -> None:
        """Check for topic recurrence across sessions and auto-store consolidated memory.

        Should be called by the agent after session end with a summary of the session's
        key topics (typically derived from user messages, not stored memories).

        This is a fire-and-forget operation — failures are logged and silently ignored.
        """
        if not self._recurrence_detector or not session_summary.strip():
            return
        await self._check_recurrence_and_store(session_summary)

    async def _check_recurrence_and_store(self, summary: str) -> None:
        """Run recurrence detection and store consolidated memory if triggered."""
        if self._recurrence_detector is None:
            return
        try:
            llm_func = self._build_recurrence_llm_func()
            result = await self._recurrence_detector.check_recurrence(
                summary, llm_func=llm_func
            )

            if not result.triggered or not result.consolidated_content:
                return

            logger.info(
                "Recurrence triggered (count=%d): storing consolidated memory",
                result.recurrence_count,
            )
            memory = SemanticMemory(
                content=result.consolidated_content,
                memory_type=MemoryType.SEMANTIC,
                importance=0.8,
                source="recurrence_consolidation",
            )
            await self.store(memory, _bypass_approval=True)
        except Exception as e:
            logger.warning("Recurrence check failed (non-fatal): %s", e)

    def _build_recurrence_llm_func(self) -> Callable[[str, str], Awaitable[str]] | None:
        """Build LLM function for recurrence consolidation using consolidation_llm."""
        if self._consolidation_llm is None:
            return None

        async def _call(system_prompt: str, user_prompt: str) -> str:
            from langchain_core.messages import HumanMessage, SystemMessage
            messages = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
            response = await self._consolidation_llm.ainvoke(messages)  # type: ignore[union-attr]
            return str(response.content)

        return _call

    async def _guarded_forgetting(self) -> None:
        """Run forgetting with maintenance lock protection."""
        if self._maintenance_lock.locked():
            return
        async with self._maintenance_lock:
            if self._vector is None:
                return
            await run_forgetting(self._vector, self._config, self._graph)

    async def _submit_preference_candidate(self, memory: AnyMemory) -> None:
        """Submit a SemanticMemory with preference_type as a PreferenceCandidate."""
        if self._preference_strategy is None:
            return
        if not isinstance(memory, SemanticMemory):
            return
        if not memory.preference_type:
            return
        try:
            cue = (
                CueFamily(memory.preference_type)
                if memory.preference_type in ("explicit", "implicit")
                else CueFamily.INFERRED
            )
            candidate = PreferenceCandidate(
                key=memory.content[:80],
                value=memory.content,
                category=_infer_preference_category(memory),
                cue=cue,
                strength=memory.preference_strength or 0.5,
                memory_id=memory.id,
                content=memory.content,
            )
            await self._preference_strategy.submit_candidate(candidate)
        except Exception as e:
            logger.warning("Preference candidate submission failed (non-fatal): %s", e)

    def _maybe_consolidate(self) -> None:
        """Schedule background consolidation if enabled and LLM is available."""
        if self._consolidation_llm is None:
            return
        cfg = self._config.consolidation
        if not cfg.enabled:
            return
        if not (self.has_vector and self.has_relational):
            return
        task = asyncio.create_task(self._guarded_consolidation(cfg))
        task.add_done_callback(_log_background_task_failure)

    async def _guarded_consolidation(self, cfg: ConsolidationConfig) -> None:
        """Run consolidation with maintenance lock protection."""
        if self._maintenance_lock.locked():
            return
        async with self._maintenance_lock:
            await self._run_consolidation_safe(cfg)

    @property
    def active_session(self) -> MemorySession | None:
        return self._active_session

    async def store(
        self, memory: AnyMemory, *, _bypass_approval: bool = False
    ) -> AnyMemory:
        result = await self._writer.store(memory, bypass_approval=_bypass_approval)
        self._stores_since_consolidation += 1
        trigger = self._config.consolidation.message_count_trigger
        if trigger > 0 and self._stores_since_consolidation >= trigger:
            self._stores_since_consolidation = 0
            self._maybe_consolidate()
        await self._submit_preference_candidate(result)
        return result

    async def store_batch(self, memories: Sequence[AnyMemory], *, _bypass_approval: bool = False) -> list[AnyMemory]:
        result = await self._writer.store_batch(memories, bypass_approval=_bypass_approval)
        self._stores_since_consolidation += len(memories)
        trigger = self._config.consolidation.message_count_trigger
        if trigger > 0 and self._stores_since_consolidation >= trigger:
            self._stores_since_consolidation = 0
            self._maybe_consolidate()
        for mem in result:
            await self._submit_preference_candidate(mem)
        return result

    async def search(
        self,
        query: str,
        *,
        memory_types: list[MemoryType] | None = None,
        limit: int = 10,
        use_rrf: bool = True,
        include_raw: bool = False,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[MemorySearchResult]:
        session_chat_id = self._active_session.chat_id if self._active_session else None
        return await self._search_service.search(
            query,
            memory_types=memory_types or self.get_enabled_types(),
            memory_types_unspecified=memory_types is None,
            limit=limit,
            use_rrf=use_rrf,
            include_raw=include_raw,
            since=since,
            until=until,
            current_chat_id=session_chat_id,
        )

    async def get_context(
        self,
        *,
        include_profile: bool = True,
        include_rules: bool = True,
        include_agent_instructions: bool = True,
    ) -> dict[str, object]:
        if not self.has_relational:
            return {"global_profile": {}, "peer_profile": {}, "rules": [], "agent_instructions": []}
        assert self._relational is not None
        ctx = await load_context(
            self._relational,
            include_profile=include_profile,
            include_rules=include_rules,
            include_agent_instructions=include_agent_instructions,
            namespaces=self._namespaces,
        )


        return ctx

    async def get_learned_context(self) -> dict[str, list[dict[str, str]]]:
        """Retrieve auto-extracted memories for always-on injection.

        Returns preference-bearing SemanticMemories and active ProceduralMemories,
        sorted by importance and truncated to max_learned_context_chars.

        When PreferenceStabilityStrategy is active, uses stability-verified Active
        preferences instead of raw vector scroll for higher precision.
        """
        rules_task = (
            asyncio.create_task(
                self._relational.list_rules(
                    active_only=True, limit=50, namespaces=self._namespaces
                )
            )
            if self._relational
            else None
        )

        preference_strategy = self._preference_strategy
        use_stability = preference_strategy is not None
        docs_task = (
            asyncio.create_task(
                self._vector.scroll(
                    self._config.semantic_collection,
                    limit=200,
                    filters={"archived": False, "namespaces": self._namespaces},
                )
            )
            if self._vector and not use_stability
            else None
        )

        rules: list[ProceduralMemory] = []
        if rules_task:
            try:
                rules = await rules_task
            except Exception as e:
                logger.warning("Learned context rules query error: %s", e)

        preferences: list[SemanticMemory] = []
        if preference_strategy is not None:
            try:
                active_facets = await preference_strategy.get_active_preferences()
                for facet in active_facets:
                    pref = SemanticMemory(
                        id=facet.id,
                        content=facet.value,
                        preference_type=facet.cue.value,
                        preference_strength=min(facet.stability / 2.0, 1.0),
                        importance=0.8,
                    )
                    preferences.append(pref)
            except Exception as e:
                logger.warning("Learned context stability preferences error: %s", e)
        elif docs_task:
            try:
                docs, _ = await docs_task
                for d in docs:
                    meta = d.metadata
                    if meta.get("preference_type") not in ("explicit", "implicit"):
                        continue
                    try:
                        strength = float(meta.get("preference_strength", 0))
                    except (TypeError, ValueError):
                        continue
                    if strength > 0:
                        preferences.append(doc_to_semantic(d))
            except Exception as e:
                logger.warning("Learned context preferences query error: %s", e)

        rules.sort(key=lambda r: r.priority, reverse=True)
        preferences.sort(
            key=lambda m: m.importance * m.preference_strength, reverse=True
        )

        base_budget = self._config.max_learned_context_chars
        if self._config.model_context_tokens:
            budget = max(base_budget, self._config.model_context_tokens // 30)
        else:
            budget = base_budget
        used = 0

        learned_rules: list[dict[str, str]] = []
        for rule in rules:
            entry_len = len(rule.trigger) + len(rule.action) + 20
            if used + entry_len > budget:
                break
            entry: dict[str, str] = {
                "id": rule.id,
                "trigger": rule.trigger,
                "action": rule.action,
                "created_at": rule.created_at.isoformat(),
            }
            if hasattr(rule, "reasoning") and rule.reasoning:
                entry["reasoning"] = rule.reasoning
            if hasattr(rule, "application") and rule.application:
                entry["application"] = rule.application
            if rule.tool_name:
                entry["tool_name"] = rule.tool_name
            if rule.tool_rule_priority:
                entry["tool_rule_priority"] = rule.tool_rule_priority.value
            learned_rules.append(entry)
            used += entry_len

        corrections = [p for p in preferences if p.source_error]
        normal_prefs = [p for p in preferences if not p.source_error]
        corrections.sort(key=lambda m: m.created_at, reverse=True)

        learned_prefs: list[dict[str, str]] = []
        max_corrections = self._config.max_corrections
        for correction_count, pref in enumerate(corrections):
            if correction_count >= max_corrections or used + len(pref.content) > budget:
                break
            learned_prefs.append(
                {
                    "id": pref.id,
                    "content": pref.content,
                    "type": pref.preference_type or "implicit",
                    "source_error": pref.source_error or "",
                    "created_at": pref.created_at.isoformat(),
                }
            )
            used += len(pref.content)

        for pref in normal_prefs:
            if used + len(pref.content) > budget:
                break
            learned_prefs.append(
                {
                    "id": pref.id,
                    "content": pref.content,
                    "type": pref.preference_type or "implicit",
                    "created_at": pref.created_at.isoformat(),
                }
            )
            used += len(pref.content)

        return {"learned_rules": learned_rules, "learned_preferences": learned_prefs}

    async def get_tool_rules(
        self,
        tool_name: str,
        *,
        limit: int = 30,
    ) -> list[ProceduralMemory]:
        """Retrieve active procedural rules scoped to a specific tool."""
        if not self._relational:
            return []
        try:
            return await self._relational.list_rules_by_tool(
                tool_name, active_only=True, limit=limit, namespaces=self._namespaces
            )
        except Exception as e:
            logger.warning("get_tool_rules failed for %s: %s", tool_name, e)
            return []

    async def record_citations(self, memory_ids: list[str]) -> int:
        """Explicitly record LLM citations for lifecycle decay tracking.
        
        Bumps the access_count and last_accessed_at for the cited memories.
        Returns the number of successfully updated memories.
        """
        if not memory_ids:
            return 0

        updated_count = 0
        now = datetime.now(UTC)
        for mem_id in memory_ids:
            try:
                mem = await self.get_memory(mem_id)
                if not mem:
                    continue
                mem.access_count += 1
                mem.last_accessed_at = now
                if hasattr(mem, "memory_type"):
                    await self.update_memory(mem.id)  # Update just saves it via model_copy
                    # Actually update_memory does not take access_count as kwarg.
                    # Let's bypass update_memory and use the writer directly for this internal bump.
                    if isinstance(mem, (SemanticMemory, EpisodicMemory)):
                        v, e = self._vec()
                        await update_vector_memory(
                            self._bind_scope(mem),
                            False,
                            v,
                            self._config,
                            e,
                            self._cache,
                        )
                    elif isinstance(mem, ProceduralMemory):
                        await self._rel().update_rule(mem.id, mem)
                    updated_count += 1
            except Exception as e:
                logger.warning("Failed to record citation for memory %s: %s", mem_id, e)

        return updated_count

    # ── Convenience: Profile ──

    async def set_profile_attribute(self, key: str, value: str) -> str | None:
        """Set a profile attribute. Returns pending_id if approval is required, else None."""
        return await self._governance.set_profile_attribute(
            key, value, approval_required=self.approval_required
        )

    async def get_profile_attribute(self, key: str) -> str | None:
        return await self._governance.get_profile_attribute(key)

    async def get_profile_attribute_snapshot(self, key: str) -> ProfileAttributeSnapshot:
        return await self._rel().get_profile_snapshot(key, namespaces=self._namespaces)

    async def restore_profile_attributes(self, values: dict[str, str | None]) -> int:
        """Restore profile keys directly for audited rollback flows."""

        restored = 0
        relational = self._rel()
        for key, value in values.items():
            if value is None:
                if await relational.delete_profile(key, namespaces=self._namespaces):
                    restored += 1
            else:
                await relational.set_profile(key, value, scope=self._scope)
                restored += 1
        return restored

    # ── Convenience: Knowledge (Semantic) ──

    async def add_knowledge(
        self,
        content: str,
        *,
        importance: float = 0.5,
        tags: list[str] | None = None,
        source_chat_id: str | None = None,
        write_target: MemoryWriteTarget = "bound",
    ) -> SemanticMemory:
        memory = self._writer.build_knowledge(
            content=content,
            importance=importance,
            tags=tags,
            source_chat_id=source_chat_id,
            write_target=write_target,
        )
        result = await self.store(memory)
        return result if isinstance(result, SemanticMemory) else memory

    # ── Convenience: Events (Episodic) ──

    async def add_event(
        self,
        content: str,
        *,
        event_type: str = "conversation",
        related_entities: list[str] | None = None,
        source_chat_id: str | None = None,
        source_message_id: str | None = None,
        write_target: MemoryWriteTarget = "bound",
    ) -> EpisodicMemory:
        memory = self._writer.build_event(
            content=content,
            event_type=event_type,
            related_entities=related_entities,
            source_chat_id=source_chat_id,
            source_message_id=source_message_id,
            write_target=write_target,
        )
        result = await self.store(memory)
        return result if isinstance(result, EpisodicMemory) else memory

    # ── Convenience: Rules (Procedural) ──

    async def add_rule(
        self,
        trigger: str,
        action: str,
        *,
        priority: int = 0,
        trigger_keywords: list[str] | None = None,
        source: RuleSource = RuleSource.USER_EXTRACTED,
    ) -> ProceduralMemory:
        memory = self._writer.build_rule(
            trigger=trigger,
            action=action,
            priority=priority,
            trigger_keywords=trigger_keywords,
            source=source,
        )
        result = await self.store(memory)
        return result if isinstance(result, ProceduralMemory) else memory

    # ── Delete ──

    async def delete_memory(
        self, collection: str, ids: list[str], *, allow_pinned: bool = True
    ) -> int:
        if self._vector is None:
            raise MemoryError("Vector backend is required but not provided")
        if ids:
            docs = await self._vector.get(collection, ids) or []
            owned_ids = [
                doc.id
                for doc in docs
                if self._owns_vector_doc(doc) and (allow_pinned or not doc.metadata.get("pinned"))
            ]
            if not owned_ids:
                return 0
            ids = owned_ids
        deleted = await delete_from_vector(collection, ids, self._vector)
        if self._graph is not None:
            for memory_id in ids:
                try:
                    await self._graph.delete_subgraph(memory_id)
                except Exception as e:
                    logger.warning("Graph cleanup failed for %s: %s", memory_id, e)
        return deleted

    async def delete_rule(self, rule_id: str, *, allow_pinned: bool = True) -> bool:
        if not allow_pinned:
            rule = await self._rel().get_rule(rule_id, namespaces=self._namespaces)
            if rule is not None and rule.pinned:
                return False
        return await self._rel().delete_rule(rule_id)

    async def delete_memories_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        *,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> dict[str, int]:
        """Delete owned memories whose flat metadata contains an exact key/value pair."""

        selected_types = tuple(
            memory_types
            or (
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
                MemoryType.CONVERSATION,
                MemoryType.PROCEDURAL,
            )
        )
        counts: dict[str, int] = {}
        vector_collections: dict[MemoryType, str] = {
            MemoryType.SEMANTIC: self._config.semantic_collection,
            MemoryType.EPISODIC: self._config.episodic_collection,
            MemoryType.CONVERSATION: self._config.conversation_collection,
        }

        if self._vector is not None:
            filters = {metadata_key: metadata_value}
            for memory_type, collection in vector_collections.items():
                if memory_type not in selected_types:
                    continue
                memory_ids = [
                    doc_id
                    for doc_id, owned in await self._collect_vector_ids(collection, filters)
                    if owned
                ]
                deleted = await self.delete_memory(collection, memory_ids)
                counts[memory_type.value] = deleted

        if MemoryType.PROCEDURAL in selected_types and self._relational is not None:
            matching_rule_ids: list[str] = []
            offset = 0
            while True:
                rules = await self._relational.list_rules(
                    active_only=False,
                    limit=500,
                    offset=offset,
                    namespaces=self._namespaces,
                )
                if not rules:
                    break
                for rule in rules:
                    if rule.metadata.get(metadata_key) == metadata_value:
                        matching_rule_ids.append(rule.id)
                offset += len(rules)
            deleted_rules = 0
            for rule_id in matching_rule_ids:
                if await self._relational.delete_rule(rule_id):
                    deleted_rules += 1
            counts[MemoryType.PROCEDURAL.value] = deleted_rules

        return counts

    async def delete_memories_by_ids(self, memory_ids_by_type: dict[str, list[str]]) -> MemoryMutationResult:
        """Delete owned memories by explicit type/id refs and return exact outcomes."""

        result = MemoryMutationResult()
        vector_collections: dict[str, str] = {
            MemoryType.SEMANTIC.value: self._config.semantic_collection,
            MemoryType.EPISODIC.value: self._config.episodic_collection,
            MemoryType.CONVERSATION.value: self._config.conversation_collection,
        }
        for memory_type, memory_ids in memory_ids_by_type.items():
            ids = [memory_id for memory_id in memory_ids if memory_id]
            if not ids:
                continue
            collection = vector_collections.get(memory_type)
            if collection is not None:
                await self._delete_vector_memories_by_ids(
                    result,
                    memory_type=memory_type,
                    collection=collection,
                    ids=ids,
                )
                continue
            if memory_type == MemoryType.PROCEDURAL.value and self._relational is not None:
                for rule_id in ids:
                    rule = await self._relational.get_rule(rule_id, namespaces=self._namespaces)
                    if rule is None:
                        result.missing_refs.append(
                            MemoryMutationRef(
                                memory_type=memory_type,
                                memory_id=rule_id,
                                backend="relational",
                                reason="not_found",
                            )
                        )
                        continue
                    if await self._relational.delete_rule(rule_id):
                        result.deleted_refs.append(
                            MemoryMutationRef(memory_type=memory_type, memory_id=rule_id, backend="relational")
                        )
                    else:
                        result.failed_refs.append(
                            MemoryMutationRef(
                                memory_type=memory_type,
                                memory_id=rule_id,
                                backend="relational",
                                reason="delete_failed",
                            )
                        )
                continue
            for memory_id in ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend="unavailable",
                        reason="backend_unavailable",
                    )
                )
        return result

    async def _delete_vector_memories_by_ids(
        self,
        result: MemoryMutationResult,
        *,
        memory_type: str,
        collection: str,
        ids: list[str],
    ) -> None:
        if self._vector is None:
            for memory_id in ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="backend_unavailable",
                    )
                )
            return
        try:
            docs = await self._vector.get(collection, ids) or []
        except Exception as e:
            for memory_id in ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason=f"read_failed:{type(e).__name__}",
                    )
                )
            return

        docs_by_id = {doc.id: doc for doc in docs}
        for memory_id in ids:
            doc = docs_by_id.get(memory_id)
            if doc is None:
                result.missing_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="not_found",
                    )
                )
            elif not self._owns_vector_doc(doc):
                result.forbidden_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="scope_mismatch",
                    )
                )

        owned_ids = [memory_id for memory_id, doc in docs_by_id.items() if self._owns_vector_doc(doc)]
        if not owned_ids:
            return
        try:
            deleted_count = await delete_from_vector(collection, owned_ids, self._vector)
        except Exception as e:
            for memory_id in owned_ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason=f"delete_failed:{type(e).__name__}",
                    )
                )
            return

        if deleted_count == len(owned_ids):
            deleted_ids = owned_ids
        else:
            remaining_docs = await self._vector.get(collection, owned_ids) or []
            remaining_ids = {doc.id for doc in remaining_docs}
            deleted_ids = [memory_id for memory_id in owned_ids if memory_id not in remaining_ids]
            for memory_id in remaining_ids:
                result.failed_refs.append(
                    MemoryMutationRef(
                        memory_type=memory_type,
                        memory_id=memory_id,
                        backend=collection,
                        reason="delete_incomplete",
                    )
                )

        for memory_id in deleted_ids:
            result.deleted_refs.append(
                MemoryMutationRef(memory_type=memory_type, memory_id=memory_id, backend=collection)
            )
            if self._graph is not None:
                try:
                    await self._graph.delete_subgraph(memory_id)
                except Exception as e:
                    logger.warning("Graph cleanup failed for %s: %s", memory_id, e)

    async def list_memory_ids_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        *,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> dict[str, list[str]]:
        """List owned memory ids whose flat metadata contains an exact key/value pair."""

        selected_types = tuple(
            memory_types
            or (
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
                MemoryType.CONVERSATION,
                MemoryType.PROCEDURAL,
            )
        )
        matches: dict[str, list[str]] = {}
        vector_collections: dict[MemoryType, str] = {
            MemoryType.SEMANTIC: self._config.semantic_collection,
            MemoryType.EPISODIC: self._config.episodic_collection,
            MemoryType.CONVERSATION: self._config.conversation_collection,
        }

        if self._vector is not None:
            filters = {metadata_key: metadata_value}
            for memory_type, collection in vector_collections.items():
                if memory_type not in selected_types:
                    continue
                matches[memory_type.value] = [
                    doc_id
                    for doc_id, owned in await self._collect_vector_ids(collection, filters)
                    if owned
                ]

        if MemoryType.PROCEDURAL in selected_types and self._relational is not None:
            rule_ids: list[str] = []
            offset = 0
            while True:
                rules = await self._relational.list_rules(
                    active_only=False,
                    limit=500,
                    offset=offset,
                    namespaces=self._namespaces,
                )
                if not rules:
                    break
                rule_ids.extend(rule.id for rule in rules if rule.metadata.get(metadata_key) == metadata_value)
                offset += len(rules)
            matches[MemoryType.PROCEDURAL.value] = rule_ids

        return matches

    async def list_memory_refs_by_metadata(
        self,
        metadata_key: str,
        metadata_value: str,
        *,
        memory_types: Sequence[MemoryType] | None = None,
    ) -> dict[str, list[dict[str, str]]]:
        """List owned memory refs and flat metadata markers for an exact metadata key/value pair."""

        selected_types = tuple(
            memory_types
            or (
                MemoryType.SEMANTIC,
                MemoryType.EPISODIC,
                MemoryType.CONVERSATION,
                MemoryType.PROCEDURAL,
            )
        )
        refs: dict[str, list[dict[str, str]]] = {}
        vector_collections: dict[MemoryType, str] = {
            MemoryType.SEMANTIC: self._config.semantic_collection,
            MemoryType.EPISODIC: self._config.episodic_collection,
            MemoryType.CONVERSATION: self._config.conversation_collection,
        }

        if self._vector is not None:
            filters = {metadata_key: metadata_value}
            for memory_type, collection in vector_collections.items():
                if memory_type not in selected_types:
                    continue
                refs[memory_type.value] = [
                    _memory_ref(doc.id, doc.metadata)
                    for doc in await self._collect_vector_docs(collection, filters)
                    if self._owns_vector_doc(doc)
                ]

        if MemoryType.PROCEDURAL in selected_types and self._relational is not None:
            rule_refs: list[dict[str, str]] = []
            offset = 0
            while True:
                rules = await self._relational.list_rules(
                    active_only=False,
                    limit=500,
                    offset=offset,
                    namespaces=self._namespaces,
                )
                if not rules:
                    break
                rule_refs.extend(_memory_ref(rule.id, rule.metadata) for rule in rules if rule.metadata.get(metadata_key) == metadata_value)
                offset += len(rules)
            refs[MemoryType.PROCEDURAL.value] = rule_refs

        return refs

    async def delete_all(self) -> dict[str, int]:
        uid, counts = self._user_id, {}
        if self._relational:
            try:
                counts["relational"] = await self._relational.delete_all()
            except Exception as e:
                logger.warning("Error deleting relational: %s", e)
        if self._vector:
            for coll in (
                self._config.semantic_collection,
                self._config.episodic_collection,
            ):
                try:
                    counts[coll] = await self._vector.delete_by_filter(coll, {})
                except Exception as e:
                    logger.warning("Error deleting %s: %s", coll, e)
        if self._graph is not None:
            try:
                counts["graph"] = await self._graph.delete_all_by_owner(uid)
            except Exception as e:
                logger.warning("Error deleting graph data: %s", e)
        return counts

    async def _collect_vector_ids(self, collection: str, filters: dict[str, str]) -> list[tuple[str, bool]]:
        if self._vector is None:
            return []
        ids: list[tuple[str, bool]] = []
        offset: str | None = None
        while True:
            docs, offset = await self._vector.scroll(collection, limit=500, offset=offset, filters=filters)
            ids.extend((doc.id, self._owns_vector_doc(doc)) for doc in docs)
            if offset is None:
                return ids

    async def _collect_vector_docs(self, collection: str, filters: dict[str, str]) -> list[VectorDocument]:
        if self._vector is None:
            return []
        collected: list[VectorDocument] = []
        offset: str | None = None
        while True:
            docs, offset = await self._vector.scroll(collection, limit=500, offset=offset, filters=filters)
            collected.extend(docs)
            if offset is None:
                return collected

    def _owns_vector_doc(self, doc: VectorDocument) -> bool:
        stored_uid = doc.metadata.get("user_id")
        if stored_uid and stored_uid != self._user_id:
            return False
        raw_namespaces = doc.metadata.get("namespaces")
        if isinstance(raw_namespaces, list) and raw_namespaces:
            namespaces = {value for value in raw_namespaces if isinstance(value, str)}
            return bool(namespaces.intersection(self._namespaces))
        primary_namespace = doc.metadata.get("primary_namespace")
        return not primary_namespace or primary_namespace in self._namespaces

    async def unarchive_memory(self, memory_id: str) -> SemanticMemory | EpisodicMemory:
        """Restore an archived memory to active status."""
        if self._vector is None:
            raise MemoryError("Vector backend is required but not provided")

        for coll, converter in (
            (self._config.semantic_collection, doc_to_semantic),
            (self._config.episodic_collection, doc_to_episodic),
        ):
            docs = await self._vector.get(coll, [memory_id])
            if not docs:
                continue
            doc = docs[0]
            if doc.metadata.get("user_id") != self._user_id:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
            is_archived = doc.metadata.get("status") == "archived" or doc.metadata.get(
                "archived"
            )
            if not is_archived:
                raise MemoryError(f"Memory {memory_id} is not archived")
            doc.metadata["status"] = "active"
            doc.metadata.pop("archived", None)
            doc.metadata.pop("archived_at", None)
            doc.metadata.pop("archive_reason", None)
            await self._vector.upsert(coll, [doc])
            return converter(doc)

        raise MemoryNotFoundError(f"Memory {memory_id} not found")

    async def close(self) -> None:
        if self._relational and hasattr(self._relational, "close"):
            await self._relational.close()
        if self._vector:
            await self._vector.close()
        if self._graph:
            await self._graph.close()
        if self._preference_strategy is not None:
            await self._preference_strategy.close()

    # ── List / Count / Delete by type (for API CRUD endpoints) ──

    async def list_memories(
        self,
        memory_type: MemoryType,
        *,
        limit: int = 100,
        offset: int = 0,
        include_archived: bool = False,
    ) -> list[AnyMemory]:
        return await list_by_type(
            memory_type,
            limit=limit,
            offset=offset,
            relational=self._relational,
            vector=self._vector,
            config=self._config,
            namespaces=self._namespaces,
            include_archived=include_archived,
        )

    async def count_memories(
        self, memory_type: MemoryType, *, since: datetime | None = None
    ) -> int:
        return await count_by_type(
            memory_type,
            relational=self._relational,
            vector=self._vector,
            config=self._config,
            namespaces=self._namespaces,
            since=since,
        )

    async def delete_by_type(self, memory_type: MemoryType) -> int:
        return await _delete_by_type(
            memory_type,
            relational=self._relational,
            vector=self._vector,
            config=self._config,
            namespaces=self._namespaces,
        )

    async def _collect_snapshot(self) -> MemorySnapshot | None:
        """Collect a point-in-time count of active semantic + episodic memories."""
        return await self._maintenance_service.collect_snapshot(
            count_memories_func=self.count_memories
        )

    async def _scroll_all_memories(self) -> list[AnyMemory]:
        """Scroll all semantic + episodic memories for maintenance analysis."""
        return await self._maintenance_service.scroll_all_memories(
            list_memories_func=lambda memory_type, limit: self.list_memories(
                memory_type, limit=limit
            )
        )

    async def compute_health_score(self) -> HealthScore:
        """Compute a quantitative health assessment of this memory instance.

        Low-frequency operation suitable for maintenance cycles, not per-query use.
        """
        return await self._maintenance_service.compute_health_score(
            count_memories_func=self.count_memories,
            list_memories_func=lambda memory_type, limit: self.list_memories(
                memory_type, limit=limit
            ),
        )

    async def archive_memories_auto(self) -> ArchivalResult:
        """Automatically archive old, rarely-accessed memories.

        Uses configured archival strategy to find and archive eligible memories.
        Improves search performance by reducing active corpus size.

        Returns:
            Archival operation result with statistics

        Raises:
            ValueError: If vector store not configured
        """
        from myrm_agent_harness.toolkits.memory.archival import (
            ArchivalResult,
            TimeBasedArchivalStrategy,
            archive_memories,
            find_archival_candidates,
        )

        if not self._vector:
            msg = "Archival requires vector store"
            raise ValueError(msg)

        if not self._config.archival.enabled:
            return ArchivalResult(archived_count=0, candidates=[], duration_ms=0.0)

        strategy = self._config.archival.archival_strategy or TimeBasedArchivalStrategy(
            min_age_days=self._config.archival.min_age_days,
            max_access_count=self._config.archival.max_access_count,
            max_importance=self._config.archival.max_importance,
        )

        candidates = await find_archival_candidates(
            vector=self._vector,
            strategy=strategy,
            limit=self._config.archival.batch_size,
            namespaces=self._namespaces,
        )

        if not candidates:
            return ArchivalResult(archived_count=0, candidates=[], duration_ms=0.0)

        return await archive_memories(candidates=candidates, vector=self._vector)

    async def search_archived(
        self, query: str, memory_type: MemoryType, *, limit: int = 10
    ) -> list[VectorDocument]:
        """Search archived memories (historical data access).

        Args:
            query: Search query
            memory_type: Memory type to search
            limit: Maximum results

        Returns:
            List of archived memory documents

        Raises:
            ValueError: If vector/embedding not configured
        """
        from myrm_agent_harness.toolkits.memory._internal.embedder import embed_single
        from myrm_agent_harness.toolkits.memory.archival import search_archived_memories

        if not self._vector or not self._embedding:
            msg = "Archival search requires vector store and embedding"
            raise ValueError(msg)

        query_vec = await embed_single(query, self._embedding, self._cache)

        return await search_archived_memories(
            query_vector=query_vec,
            memory_type=memory_type,
            vector=self._vector,
            limit=limit,
            namespaces=self._namespaces,
        )

    async def unarchive_memories(
        self, memory_ids: list[str], memory_type: MemoryType
    ) -> int:
        """Restore archived memories to active collections.

        Args:
            memory_ids: Memory IDs to restore
            memory_type: Memory type

        Returns:
            Number of memories restored

        Raises:
            ValueError: If vector store not configured
        """
        from myrm_agent_harness.toolkits.memory.archival import unarchive_memories

        if not self._vector:
            msg = "Unarchival requires vector store"
            raise ValueError(msg)

        return await unarchive_memories(
            memory_ids=memory_ids, memory_type=memory_type, vector=self._vector
        )

    async def create_backup(
        self, strategy: MemoryBackupStrategy, description: str | None = None
    ) -> BackupResult:
        """Create a complete memory backup using provided strategy.

        Args:
            strategy: Backup strategy implementation
            description: Optional backup description

        Returns:
            Backup operation result

        Raises:
            ValueError: If vector store not configured
        """

        if not self._vector:
            msg = "Backup requires vector store"
            raise ValueError(msg)

        return await strategy.create_backup(
            vector=self._vector, relational=self._relational, description=description
        )

    async def list_backups(
        self, strategy: MemoryBackupStrategy
    ) -> list[BackupMetadata]:
        """List available backups using provided strategy.

        Args:
            strategy: Backup strategy implementation

        Returns:
            List of backup metadata
        """
        return await strategy.list_backups()

    async def restore_backup(
        self, backup_id: str, strategy: MemoryBackupStrategy, *, overwrite: bool = False
    ) -> RestoreResult:
        """Restore memories from backup using provided strategy.

        Args:
            backup_id: Backup identifier
            strategy: Backup strategy implementation
            overwrite: If True, clear existing memories before restore

        Returns:
            Restore operation result

        Raises:
            ValueError: If vector store not configured
        """

        if not self._vector:
            msg = "Restore requires vector store"
            raise ValueError(msg)

        return await strategy.restore_backup(
            backup_id=backup_id,
            vector=self._vector,
            relational=self._relational,
            overwrite=overwrite,
        )

    async def delete_backup(
        self, backup_id: str, strategy: MemoryBackupStrategy
    ) -> bool:
        """Delete a backup using provided strategy.

        Args:
            backup_id: Backup identifier
            strategy: Backup strategy implementation

        Returns:
            True if backup deleted successfully
        """
        return await strategy.delete_backup(backup_id=backup_id)

    async def run_maintenance_cycle(self, *, force: bool = False) -> MaintenanceReport:
        """Execute a full maintenance cycle: consolidation → forgetting → health check.

        Args:
            force: Skip consolidation time gate (should_consolidate check).
                   Use when the caller explicitly requests maintenance, e.g.
                   user says "organize my memories" or after a bulk import.

        Non-blocking: returns immediately with skipped=True if another cycle
        is already running (via _maintenance_lock).
        """

        return await self._maintenance_service.run_cycle(
            force=force,
            lock=self._maintenance_lock,
            consolidation_enabled=self._consolidation_llm is not None
            and self.has_vector
            and self.has_relational,
            collect_snapshot_func=self._collect_snapshot,
            compute_health_func=self.compute_health_score,
            scroll_all_memories_func=self._scroll_all_memories,
            run_consolidation_func=self._run_consolidation_cycle,
            preference_rebuild_func=self._run_preference_rebuild,
        )

    async def _run_consolidation_cycle(
        self, cfg: ConsolidationConfig, force: bool
    ) -> MaintenanceConsolidationResult:
        if self._consolidation_llm is None:
            return MaintenanceConsolidationResult((0, 0, 0, 0, ()))

        from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
            run_consolidation,
            should_consolidate,
        )

        if not cfg.enabled or not (force or await should_consolidate(self, cfg)):
            return MaintenanceConsolidationResult((0, 0, 0, 0, ()))

        stats = await run_consolidation(self, self._consolidation_llm, cfg)
        if stats.merged + stats.corrected + stats.updated > 0:
            from myrm_agent_harness.toolkits.memory.strategies.pattern_discovery import (
                increment_consolidation_count,
            )

            with suppress(Exception):
                await increment_consolidation_count(self)
        return MaintenanceConsolidationResult(
            (stats.merged, stats.corrected, stats.updated, stats.errors, stats.insights)
        )

    async def _run_preference_rebuild(self) -> tuple[int, int, int]:
        """Execute full preference stability rebuild during maintenance.

        After rebuild, writes back stability scores to SemanticMemory.preference_strength
        so the existing retrieval pipeline (get_learned_context, ResultBooster) automatically
        benefits without any modifications.
        """
        if self._preference_strategy is None:
            return (0, 0, 0)
        promoted, demoted, dropped = await self._preference_strategy.full_rebuild()
        await self._writeback_preference_strength()
        return promoted, demoted, dropped

    async def _writeback_preference_strength(self) -> None:
        """Sync stability scores from PreferenceFacet back to SemanticMemory.preference_strength."""
        if self._preference_strategy is None or self._vector is None:
            return
        try:
            all_facets = await self._preference_strategy._store.list_all()
            coll = self._config.semantic_collection
            for facet in all_facets:
                normalized_strength = (
                    min(facet.stability / 3.0, 1.0) if not facet.user_pinned else 1.0
                )
                if facet.user_forgotten:
                    normalized_strength = 0.0
                for mid in facet.memory_ids:
                    try:
                        docs = await self._vector.get(coll, [mid])
                        if not docs:
                            continue
                        doc = docs[0]
                        old_strength = doc.metadata.get("preference_strength", 0.0)
                        if abs(float(old_strength) - normalized_strength) < 0.01:
                            continue
                        doc.metadata["preference_strength"] = normalized_strength
                        await self._vector.upsert(coll, [doc])
                    except Exception:
                        pass
        except Exception as e:
            logger.warning("Preference strength writeback failed (non-fatal): %s", e)

    async def delete_profile(self, key_or_id: str) -> bool:
        return await self._rel().delete_profile(key_or_id, namespaces=self._namespaces)

    # ── User Feedback Rating ──

    async def rate_memory(
        self, memory_id: str, score: int, collection: str | None = None
    ) -> bool:
        """Update a memory's user_rating using asymmetric Exponential Moving Average.

        Score is an integer in [1, 5] (user-facing Likert scale).
        Internally normalized to [0, 1] and applied via asymmetric EMA:
            alpha = alpha_negative if normalized < old_rating else alpha_positive
            rating_new = rating_old + alpha * (normalized - rating_old)

        Asymmetric design: negative feedback decays rating faster than positive
        feedback recovers it, requiring more positive validations to restore trust.

        Args:
            memory_id: Target memory ID.
            score: User feedback score (1=bad, 5=excellent).
            collection: Explicit vector collection. If None, searches both.

        Returns:
            True if the memory was found and updated.
        """
        if self._vector is None:
            return False

        clamped = max(1, min(5, score))
        normalized = (clamped - 1) / 4.0
        alpha_positive = self._config.rating_alpha
        alpha_negative = self._config.rating_alpha_negative

        collections = (
            [collection]
            if collection
            else [self._config.semantic_collection, self._config.episodic_collection]
        )
        for coll in collections:
            try:
                docs = await self._vector.get(coll, [memory_id])
            except Exception:
                continue
            if not docs:
                continue
            doc = docs[0]
            stored_uid = doc.metadata.get("user_id")
            if stored_uid and stored_uid != self._user_id:
                continue

            old_rating = float(doc.metadata.get("user_rating", 0.5))
            alpha = alpha_negative if normalized < old_rating else alpha_positive
            new_rating = old_rating + alpha * (normalized - old_rating)
            new_rating = max(0.0, min(1.0, round(new_rating, 4)))
            doc.metadata["user_rating"] = new_rating
            await self._vector.upsert(coll, [doc])
            return True
        return False

    # ── Get / Update single memory ──

    async def get_memory(self, memory_id: str) -> AnyMemory | None:
        tasks: list[asyncio.Task[AnyMemory | None]] = []
        if self._vector is not None:
            tasks.append(
                asyncio.create_task(
                    get_from_vector(
                        memory_id,
                        self._vector,
                        self._config,
                        namespaces=self._namespaces,
                    )
                )
            )
        if self._relational is not None:
            tasks.append(
                asyncio.create_task(
                    self._relational.get_rule(memory_id, namespaces=self._namespaces)
                )
            )
        for r in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(r, BaseException):
                logger.warning("Get memory error: %s", r)
            elif r is not None:
                return r
        return None

    async def correct_memory(
        self, memory_id: str, corrected_content: str
    ) -> SemanticMemory:
        """Correct a factually wrong memory: demote the old one and create a linked correction.

        Returns the newly created correction memory.
        """
        existing = await self.get_memory(memory_id)
        if existing is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")
        if not isinstance(existing, SemanticMemory):
            raise MemoryError(
                f"Correction only supports SemanticMemory, got {type(existing).__name__}"
            )

        demoted = existing.model_copy(deep=True)
        demoted.importance = max(existing.importance * 0.3, 0.05)
        demoted.confidence = 0.1
        demoted.metadata = {**demoted.metadata, "corrected": True}
        demoted.updated_at = datetime.now(UTC)
        v, e = self._vec()
        await update_vector_memory(demoted, False, v, self._config, e, self._cache)

        pref_strength = (
            min(existing.preference_strength + 0.1, 1.0)
            if existing.preference_strength > 0
            else 0.0
        )
        correction = SemanticMemory(
            content=corrected_content,
            importance=min(existing.importance + 0.2, 1.0),
            confidence=0.95,
            tags=existing.tags,
            source_chat_id=existing.source_chat_id,
            preference_type=existing.preference_type,
            preference_strength=pref_strength,
            correction_of=memory_id,
        )
        return await self._store_semantic(correction)

    async def pin_memory(self, memory_id: str) -> AnyMemory:
        """Mark a memory as user-pinned (immune to forgetting)."""
        return await self._set_pinned(memory_id, pinned=True)

    async def unpin_memory(self, memory_id: str) -> AnyMemory:
        """Remove user-pinned protection from a memory."""
        return await self._set_pinned(memory_id, pinned=False)

    async def _set_pinned(self, memory_id: str, *, pinned: bool) -> AnyMemory:
        if self._vector is None:
            raise MemoryError("Vector backend is required but not provided")

        for coll, converter in (
            (self._config.semantic_collection, doc_to_semantic),
            (self._config.episodic_collection, doc_to_episodic),
        ):
            docs = await self._vector.get(coll, [memory_id])
            if not docs:
                continue
            doc = docs[0]
            if doc.metadata.get("user_id") != self._user_id:
                raise MemoryNotFoundError(f"Memory {memory_id} not found")
            if bool(doc.metadata.get("pinned", False)) == pinned:
                return converter(doc)
            doc.metadata["pinned"] = pinned
            await self._vector.upsert(coll, [doc])
            return converter(doc)

        raise MemoryNotFoundError(f"Memory {memory_id} not found")

    async def update_memory(
        self,
        memory_id: str,
        *,
        content: str | None = None,
        importance: float | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, str | int | float | bool] | None = None,
        is_active: bool | None = None,
        status: MemoryStatus | None = None,
        reasoning: str | None = None,
        application: str | None = None,
    ) -> AnyMemory:
        existing = await self.get_memory(memory_id)
        if existing is None:
            raise MemoryNotFoundError(f"Memory {memory_id} not found")

        updated = existing.model_copy(deep=True)
        content_changed = content is not None
        if content_changed:
            updated.metadata = {
                **updated.metadata,
                "previous_content": existing.content,
            }
            updated.content = content
        if importance is not None and isinstance(updated, (SemanticMemory, EpisodicMemory, ConversationMemory)):
            updated.importance = importance
        if tags is not None and isinstance(updated, SemanticMemory):
            updated.tags = tags
        if status is not None:
            updated.status = status
            if status == MemoryStatus.ARCHIVED:
                now = datetime.now(UTC)
                updated.metadata = {
                    **updated.metadata,
                    "archived_at": now.isoformat(),
                    "archive_expires_at": (now + timedelta(days=7)).isoformat(),
                    "archive_reason": "user_deleted",
                }
            elif existing.status == MemoryStatus.ARCHIVED and status == MemoryStatus.ACTIVE:
                updated.metadata.pop("archived_at", None)
                updated.metadata.pop("archive_expires_at", None)
                updated.metadata.pop("archive_reason", None)
            if isinstance(updated, ProceduralMemory):
                updated.is_active = status == MemoryStatus.ACTIVE
        elif is_active is not None and isinstance(updated, ProceduralMemory):
            updated.is_active = is_active
            updated.status = MemoryStatus.ACTIVE if is_active else MemoryStatus.DISABLED
        if metadata is not None:
            updated.metadata = {**updated.metadata, **metadata}
        if isinstance(updated, ProceduralMemory):
            if reasoning is not None:
                updated.reasoning = reasoning
            if application is not None:
                updated.application = application
        updated.updated_at = datetime.now(UTC)

        if content_changed and self._config.security_scan_enabled:
            scan_and_clean_memory(
                updated, block_threshold=self._config.injection_block_threshold
            )

        if isinstance(updated, (SemanticMemory, EpisodicMemory)):
            v, e = self._vec()
            return await update_vector_memory(
                self._bind_scope(updated),
                content_changed,
                v,
                self._config,
                e,
                self._cache,
            )
        if isinstance(updated, ProceduralMemory):
            return await self._rel().update_rule(memory_id, updated)
        raise ValueError(f"Cannot update memory type: {type(updated).__name__}")

    # ── Private: backend accessors (fail-fast if not configured) ──

    def _vec(self) -> tuple[VectorStoreProtocol, EmbeddingProtocol]:
        if self._vector is None or self._embedding is None:
            raise MemoryError("Vector + Embedding backends required")
        return self._vector, self._embedding

    def _rel(self) -> RelationalStoreProtocol:
        if self._relational is None:
            raise MemoryError("Relational backend required")
        return self._relational

    def _bind_scope(self, memory: AnyMemory) -> AnyMemory:
        bound = bind_scope(memory, self._scope)
        if isinstance(bound, ProceduralMemory):
            if len(self._namespaces) > 1:
                bound.scope.primary_namespace = self._namespaces[1]
                bound.scope.namespaces = self._namespaces[:2]
                bound.scope.channel_id = None
                bound.scope.conversation_id = None
                bound.scope.task_id = None
            elif self._namespaces:
                bound.scope.primary_namespace = self._namespaces[0]
                bound.scope.namespaces = [self._namespaces[0]]
                bound.scope.agent_id = None
                bound.scope.channel_id = None
                bound.scope.conversation_id = None
                bound.scope.task_id = None
        return bound

    def _apply_channel_affinity(
        self, results: list[MemorySearchResult]
    ) -> list[MemorySearchResult]:
        return apply_channel_affinity(
            results, current_channel_id=self._scope.channel_id
        )

    async def _store_semantic(self, memory: SemanticMemory) -> SemanticMemory:
        v, e = self._vec()
        return await store_semantic(
            self._bind_scope(memory), v, self._config, e, self._cache
        )

    async def _store_semantics_batch(
        self, memories: list[SemanticMemory]
    ) -> list[SemanticMemory]:
        v, e = self._vec()
        return await store_semantics_batch(
            [self._bind_scope(memory) for memory in memories],
            v,
            self._config,
            e,
            self._cache,
        )

    async def _store_episodic(self, memory: EpisodicMemory) -> EpisodicMemory:
        v, e = self._vec()
        return await store_episodic(
            self._bind_scope(memory), v, self._config, e, self._cache, self._graph
        )

    async def _store_episodics_batch(
        self, memories: list[EpisodicMemory]
    ) -> list[EpisodicMemory]:
        v, e = self._vec()
        return await store_episodics_batch(
            [self._bind_scope(memory) for memory in memories],
            v,
            self._config,
            e,
            self._cache,
            self._graph,
        )

    async def _store_conversations_batch(
        self, memories: list[ConversationMemory]
    ) -> list[ConversationMemory]:
        from myrm_agent_harness.toolkits.memory._internal.storage import (
            store_conversations_batch,
        )

        v, e = self._vec()
        return await store_conversations_batch(
            [self._bind_scope(memory) for memory in memories],
            v,
            self._config,
            e,
            self._cache,
        )

    async def _store_procedural(self, memory: ProceduralMemory) -> ProceduralMemory:
        return await self._rel().create_rule(memory)

    async def _store_procedurals_batch(
        self, memories: list[ProceduralMemory]
    ) -> list[ProceduralMemory]:
        return [await self._rel().create_rule(m) for m in memories]

    async def _run_consolidation_safe(self, cfg: ConsolidationConfig) -> None:
        """Run consolidation in background, swallowing all exceptions."""
        try:
            from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
                run_consolidation,
                should_consolidate,
            )

            assert self._consolidation_llm is not None
            if not await should_consolidate(self, cfg):
                return
            await run_consolidation(self, self._consolidation_llm, cfg)
            self._stores_since_consolidation = 0
        except Exception as e:
            logger.warning("Background consolidation failed (non-fatal): %s", e)

    async def _warmup_embedding_cache(self) -> None:
        """Preload embeddings for recent memories into cache to eliminate cold-start latency.

        Runs asynchronously in background without blocking initialization.
        Collections are loaded in parallel for faster warmup.
        """
        if self._vector is None or self._embedding is None or self._cache is None:
            return

        try:
            limit = self._config.dedup.warmup_limit
            collections = [
                self._config.semantic_collection,
                self._config.episodic_collection,
            ]

            async def warmup_collection(collection: str) -> int:
                try:
                    exists = await self._vector.collection_exists(collection)
                    if not exists:
                        return 0

                    docs, _ = await self._vector.scroll(
                        collection, limit=limit, filters={"archived": False}
                    )
                    if not docs:
                        return 0

                    texts = []
                    for doc in docs:
                        if hasattr(doc, "content"):
                            texts.append(doc.content)
                        elif isinstance(doc, dict) and "content" in doc:
                            texts.append(doc["content"])
                        elif (
                            hasattr(doc, "payload")
                            and doc.payload
                            and "content" in doc.payload
                        ):
                            texts.append(doc.payload["content"])

                    if not texts:
                        return 0
                    from myrm_agent_harness.toolkits.memory._internal.storage import (
                        embed_batch,
                    )

                    await embed_batch(texts, self._embedding, self._cache)
                    logger.info(
                        "Warmed up %d embeddings from %s", len(texts), collection
                    )
                    return len(texts)
                except Exception as e:
                    logger.warning("Warmup failed for %s: %s", collection, e)
                    return 0

            results = await asyncio.gather(*[warmup_collection(c) for c in collections])
            total = sum(results)
            if total > 0:
                logger.info(
                    "Embedding cache warmup completed: %d embeddings preloaded", total
                )
        except Exception as e:
            logger.warning("Embedding cache warmup failed: %s", e)

    # ── Export / Import ──

    async def export_all(self) -> dict[str, list[dict[str, object]]]:
        """Export all memories as serializable dicts (excludes embeddings for portability).

        Returns:
            Dict keyed by memory type with lists of serialized memory objects.
        """
        result: dict[str, list[dict[str, object]]] = {}

        for mem_type in MemoryType:
            if mem_type == MemoryType.TASK_DIGEST:
                continue
            try:
                memories = await self.list_memories(
                    mem_type, limit=10000, include_archived=True
                )
                if memories:
                    serialized: list[dict[str, object]] = []
                    for m in memories:
                        data = m.model_dump(mode="json", exclude={"embedding"})
                        serialized.append(data)
                    result[mem_type.value] = serialized
            except Exception as e:
                logger.warning("Export failed for %s: %s", mem_type.value, e)

        return result

    async def import_memories(
        self, data: dict[str, list[dict[str, object]]], *, skip_duplicates: bool = True
    ) -> dict[str, int]:
        """Import memories from exported data, recomputing embeddings.

        Deduplication happens via ``store_batch`` when ``skip_duplicates`` is True
        and a deduplicator is configured. Profile entries are upserted via the
        relational backend directly.

        Args:
            data: Dict keyed by memory type with lists of serialized memory objects.
            skip_duplicates: When True (default), deduplicator filters duplicates.

        Returns:
            Dict with import counts per memory type.
        """
        counts: dict[str, int] = {}

        type_parsers: dict[
            str, type[SemanticMemory | EpisodicMemory | ProceduralMemory]
        ] = {
            MemoryType.SEMANTIC.value: SemanticMemory,
            MemoryType.EPISODIC.value: EpisodicMemory,
            MemoryType.PROCEDURAL.value: ProceduralMemory,
        }

        saved_dedup = self._deduplicator
        if not skip_duplicates:
            self._deduplicator = None

        try:
            for type_name, entries in data.items():
                parser = type_parsers.get(type_name)
                if parser is None:
                    if type_name == MemoryType.PROFILE.value and self._relational:
                        imported = 0
                        for entry in entries:
                            try:
                                meta = entry.get("metadata") or {}
                                key = str(entry.get("key", "") or meta.get("key", ""))
                                value = entry.get("value", "") or meta.get("value", "")
                                if key:
                                    await self._relational.set_profile(key, str(value), scope=self._scope)
                                    imported += 1
                            except Exception as e:
                                logger.warning("Import profile entry failed: %s", e)
                        counts[type_name] = imported
                    continue

                memories: list[SemanticMemory | EpisodicMemory | ProceduralMemory] = []
                for entry in entries:
                    try:
                        clean = {
                            k: v
                            for k, v in entry.items()
                            if k not in ("id", "embedding")
                        }
                        mem = parser.model_validate(clean)
                        memories.append(mem)
                    except Exception as e:
                        logger.warning(
                            "Import parse failed for %s entry: %s", type_name, e
                        )

                if memories:
                    try:
                        stored = await self.store_batch(memories)
                        counts[type_name] = len(stored)
                    except Exception as e:
                        logger.warning(
                            "Import batch store failed for %s: %s", type_name, e
                        )
                        counts[type_name] = 0
                else:
                    counts[type_name] = 0
        finally:
            self._deduplicator = saved_dedup

        return counts


def _memory_ref(memory_id: str, metadata: dict[str, object]) -> dict[str, str]:
    ref = {"id": memory_id}
    import_item_id = metadata.get("import_item_id")
    if isinstance(import_item_id, str):
        ref["import_item_id"] = import_item_id
    return ref


def _infer_preference_category(memory: SemanticMemory) -> PreferenceCategory:
    """Infer preference category from memory content via keyword heuristics.

    Priority order matters: VETO must precede TOOLING to avoid "don't use X"
    matching TOOLING before VETO. IDENTITY checked first as most distinctive.
    """
    content_lower = memory.content.lower()

    category_rules: tuple[tuple[PreferenceCategory, tuple[str, ...]], ...] = (
        (PreferenceCategory.IDENTITY, ("i am", "my name", "i'm", "我是", "我的名字")),
        (
            PreferenceCategory.VETO,
            ("don't", "never", "hate", "avoid", "禁止", "不要", "讨厌", "refuse"),
        ),
        (
            PreferenceCategory.CHANNEL,
            ("channel", "email", "slack", "wechat", "discord", "渠道", "邮件"),
        ),
        (PreferenceCategory.GOAL, ("goal", "plan", "want to", "aim", "目标", "计划")),
        (
            PreferenceCategory.TOOLING,
            ("use ", "tool", "ide", "editor", "framework", "工具", "使用"),
        ),
    )

    for category, keywords in category_rules:
        if any(kw in content_lower for kw in keywords):
            return category

    return PreferenceCategory.STYLE
