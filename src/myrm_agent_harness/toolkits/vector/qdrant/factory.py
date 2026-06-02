"""Qdrant Store Factory with Singleton Management.

[INPUT]
myrm_agent_harness.toolkits.vector.config (POS: vector store common configuration)
myrm_agent_harness.toolkits.vector.qdrant.store (POS: Qdrant vector store implementation)
qdrant_client (POS: Qdrant SDK, optional dependency)

[OUTPUT]
create_embedded_store: Create embedded Qdrant store (singleton per path)
create_remote_store: Create remote Qdrant store with async support
create_vector_store: Config-based factory (single entry point)

[POS]
Qdrant factory module. Manages singleton instances for embedded mode and AsyncQdrantClient creation for remote mode.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from myrm_agent_harness.toolkits.vector.config import DeploymentMode, VectorStoreConfig

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.vector.qdrant.store import QdrantVectorStore

logger = logging.getLogger(__name__)

_embedded_clients: dict[str, QdrantVectorStore] = {}
_embedded_lock: asyncio.Lock = asyncio.Lock()


async def create_embedded_store(
    path: str = "./data/vector_store",
    default_dimension: int = 1536,
) -> QdrantVectorStore:
    """Create an embedded Qdrant store (Local Files or In-Memory).

    Data stored in local files, no Docker needed.
    If the path is invalid or unwritable, it fallback to :memory: for safety.
    Uses singleton pattern per path to prevent file lock conflicts.

    Returns:
        QdrantVectorStore instance.
    """
    from myrm_agent_harness.toolkits.vector.qdrant.store import QdrantVectorStore

    try:
        from qdrant_client import QdrantClient
    except ImportError as e:
        raise ImportError("qdrant-client is required. Install with: pip install myrm-agent-harness[qdrant]") from e

    is_memory = path == ":memory:"
    if is_memory:
        data_path = Path(":memory:")
        cache_key = "memory_fallback"
    else:
        data_path = Path(path).resolve()
        cache_key = str(data_path)

    async with _embedded_lock:
        logger.debug("Checking cache for %s (available: %s)", cache_key, list(_embedded_clients.keys()))
        if cache_key in _embedded_clients:
            logger.debug("Cache hit for %s", cache_key)
            return _embedded_clients[cache_key]

        logger.debug("Cache miss for %s, creating new QdrantClient", cache_key)
        try:
            if not is_memory:
                data_path.mkdir(parents=True, exist_ok=True)

            client = QdrantClient(path=str(data_path) if not is_memory else ":memory:")
            actual_path = str(data_path) if not is_memory else ":memory:"
            logger.info("Qdrant EMBEDDED mode initialized: %s", actual_path)
        except Exception as e:
            # Fallback to in-memory if filesystem fails
            logger.error(f" Failed to initialize Qdrant at {data_path}: {e}. Falling back to :memory:")
            client = QdrantClient(path=":memory:")
            actual_path = ":memory:"
            cache_key = "memory_fallback"

        config = VectorStoreConfig(
            mode=DeploymentMode.EMBEDDED,
            local_path=actual_path,
            embedding_dimension=default_dimension,
        )
        store = QdrantVectorStore(client=client, config=config, is_async=False)
        _embedded_clients[cache_key] = store
        return store


def create_remote_store(
    url: str = "http://localhost:6333",
    api_key: str | None = None,
    default_dimension: int = 1536,
) -> QdrantVectorStore:
    """Create a remote Qdrant store with true async support.

    Connects to Qdrant server or cloud service.
    """
    from myrm_agent_harness.toolkits.vector.qdrant.store import QdrantVectorStore

    try:
        from qdrant_client import AsyncQdrantClient
    except ImportError as e:
        raise ImportError("qdrant-client is required. Install with: pip install myrm-agent-harness[qdrant]") from e

    client = AsyncQdrantClient(url=url, api_key=api_key)
    config = VectorStoreConfig(
        mode=DeploymentMode.REMOTE,
        url=url,
        api_key=api_key,
        embedding_dimension=default_dimension,
    )
    return QdrantVectorStore(client=client, config=config, is_async=True)


async def create_vector_store(config: VectorStoreConfig) -> QdrantVectorStore | None:
    """Create Qdrant store from configuration.

    Single entry point — routes to embedded or remote based on config.mode.

    Returns:
        QdrantVectorStore instance, or None if embedded mode fails.

    Raises:
        ValueError: If deployment mode is unknown.
        ImportError: If qdrant-client is not installed.
    """
    if config.mode == DeploymentMode.EMBEDDED:
        return await create_embedded_store(
            path=config.local_path,
            default_dimension=config.embedding_dimension,
        )
    elif config.mode == DeploymentMode.REMOTE:
        return create_remote_store(
            url=config.url,
            api_key=config.api_key,
            default_dimension=config.embedding_dimension,
        )
    else:
        raise ValueError(f"Unknown deployment mode: {config.mode}")
