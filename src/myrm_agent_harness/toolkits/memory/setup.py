"""Out-of-the-box Memory Setup for local and sandbox environments.

[INPUT]
myrm_agent_harness.toolkits.memory.manager::MemoryManager (POS: memory manager core class)
myrm_agent_harness.toolkits.memory.relational.sqlite_store::SQLiteRelationalStore (POS: local SQLite relational store implementation)
myrm_agent_harness.toolkits.vector.qdrant.factory::create_vector_store (POS: Qdrant vector store factory)

[OUTPUT]
create_local_memory_manager: zero-config local memory manager factory function

[POS]
Out-of-the-box local memory factory. Combines SQLite and embedded Qdrant to provide zero-config
persistent memory capability for standalone deployments and single-machine sandboxes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.memory._internal.storage_conversation import (
    CONVERSATION_VECTORS,
)
from myrm_agent_harness.toolkits.memory.config import (
    AgentMemoryPolicy,
    MemoryConfig,
    RecallMode,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.relational.sqlite_store import (
    SQLiteRelationalStore,
)
from myrm_agent_harness.toolkits.retriever.embedding.base import EmbeddingService
from myrm_agent_harness.toolkits.retriever.embedding.factory import (
    EmbeddingConfig,
    get_embedding_service,
)
from myrm_agent_harness.toolkits.retriever.reranker.factory import (
    RerankerConfig,
    get_reranker_service,
)
from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.factory import create_vector_store

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.memory.file_sync.sync import FileMemorySyncEngine
    from myrm_agent_harness.toolkits.memory.strategies.consolidation import (
        ConflictCallback,
        ConsolidationCompleteCallback,
    )

logger = logging.getLogger(__name__)

_DEFAULT_EMBEDDING_DIMENSION = 1536
"""Size for the store's own default only, when the embedder cannot report or produce one."""

_SPARSE_ONLY_EMBEDDING_MODEL = "sparse-only"
"""Embedding-model marker for embeddings-less deployments.

The config field feeds model-switch detection (collection lineage); without
an embedding backend no dense vectors exist, so the marker stays stable and
can never collide with a real model name.
"""


async def _probe_embedding_dimension(embedding_service: object) -> int:
    """The embedder's vector size, probed when the service cannot report it yet.

    ``dimension`` may raise until a first embed completes (auto-detect backends), so a
    failure falls through to the probe. A probe failure returns 0: collections are then
    created by their first write, which sizes them from the vectors that write carries,
    instead of freezing a guessed size that every later write would fail against.
    """
    try:
        dim = getattr(embedding_service, "dimension", 0)
    except Exception as e:  # property raised (e.g. dimension not yet detected)
        logger.debug("Embedding dimension not available yet (%s); probing.", e)
        dim = 0
    if isinstance(dim, int) and dim > 0:
        return dim
    try:
        test_vec = await embedding_service.embed("dimension probe")  # type: ignore[attr-defined]
    except Exception as e:
        logger.warning("Cannot determine embedding dimension (%s); collections are created on first write.", e)
        return 0
    return len(test_vec)


async def create_local_memory_manager(
    base_path: str | Path,
    embedding_config: EmbeddingConfig | None,
    *,
    user_id: str = "sandbox_user",
    approval_required: bool = False,
    dedup_llm: object | None = None,
    consolidation_llm: object | None = None,
    namespaces: list[str] | None = None,
    agent_id: str | None = None,
    channel_id: str | None = None,
    conversation_id: str | None = None,
    task_id: str | None = None,
    memory_policy: AgentMemoryPolicy | None = None,
    recall_mode: RecallMode = RecallMode.HYBRID,
    vector_store: object | None = None,
    reranker_config: RerankerConfig | None = None,
    time_decay_half_life_days: float | None = None,
    on_conflict: ConflictCallback | None = None,
    on_consolidation_complete: ConsolidationCompleteCallback | None = None,
) -> MemoryManager:
    """Create a fully functional MemoryManager using local file-based storage.

    This is the recommended out-of-the-box setup for Agent-in-Sandbox.
    It uses SQLite for relational data and embedded Qdrant for vector data,
    ensuring 100% data isolation and zero cloud database coupling.

    Args:
        user_id: The owner of the memories.
        base_path: The directory where SQLite and Qdrant files will be stored.
                   In a SaaS environment, this should be the mounted `/persistent` volume.
        embedding_config: Configuration for the embedding model. Pass ``None``
            for embeddings-less deployments: semantic and episodic memories
            then persist through the BM25 sparse mirror, which becomes the
            authoritative store for their collections and is served by the
            existing BM25 search channel until an embedding backend is configured.
        approval_required: Whether writes need human approval.
        dedup_llm: Optional LLM for smart deduplication.

    Returns:
        A fully initialized MemoryManager.
    """
    base_path = Path(base_path).resolve()
    base_path.mkdir(parents=True, exist_ok=True)

    # 1. Initialize Relational Store (SQLite)
    sqlite_path = base_path / "memory.db"
    from myrm_agent_harness.toolkits.memory.ephemeral_delta.shared_store import (
        configure_ephemeral_delta_persistence,
    )

    configure_ephemeral_delta_persistence(sqlite_path)
    relational_store = SQLiteRelationalStore(db_path=str(sqlite_path))

    # 2. Initialize Vector Store (Embedded Qdrant)
    qdrant_path = base_path / "vector_store"
    embedding_service: EmbeddingService | None = None
    dim: int | None = None
    if embedding_config is not None:
        embedding_service = get_embedding_service(embedding_config)

        # Determine the embedding dimension. `dimension` may be a property that raises
        # until a first embed completes (auto-detect backends), so both "attribute
        # missing" and "property raised" must fall through to the probe path instead
        # of crashing startup for self-hosted/unknown embedding models.
        dim = await _probe_embedding_dimension(embedding_service)

    if vector_store is None:
        vector_config = VectorStoreConfig(
            mode=DeploymentMode.EMBEDDED,
            local_path=str(qdrant_path),
            embedding_dimension=dim or _DEFAULT_EMBEDDING_DIMENSION,
        )
        vector_store = await create_vector_store(vector_config)

    # Ensure collections exist. Dense collections need an embedding dimension;
    # without an embedding backend they are skipped and the BM25 sparse mirror
    # is ensured on the first sparse write instead.
    mem_config_args = {
        "embedding_model": embedding_config.model if embedding_config is not None else _SPARSE_ONLY_EMBEDDING_MODEL
    }
    if time_decay_half_life_days is not None:
        from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
            ForgettingConfig,
        )

        mem_config_args["forgetting"] = ForgettingConfig(time_decay_half_life_days=time_decay_half_life_days)
    mem_config = MemoryConfig(**mem_config_args)
    if vector_store and dim:
        for coll in [mem_config.semantic_collection, mem_config.episodic_collection]:
            try:
                await vector_store.ensure_collection(coll, dim)
            except Exception as e:
                logger.warning(f"Failed to ensure collection '{coll}': {e}")

        try:
            if not await vector_store.collection_exists(mem_config.conversation_collection):
                await vector_store.create_named_vector_collection(
                    mem_config.conversation_collection, dim, names=CONVERSATION_VECTORS
                )
        except Exception as e:
            logger.warning(f"Failed to ensure collection '{mem_config.conversation_collection}': {e}")

    # 3. Initialize Embedding Cache (only meaningful with an embedding backend)
    cache: EmbeddingCache | None = None
    if embedding_service is not None and embedding_config is not None:
        from myrm_agent_harness.toolkits.memory import EmbeddingCache

        cache = EmbeddingCache(
            embedding_func=embedding_service.embed,
            batch_func=embedding_service.embed_batch,
            model_name=embedding_config.model,
        )

    # 4. Initialize Preference Facet Store (shares same SQLite DB)
    from myrm_agent_harness.toolkits.memory.strategies.preference_stability_store import (
        SQLitePreferenceFacetStore,
    )

    preference_facet_store = SQLitePreferenceFacetStore(db_path=str(sqlite_path))

    # 5. Initialize Graph Store (shares data directory, separate DB file)
    from myrm_agent_harness.toolkits.memory.graph.sqlite_store import SQLiteGraphStore

    graph_db_path = base_path / "graph.db"
    graph_store = SQLiteGraphStore(db_path=str(graph_db_path))

    # 6. Create and return the MemoryManager
    consolidation_llm = dedup_llm  # Reuse dedup_llm for consolidation

    # Cross-encoder rerank gate for the retrieval pipeline; the factory-level
    # process cache dedupes identical configs across manager instances.
    reranker = get_reranker_service(reranker_config) if reranker_config is not None else None

    manager = MemoryManager(
        config=mem_config,
        user_id=user_id,
        relational=relational_store,
        vector=vector_store,
        graph=graph_store,
        fts5_searcher=relational_store.search_fts5,
        reranker=reranker,
        embedding=embedding_service,
        cache=cache,
        approval_required=approval_required,
        dedup_llm=dedup_llm,
        consolidation_llm=consolidation_llm,
        namespaces=namespaces,
        agent_id=agent_id,
        channel_id=channel_id,
        conversation_id=conversation_id,
        task_id=task_id,
        memory_policy=memory_policy,
        recall_mode=recall_mode,
        preference_facet_store=preference_facet_store,
        on_conflict=on_conflict,
        on_consolidation_complete=on_consolidation_complete,
    )

    logger.info(f"Local MemoryManager initialized at {base_path} for local user")
    return manager


def setup_local_file_memory_sync(
    base_path: str | Path,
    memory_manager: MemoryManager | None = None,
) -> FileMemorySyncEngine:
    """Create and initialize a Local-First FileMemorySyncEngine.

    Ensures MEMORY.md and daily note directory structures are created and
    binds synchronization to the provided MemoryManager instance.
    """
    from myrm_agent_harness.toolkits.memory.file_sync import (
        FileMemoryStore,
        FileMemorySyncEngine,
        FileMemoryTopology,
    )

    resolved_path = Path(base_path).resolve()
    topology = FileMemoryTopology(root_dir=resolved_path)
    store = FileMemoryStore(topology=topology)
    store.ensure_topology()
    return FileMemorySyncEngine(store=store, memory_manager=memory_manager)
