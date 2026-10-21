"""Connection Pool for Vector Store.

Provides connection pooling for high-concurrency scenarios.


[INPUT]
- myrm_agent_harness.toolkits.vector (POS: vector store abstraction layer)
- myrm_agent_harness.toolkits.vector.config (POS: vector store common configuration)

[OUTPUT]
- VectorStorePool: semaphore-based connection pool for VectorStore instances

[POS]
Vector store connection pool. Manages a pool of VectorStore instances for high-concurrency
scenarios in remote deployment mode.
"""

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from myrm_agent_harness.toolkits.vector import (
    FilterDict,
    SearchResult,
    VectorDocument,
    VectorStore,
    VectorStoreConfig,
)
from myrm_agent_harness.toolkits.vector.config import DeploymentMode

logger = logging.getLogger(__name__)


class VectorStorePool:
    """Connection pool for VectorStore instances.

    Manages a pool of VectorStore connections for high-concurrency scenarios.
    Uses semaphore-based limiting to prevent overwhelming the backend.

    Features:
    - Pre-initialized connection pool
    - Semaphore-based concurrency limiting
    - Automatic connection recycling
    - Health monitoring

    Example:
        ```python
        # Create pool
        pool = await VectorStorePool.create(
            config=VectorStoreConfig(mode=DeploymentMode.REMOTE),
            pool_size=5,
        )

        # Use connection from pool
        async with pool.acquire() as store:
            await store.search(...)

        # Or use convenience methods
        results = await pool.search("collection", query_vector, limit=10)

        # Close pool
        await pool.close()
        ```
    """

    def __init__(
        self,
        stores: list[VectorStore],
        config: VectorStoreConfig,
    ):
        """Initialize pool with pre-created stores.

        Use VectorStorePool.create() instead.
        """
        self._stores = stores
        self._config = config
        self._pool_size = len(stores)
        self._semaphore = asyncio.Semaphore(self._pool_size)
        self._available: asyncio.Queue[VectorStore] = asyncio.Queue()
        self._closed = False

        # Add all stores to available queue
        for store in stores:
            self._available.put_nowait(store)

    @classmethod
    async def create(
        cls,
        config: VectorStoreConfig,
        pool_size: int = 5,
    ) -> "VectorStorePool":
        """Create a connection pool.

        Args:
            config: VectorStore configuration.
            pool_size: Number of connections in the pool.

        Returns:
            Initialized VectorStorePool.

        Note:
            Embedded mode only supports pool_size=1 (singleton).
        """
        from myrm_agent_harness.toolkits.vector.qdrant import create_vector_store as create_store_from_config

        # Embedded mode can only have one connection
        if config.mode == DeploymentMode.EMBEDDED:
            pool_size = 1
            logger.warning("Embedded mode only supports pool_size=1. For connection pooling, use REMOTE mode.")

        stores: list[VectorStore] = []
        for _i in range(pool_size):
            store = await create_store_from_config(config)
            if store is None:
                if config.mode == DeploymentMode.EMBEDDED:
                    logger.warning(
                        " Failed to create embedded vector store (concurrent access detected). Pool creation aborted."
                    )
                    raise RuntimeError(
                        "Cannot create vector store pool: embedded mode storage is already accessed by another process. "
                        "Consider using REMOTE mode for multi-process deployments."
                    )
                else:
                    raise RuntimeError("Failed to create vector store instance")
            stores.append(store)

        pool = cls(stores=stores, config=config)
        logger.warning(f"VectorStorePool created with {pool_size} connections")

        return pool

    @property
    def pool_size(self) -> int:
        """Get the pool size."""
        return self._pool_size

    @property
    def available_count(self) -> int:
        """Get the number of available connections."""
        return self._available.qsize()

    @asynccontextmanager
    async def acquire(self) -> AsyncIterator[VectorStore]:
        """Acquire a connection from the pool.

        Usage:
            async with pool.acquire() as store:
                await store.search(...)

        Yields:
            A VectorStore instance from the pool.
        """
        if self._closed:
            raise RuntimeError("Pool is closed")

        async with self._semaphore:
            store = await self._available.get()
            try:
                yield store
            finally:
                # Return to pool
                await self._available.put(store)

    async def close(self) -> None:
        """Close all connections in the pool."""
        if self._closed:
            return

        self._closed = True

        # Close all stores
        for store in self._stores:
            try:
                await store.close()
            except Exception as e:
                logger.warning(f"Error closing store: {e}")

        logger.warning("VectorStorePool closed")

    async def health_check(self) -> bool:
        """Check if the pool is healthy.

        Returns:
            True if at least one connection is healthy.
        """
        for store in self._stores:
            if await store.health_check():
                return True
        return False

    # ========================================================================
    # Convenience Methods (delegate to acquired connection)
    # ========================================================================

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Search using a connection from the pool."""
        async with self.acquire() as store:
            return await store.search(
                collection=collection,
                query_vector=query_vector,
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
            )

    async def upsert(
        self,
        collection: str,
        documents: Sequence[VectorDocument],
    ) -> list[str]:
        """Upsert using a connection from the pool."""
        async with self.acquire() as store:
            return await store.upsert(collection, documents)

    async def batch_upsert(
        self,
        collection: str,
        documents: Sequence[VectorDocument],
        batch_size: int = 500,
    ) -> list[str]:
        """Batch upsert distributing across pool connections."""
        docs_list = list(documents)
        batches: list[list[VectorDocument]] = [
            docs_list[i : i + batch_size] for i in range(0, len(docs_list), batch_size)
        ]

        async def process_batch(batch: list[VectorDocument]) -> list[str]:
            async with self.acquire() as store:
                return await store.upsert(collection, batch)

        results = await asyncio.gather(*[process_batch(batch) for batch in batches])

        all_ids: list[str] = []
        for ids in results:
            all_ids.extend(ids)

        return all_ids

    async def create_collection(
        self,
        name: str,
        dimension: int | None = None,
        distance: str = "cosine",
    ) -> bool:
        """Create collection using a connection from the pool."""
        async with self.acquire() as store:
            return await store.create_collection(name, dimension, distance)

    async def delete_collection(self, name: str) -> bool:
        """Delete collection using a connection from the pool."""
        async with self.acquire() as store:
            return await store.delete_collection(name)

    async def collection_exists(self, name: str) -> bool:
        """Check collection exists using a connection from the pool."""
        async with self.acquire() as store:
            return await store.collection_exists(name)

    async def count(
        self,
        collection: str,
        filters: FilterDict | None = None,
    ) -> int:
        """Count documents using a connection from the pool."""
        async with self.acquire() as store:
            return await store.count(collection, filters)
