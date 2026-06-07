"""MemoryManager mixin module (internal). Do not import directly."""

from __future__ import annotations



from myrm_agent_harness.toolkits.memory._manager.shared import (
    AgentMemoryPolicy,
    BaseChatModel,
    EmbeddingCacheProtocol,
    EmbeddingProtocol,
    GovernanceService,
    GraphStoreProtocol,
    MaintenanceService,
    MemoryConfig,
    MemoryError,
    MemoryRetrievalTrace,
    MemoryRetriever,
    MemoryScope,
    MemorySearchService,
    MemoryType,
    MemoryWriter,
    PreferenceStabilityStrategy,
    RecallMode,
    RecurrenceDetector,
    RelationalStoreProtocol,
    VectorStoreProtocol,
    _log_background_task_failure,
    build_episodic_deduplicator,
    build_scope,
    build_semantic_deduplicator,
    derive_namespaces,
)
from myrm_agent_harness.toolkits.memory._manager.shared import _log_background_task_failure


class MemoryManagerCore:
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
        self._maintenance_service = MaintenanceService(config=config, vector=vector, graph=graph)
        self._consolidation_llm: BaseChatModel | None = consolidation_llm
        self._fts5_searcher: FTS5SearcherFunc | None = fts5_searcher
        self._maintenance_lock = asyncio.Lock()
        self._preference_strategy: PreferenceStabilityStrategy | None = (
            PreferenceStabilityStrategy(preference_facet_store) if preference_facet_store is not None else None
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
