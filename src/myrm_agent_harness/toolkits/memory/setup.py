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

import logging
from pathlib import Path

from myrm_agent_harness.toolkits.memory.config import (
    AgentMemoryPolicy,
    MemoryConfig,
    RecallMode,
)
from myrm_agent_harness.toolkits.memory.manager import MemoryManager
from myrm_agent_harness.toolkits.memory.relational.sqlite_store import (
    SQLiteRelationalStore,
)
from myrm_agent_harness.toolkits.retriever.embedding.factory import (
    EmbeddingConfig,
    get_embedding_service,
)
from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.factory import create_vector_store

logger = logging.getLogger(__name__)


async def create_local_memory_manager(
    base_path: str | Path,
    embedding_config: EmbeddingConfig,
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
    time_decay_half_life_days: float | None = None,
) -> MemoryManager:
    """Create a fully functional MemoryManager using local file-based storage.

    This is the recommended out-of-the-box setup for Agent-in-Sandbox.
    It uses SQLite for relational data and embedded Qdrant for vector data,
    ensuring 100% data isolation and zero cloud database coupling.

    Args:
        user_id: The owner of the memories.
        base_path: The directory where SQLite and Qdrant files will be stored.
                   In a SaaS environment, this should be the mounted `/persistent` volume.
        embedding_config: Configuration for the embedding model.
        approval_required: Whether writes need human approval.
        dedup_llm: Optional LLM for smart deduplication.

    Returns:
        A fully initialized MemoryManager.
    """
    base_path = Path(base_path).resolve()
    base_path.mkdir(parents=True, exist_ok=True)

    # 1. Initialize Relational Store (SQLite)
    sqlite_path = base_path / "memory.db"
    relational_store = SQLiteRelationalStore(db_path=str(sqlite_path))

    # 2. Initialize Vector Store (Embedded Qdrant)
    qdrant_path = base_path / "vector_store"
    embedding_service = get_embedding_service(embedding_config)

    # We need to determine the embedding dimension
    # If the service doesn't provide it synchronously, we might need a dummy embed call
    # But usually EmbeddingConfig or EmbeddingService has it. Let's assume it's available or we default to 1536.
    dim = getattr(embedding_service, "dimension", 1536)
    if dim <= 0:
        try:
            test_vec = await embedding_service.embed("dimension probe")
            dim = len(test_vec)
        except Exception as e:
            logger.warning(
                f"Cannot determine embedding dimension, defaulting to 1536: {e}"
            )
            dim = 1536

    if vector_store is None:
        vector_config = VectorStoreConfig(
            mode=DeploymentMode.EMBEDDED,
            local_path=str(qdrant_path),
            embedding_dimension=dim,
        )
        vector_store = await create_vector_store(vector_config)

    # Ensure collections exist
    mem_config_args = {"embedding_model": embedding_config.model}
    if time_decay_half_life_days is not None:
        from myrm_agent_harness.toolkits.memory.strategies.forgetting import (
            ForgettingConfig,
        )

        mem_config_args["forgetting"] = ForgettingConfig(
            time_decay_half_life_days=time_decay_half_life_days
        )
    mem_config = MemoryConfig(**mem_config_args)
    if vector_store:
        for coll in [mem_config.semantic_collection, mem_config.episodic_collection]:
            try:
                exists = await vector_store.collection_exists(coll)
                if not exists:
                    await vector_store.create_collection(coll, dim)
            except Exception as e:
                logger.warning(f"Failed to ensure collection '{coll}': {e}")

        try:
            conv_coll = mem_config.conversation_collection
            if not await vector_store.collection_exists(conv_coll):
                from qdrant_client.models import Distance, VectorParams

                vectors_config = {
                    "raw": VectorParams(size=dim, distance=Distance.COSINE),
                    "summary": VectorParams(size=dim, distance=Distance.COSINE),
                }
                if getattr(vector_store, "_is_async", False):
                    await vector_store._client.create_collection(
                        collection_name=conv_coll, vectors_config=vectors_config
                    )
                else:
                    import asyncio

                    await asyncio.to_thread(
                        vector_store._client.create_collection,
                        collection_name=conv_coll,
                        vectors_config=vectors_config,
                    )
        except Exception as e:
            logger.warning(
                f"Failed to ensure collection '{mem_config.conversation_collection}': {e}"
            )

    # 3. Initialize Embedding Cache
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

    manager = MemoryManager(
        config=mem_config,
        user_id=user_id,
        relational=relational_store,
        vector=vector_store,
        graph=graph_store,
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
    )

    logger.info(f"Local MemoryManager initialized at {base_path} for local user")
    return manager
