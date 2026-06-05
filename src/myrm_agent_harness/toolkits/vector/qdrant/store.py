"""Qdrant Vector Store Implementation.

[INPUT]
myrm_agent_harness.toolkits.vector.base (POS: vector store abstraction layer)
myrm_agent_harness.toolkits.vector.config (POS: vector store common configuration)
myrm_agent_harness.toolkits.vector.qdrant.filters (POS: Qdrant filter builder)
qdrant_client (POS: Qdrant SDK, optional dependency)

[OUTPUT]
QdrantVectorStore: Async Qdrant implementation of VectorStore ABC

[POS]
Qdrant vector store implementation. Supports embedded and remote deployment modes with built-in retry and exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from myrm_agent_harness.toolkits.vector.base import (
    CollectionInfo,
    FilterDict,
    SearchResult,
    VectorDocument,
    VectorStore,
)
from myrm_agent_harness.toolkits.vector.config import VectorStoreConfig
from myrm_agent_harness.toolkits.vector.qdrant.filters import build_qdrant_filter

logger = logging.getLogger(__name__)


class QdrantVectorStore(VectorStore):
    """Qdrant implementation of VectorStore.

    Supports embedded (local file) and remote (server/cloud) modes.
    Use factory functions to create instances::

        from myrm_agent_harness.toolkits.vector.qdrant import (
            create_embedded_store,
            create_remote_store,
        )

        store = await create_embedded_store(path="./data/vectors")
        store = create_remote_store(url="http://localhost:6333")
    """

    MAX_RETRIES: int = 3
    RETRY_BASE_DELAY: float = 0.5

    def __init__(
        self,
        client: object,
        config: VectorStoreConfig,
        is_async: bool = True,
    ):
        """Use factory functions instead of direct instantiation."""
        self._client = client
        self._config = config
        self._default_dimension = config.embedding_dimension
        self._is_async = is_async

    @property
    def config(self) -> VectorStoreConfig:
        """Get the store configuration."""
        return self._config

    @property
    def deployment_mode(self) -> str:
        """Get the deployment mode string."""
        return self._config.mode.value

    async def _with_retry(self, operation: object, *args: object, **kwargs: object) -> object:
        """Execute operation with exponential backoff retry."""
        last_exception: Exception | None = None

        for attempt in range(self.MAX_RETRIES):
            try:
                return await self._execute(operation, *args, **kwargs)
            except Exception as e:
                last_exception = e
                if attempt < self.MAX_RETRIES - 1:
                    delay = self.RETRY_BASE_DELAY * (2**attempt)
                    logger.warning(
                        f"Qdrant operation failed (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.warning(f"Qdrant operation failed after {self.MAX_RETRIES} attempts: {e}")

        if last_exception:
            raise last_exception
        raise RuntimeError("Unexpected: no exception but operation failed")

    async def _execute(self, operation: object, *args: object, **kwargs: object) -> object:
        """Execute client operation, handling sync/async transparently."""
        if self._is_async:
            return await operation(*args, **kwargs)  # type: ignore[misc]
        return await asyncio.to_thread(operation, *args, **kwargs)  # type: ignore[arg-type]

    # Collection operations

    async def create_collection(
        self,
        name: str,
        dimension: int | None = None,
        distance: str = "cosine",
    ) -> bool:
        from qdrant_client.models import Distance, VectorParams

        if await self.collection_exists(name):
            return False

        dim = dimension or self._default_dimension
        distance_map = {
            "cosine": Distance.COSINE,
            "euclidean": Distance.EUCLID,
            "dot": Distance.DOT,
        }
        qdrant_distance = distance_map.get(distance.lower(), Distance.COSINE)

        await self._with_retry(
            self._client.create_collection,  # type: ignore[attr-defined]
            collection_name=name,
            vectors_config=VectorParams(size=dim, distance=qdrant_distance),
        )
        logger.debug(f"Created collection: {name} (dim={dim}, distance={distance})")
        return True

    async def delete_collection(self, name: str) -> bool:
        if not await self.collection_exists(name):
            return False
        await self._with_retry(self._client.delete_collection, collection_name=name)  # type: ignore[attr-defined]
        logger.debug(f"Deleted collection: {name}")
        return True

    async def collection_exists(self, name: str) -> bool:
        try:
            return await self._with_retry(self._client.collection_exists, collection_name=name)
        except Exception:
            return False

    async def get_collection_info(self, name: str) -> CollectionInfo | None:
        try:
            info = await self._execute(self._client.get_collection, collection_name=name)  # type: ignore[attr-defined]
            return CollectionInfo(
                name=name,
                dimension=info.config.params.vectors.size,  # type: ignore[union-attr]
                distance=info.config.params.vectors.distance.name.lower(),  # type: ignore[union-attr]
                count=info.points_count,
            )
        except Exception:
            return None

    async def list_collections(self) -> list[str]:
        collections = await self._execute(self._client.get_collections)  # type: ignore[attr-defined]
        return [c.name for c in collections.collections]  # type: ignore[union-attr]

    # Document operations

    async def upsert(
        self,
        collection: str,
        documents: Sequence[VectorDocument],
    ) -> list[str]:
        from qdrant_client.models import PointStruct

        try:
            await self._client.get_collection(collection_name=collection)
        except Exception:
            if documents and documents[0].vector:
                dim = len(documents[0].vector)
                await self.create_collection(collection, dimension=dim)
            else:
                raise ValueError(
                    f"Collection {collection} not found and cannot infer dimension from empty/vectorless documents"
                ) from None

        for doc in documents:
            if doc.vector is None:
                raise ValueError(f"Document {doc.id} is missing vector")

        import uuid

        def _ensure_valid_uuid(id_str: str) -> str:
            try:
                uuid.UUID(id_str)
                return id_str
            except ValueError:
                # If not a valid UUID, generate a deterministic one based on the string
                return str(uuid.uuid5(uuid.NAMESPACE_OID, id_str))

        points = [
            PointStruct(
                id=_ensure_valid_uuid(doc.id),
                vector=doc.vector,  # type: ignore[arg-type]
                payload={
                    "original_id": doc.id,
                    "content": doc.content,
                    "created_at": doc.created_at.isoformat(),
                    "updated_at": doc.updated_at.isoformat(),
                    **doc.metadata,
                },
            )
            for doc in documents
        ]

        await self._with_retry(self._client.upsert, collection_name=collection, points=points)  # type: ignore[attr-defined]
        return [doc.id for doc in documents]

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        query_filter = build_qdrant_filter(filters)

        results = await self._with_retry(
            self._client.query_points,  # type: ignore[attr-defined]
            collection_name=collection,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=True,
        )

        return [
            SearchResult(document=self._point_to_document(point), score=point.score)
            for point in results.points  # type: ignore[union-attr]
        ]

    async def search_multi_vector(
        self,
        collection: str,
        named_vectors: dict[str, list[float]],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
        fusion: str = "rrf",
    ) -> list[SearchResult]:
        """Qdrant 1.10+ native multi-vector search with prefetch and fusion.

        Uses Qdrant Query API's prefetch mechanism to query multiple named
        vectors in a single request, then fuses results server-side.
        """
        from qdrant_client.models import Prefetch, Rrf, RrfQuery

        query_filter = build_qdrant_filter(filters)

        prefetch_list = [
            Prefetch(
                query=vector,
                using=vector_name,
                limit=limit * 2,
                filter=query_filter,
                score_threshold=score_threshold,
            )
            for vector_name, vector in named_vectors.items()
        ]

        results = await self._with_retry(
            self._client.query_points,  # type: ignore[attr-defined]
            collection_name=collection,
            prefetch=prefetch_list,
            query=RrfQuery(rrf=Rrf()) if fusion.lower() == "rrf" else None,
            limit=limit,
            with_payload=True,
            with_vectors=True,
        )

        return [
            SearchResult(document=self._point_to_document(point), score=point.score)
            for point in results.points  # type: ignore[union-attr]
        ]

    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        points = await self._with_retry(
            self._client.retrieve,  # type: ignore[attr-defined]
            collection_name=collection,
            ids=ids,
            with_payload=True,
            with_vectors=True,
        )
        return [self._point_to_document(point) for point in points]  # type: ignore[union-attr]

    async def delete(self, collection: str, ids: list[str]) -> int:
        existing = await self.get(collection, ids)
        count = len(existing)
        if count > 0:
            await self._with_retry(
                self._client.delete,  # type: ignore[attr-defined]
                collection_name=collection,
                points_selector=ids,
            )
        return count

    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int:
        count = await self.count(collection, filters)
        if count > 0:
            query_filter = build_qdrant_filter(filters)
            await self._with_retry(
                self._client.delete,  # type: ignore[attr-defined]
                collection_name=collection,
                points_selector=query_filter,
            )
        return count

    async def count(self, collection: str, filters: FilterDict | None = None) -> int:
        query_filter = build_qdrant_filter(filters)
        if query_filter:
            result = await self._with_retry(
                self._client.count,  # type: ignore[attr-defined]
                collection_name=collection,
                count_filter=query_filter,
            )
        else:
            result = await self._with_retry(
                self._client.count,  # type: ignore[attr-defined]
                collection_name=collection,
            )
        return result.count  # type: ignore[union-attr]

    async def scroll(
        self,
        collection: str,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        scroll_filter = build_qdrant_filter(filters)

        points, next_offset = await self._with_retry(
            self._client.scroll,  # type: ignore[attr-defined]
            collection_name=collection,
            scroll_filter=scroll_filter,
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )

        documents = [self._point_to_document(point) for point in points]  # type: ignore[union-attr]
        next_cursor = str(next_offset) if next_offset is not None else None
        return documents, next_cursor

    async def close(self) -> None:
        from myrm_agent_harness.toolkits.vector.config import DeploymentMode

        if self._config.mode == DeploymentMode.EMBEDDED:
            logger.debug("Skipping close for EMBEDDED Qdrant client (managed as singleton)")
            return

        if self._is_async and hasattr(self._client, "close"):
            await self._client.close()  # type: ignore[union-attr]
        elif hasattr(self._client, "close"):
            self._client.close()  # type: ignore[union-attr]
        logger.debug("Qdrant connection closed")

    # Health & diagnostics

    async def health_check(self) -> bool:
        try:
            await self._execute(self._client.get_collections)  # type: ignore[attr-defined]
            return True
        except Exception as e:
            logger.warning(f"Qdrant health check failed: {e}")
            return False

    async def get_server_info(self) -> dict[str, str | int | bool]:
        try:
            collections = await self._execute(self._client.get_collections)  # type: ignore[attr-defined]
            return {
                "mode": self._config.mode.value,
                "collections_count": len(collections.collections),  # type: ignore[union-attr]
                "is_async": self._is_async,
            }
        except Exception as e:
            logger.warning(f"Failed to get server info: {e}")
            return {}

    # Private helpers

    def _point_to_document(self, point: object) -> VectorDocument:
        """Convert Qdrant point to VectorDocument."""
        payload = dict(point.payload) if point.payload else {}  # type: ignore[union-attr]

        content = payload.pop("content", "")
        created_at_str = payload.pop("created_at", None)
        updated_at_str = payload.pop("updated_at", None)

        created_at = datetime.fromisoformat(created_at_str) if created_at_str else datetime.now(UTC)
        updated_at = datetime.fromisoformat(updated_at_str) if updated_at_str else datetime.now(UTC)

        vector_value = point.vector if hasattr(point, "vector") else None  # type: ignore[union-attr]
        if isinstance(vector_value, dict):
            vector_value = None

        return VectorDocument(
            id=str(point.id),  # type: ignore[union-attr]
            content=content,
            vector=vector_value,
            metadata=payload,
            created_at=created_at,
            updated_at=updated_at,
        )
