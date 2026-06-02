"""Vector Store Cache Warming Toolkit.

[INPUT]
myrm_agent_harness.toolkits.vector.base (POS: Vector store abstract interface)

[OUTPUT]
VectorStoreWarmer: Generic vector store cache warming utility
VectorWarmupMetrics: Performance metrics for warmup operations
DummyQueryStrategy: Default warmup strategy using random vectors

[POS]
Vector store cache warm-up toolkit. Provides a generic warm-up mechanism for any
VectorStore implementation, reducing cold start latency. Framework-level, out-of-the-box.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Protocol

from myrm_agent_harness.toolkits.vector.base import VectorStore

logger = logging.getLogger(__name__)

__all__ = ["DummyQueryStrategy", "VectorStoreWarmer", "VectorWarmupMetrics", "WarmupStrategy"]


@dataclass
class VectorWarmupMetrics:
    """Vector store warmup performance metrics.

    Tracks elapsed time, success rate, and warmup effectiveness.
    Framework layer provides .to_dict() for business layer export.
    """

    collection_name: str
    warmup_duration_ms: float = 0.0
    verify_duration_ms: float | None = None
    speedup_ratio: float | None = None
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, str | float | bool | None]:
        """Export metrics for logging/monitoring.

        Returns:
            Dictionary with warmup metrics.
            Format: {
                "collection_name": str,
                "warmup_duration_ms": float,
                "verify_duration_ms": float | None,
                "speedup_ratio": float | None,
                "success": bool,
                "error": str | None
            }
        """
        return {
            "collection_name": self.collection_name,
            "warmup_duration_ms": self.warmup_duration_ms,
            "verify_duration_ms": self.verify_duration_ms,
            "speedup_ratio": self.speedup_ratio,
            "success": self.success,
            "error": self.error,
        }


class WarmupStrategy(Protocol):
    """Warmup strategy protocol.

    Defines how to generate query vectors for cache warming.
    """

    async def generate_query_vector(self, dimension: int) -> list[float]:
        """Generate a query vector for warmup.

        Args:
            dimension: Vector dimension.

        Returns:
            Query vector for warmup.
        """
        ...


class DummyQueryStrategy:
    """Dummy query strategy using random vectors.

    Simple and effective strategy for cache warming.
    No dependencies on real query patterns or embeddings.
    """

    async def generate_query_vector(self, dimension: int) -> list[float]:
        """Generate a random query vector.

        Args:
            dimension: Vector dimension.

        Returns:
            Random query vector (normalized).
        """
        vector = [random.gauss(0, 1) for _ in range(dimension)]
        norm = sum(x * x for x in vector) ** 0.5
        return [x / norm for x in vector] if norm > 0 else vector


class VectorStoreWarmer:
    """Generic vector store cache warmer.

    Reduces cold start latency by pre-executing queries before users interact.
    Works with any VectorStore implementation (Qdrant, Milvus, Weaviate, etc.).

    Example:
        ```python
        warmer = VectorStoreWarmer(vector_store)

        # Warmup single collection
        metrics = await warmer.warmup_collection("kb_docs", dimension=1536)
        logger.info(f"Warmup metrics: {metrics.to_dict()}")

        # Warmup multiple collections in parallel
        collections = [("kb_docs", 1536), ("kb_code", 1536)]
        all_metrics = await warmer.warmup_batch(collections)
        for m in all_metrics:
            logger.info(f"Warmup {m.collection_name}: {m.warmup_duration_ms:.2f}ms")
        ```

    Note:
        Warmup failures do not raise exceptions, only log warnings and return metrics.
        This ensures warmup does not block application startup.
    """

    def __init__(
        self,
        store: VectorStore,
        strategy: WarmupStrategy | None = None,
    ):
        """Initialize vector store warmer.

        Args:
            store: Vector store to warm up.
            strategy: Warmup strategy (defaults to DummyQueryStrategy).
        """
        self._store = store
        self._strategy = strategy or DummyQueryStrategy()

    async def warmup_collection(
        self,
        collection: str,
        dimension: int,
        limit: int = 1,
    ) -> VectorWarmupMetrics:
        """Warm up a single collection.

        Args:
            collection: Collection name to warm up.
            dimension: Vector dimension.
            limit: Number of results to fetch (default: 1, minimal overhead).

        Returns:
            Warmup metrics (duration, success, error).
        """
        metrics = VectorWarmupMetrics(collection_name=collection)
        start_time = time.perf_counter()

        try:
            exists = await self._store.collection_exists(collection)
            if not exists:
                logger.warning(f"Collection '{collection}' does not exist, skipping warmup")
                metrics.success = False
                metrics.error = "Collection does not exist"
                metrics.warmup_duration_ms = (time.perf_counter() - start_time) * 1000
                return metrics

            query_vector = await self._strategy.generate_query_vector(dimension)

            await self._store.search(
                collection=collection,
                query_vector=query_vector,
                limit=limit,
            )

            metrics.success = True

        except Exception as e:
            metrics.success = False
            metrics.error = str(e)
            logger.warning(f"Failed to warm up collection '{collection}': {e}")

        finally:
            metrics.warmup_duration_ms = (time.perf_counter() - start_time) * 1000
            if metrics.success:
                logger.debug(f"Warmed up collection '{collection}' in {metrics.warmup_duration_ms:.2f}ms")

        return metrics

    async def warmup_with_verification(
        self,
        collection: str,
        dimension: int,
        limit: int = 1,
    ) -> VectorWarmupMetrics:
        """Warm up a single collection and verify effectiveness.

        Executes two queries: warmup (cold) and verification (warm).
        Calculates speedup ratio to measure cache effectiveness.

        Args:
            collection: Collection name to warm up.
            dimension: Vector dimension.
            limit: Number of results to fetch (default: 1, minimal overhead).

        Returns:
            Warmup metrics (duration, verify duration, speedup ratio, success, error).

        Example:
            ```python
            metrics = await warmer.warmup_with_verification("kb_docs", 1536)
            if metrics.success and metrics.speedup_ratio:
                logger.info(f"Warmup effectiveness: {metrics.speedup_ratio:.1f}x speedup")
            ```
        """
        metrics = VectorWarmupMetrics(collection_name=collection)
        start_time = time.perf_counter()

        try:
            exists = await self._store.collection_exists(collection)
            if not exists:
                logger.warning(f"Collection '{collection}' does not exist, skipping warmup")
                metrics.success = False
                metrics.error = "Collection does not exist"
                metrics.warmup_duration_ms = (time.perf_counter() - start_time) * 1000
                return metrics

            query_vector = await self._strategy.generate_query_vector(dimension)

            await self._store.search(
                collection=collection,
                query_vector=query_vector,
                limit=limit,
            )

            warmup_ms = (time.perf_counter() - start_time) * 1000
            metrics.warmup_duration_ms = warmup_ms

            verify_start = time.perf_counter()
            await self._store.search(
                collection=collection,
                query_vector=query_vector,
                limit=limit,
            )
            verify_ms = (time.perf_counter() - verify_start) * 1000
            metrics.verify_duration_ms = verify_ms

            if verify_ms > 0:
                metrics.speedup_ratio = warmup_ms / verify_ms

            metrics.success = True

            logger.debug(
                f"Warmed up collection '{collection}': "
                f"warmup={warmup_ms:.2f}ms, verify={verify_ms:.2f}ms, "
                f"speedup={metrics.speedup_ratio:.1f}x"
            )

        except Exception as e:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            metrics.warmup_duration_ms = elapsed_ms
            metrics.success = False
            metrics.error = str(e)
            logger.warning(f"Failed to warm up collection '{collection}': {e}")

        return metrics

    async def warmup_batch(
        self,
        collections: list[tuple[str, int]],
        limit: int = 1,
    ) -> list[VectorWarmupMetrics]:
        """Warm up multiple collections in parallel.

        Args:
            collections: List of (collection_name, dimension) tuples.
            limit: Number of results to fetch per collection (default: 1).

        Returns:
            List of warmup metrics for each collection.

        Example:
            ```python
            collections = [("kb_docs", 1536), ("kb_code", 768)]
            metrics = await warmer.warmup_batch(collections)
            ```
        """
        tasks = [self.warmup_collection(name, dim, limit) for name, dim in collections]
        return await asyncio.gather(*tasks)

    async def warmup_batch_with_verification(
        self,
        collections: list[tuple[str, int]],
        limit: int = 1,
    ) -> list[VectorWarmupMetrics]:
        """Warm up multiple collections in parallel with verification.

        Args:
            collections: List of (collection_name, dimension) tuples.
            limit: Number of results to fetch per collection (default: 1).

        Returns:
            List of warmup metrics for each collection (with verification data).

        Example:
            ```python
            collections = [("kb_docs", 1536), ("kb_code", 768)]
            metrics = await warmer.warmup_batch_with_verification(collections)
            for m in metrics:
                if m.success and m.speedup_ratio:
                    logger.info(f"{m.collection_name}: {m.speedup_ratio:.1f}x speedup")
            ```
        """
        tasks = [self.warmup_with_verification(name, dim, limit) for name, dim in collections]
        return await asyncio.gather(*tasks)
