"""Vector Store Toolkit — unified async vector storage and retrieval.

Features:
- VectorStore ABC with full CRUD + search + scroll + health
- Built-in Qdrant implementation (embedded & remote modes)
- Cursor-based pagination, advanced filters, batch operations
- Automatic retry with exponential backoff

Example::

    from myrm_agent_harness.toolkits.vector import VectorStoreConfig, VectorDocument
    from myrm_agent_harness.toolkits.vector.qdrant import create_vector_store

    config = VectorStoreConfig(local_path="./data/vectors")
    store = await create_vector_store(config)

    await store.create_collection("docs", dimension=1536)
    await store.upsert("docs", [VectorDocument(id="1", content="Hello", vector=[...])])
    results = await store.search("docs", query_vector=[...], limit=10)
"""

from myrm_agent_harness.toolkits.vector.base import (
    CollectionInfo,
    FilterDict,
    FilterValue,
    SearchResult,
    VectorDocument,
    VectorStore,
)
from myrm_agent_harness.toolkits.vector.config import (
    DeploymentMode,
    VectorStoreConfig,
)
from myrm_agent_harness.toolkits.vector.pool import VectorStorePool
from myrm_agent_harness.toolkits.vector.warmer import (
    DummyQueryStrategy,
    VectorStoreWarmer,
    VectorWarmupMetrics,
    WarmupStrategy,
)

__all__ = [
    "CollectionInfo",
    "DeploymentMode",
    "DummyQueryStrategy",
    "FilterDict",
    "FilterValue",
    "SearchResult",
    "VectorDocument",
    "VectorStore",
    "VectorStoreConfig",
    "VectorStorePool",
    "VectorStoreWarmer",
    "VectorWarmupMetrics",
    "WarmupStrategy",
]
