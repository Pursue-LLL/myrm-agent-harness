"""Vector Store Abstract Interface and Data Models.


[INPUT]
(none — leaf module, no internal dependencies)

[OUTPUT]
- VectorStore: abstract async vector store interface (CRUD + search + scroll + health)
- VectorDocument: Pydantic model for documents with optional embedding
- SearchResult: Pydantic model for similarity search results
- CollectionInfo: Pydantic model for collection metadata

[POS]
Vector store abstraction layer. Defines backend-agnostic vector store interface and data models,
inherited by all vector store implementations.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

FilterValue = str | int | float | bool | list[str] | dict[str, str | int | float]
FilterDict = dict[str, FilterValue]


class VectorDocument(BaseModel):
    """Document with optional vector embedding and metadata."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    content: str = Field(description="Document text content")
    vector: list[float] | None = Field(
        default=None,
        description="Embedding vector (optional, can be generated later)",
    )
    metadata: dict[str, str | int | float | bool | list[str]] = Field(
        default_factory=dict,
        description="Additional document metadata",
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SearchResult(BaseModel):
    """Vector similarity search result."""

    document: VectorDocument
    score: float = Field(ge=0.0, description="Similarity score (higher is better for cosine/dot)")


class CollectionInfo(BaseModel):
    """Vector collection metadata."""

    name: str
    dimension: int
    distance: str = "cosine"
    count: int = 0


class VectorStore(ABC):
    """Abstract async vector store interface.

    Provides a unified API for vector storage and retrieval,
    supporting different backends (Qdrant, Milvus, etc.) and
    deployment modes (embedded, remote).

    All methods are async for non-blocking I/O.

    Example::

        store = await create_vector_store(config)
        await store.create_collection("docs", dimension=1536)

        docs = [VectorDocument(id="1", content="Hello", vector=[...])]
        await store.upsert("docs", docs)

        results = await store.search("docs", query_vector=[...], limit=10)
        for r in results:
            print(f"{r.document.content}: {r.score}")
    """

    @abstractmethod
    async def create_collection(
        self,
        name: str,
        dimension: int | None = None,
        distance: str = "cosine",
    ) -> bool:
        """Create a new collection. No-op if already exists.

        Returns:
            True if created, False if already exists.
        """

    @abstractmethod
    async def delete_collection(self, name: str) -> bool:
        """Delete a collection.

        Returns:
            True if deleted, False if not found.
        """

    @abstractmethod
    async def collection_exists(self, name: str) -> bool:
        """Check if a collection exists."""

    @abstractmethod
    async def get_collection_info(self, name: str) -> CollectionInfo | None:
        """Get collection metadata, or None if not found."""

    @abstractmethod
    async def list_collections(self) -> list[str]:
        """List all collection names."""

    @abstractmethod
    async def upsert(
        self,
        collection: str,
        documents: Sequence[VectorDocument],
    ) -> list[str]:
        """Insert or update documents (must have vectors set).

        Returns:
            List of upserted document IDs.

        Raises:
            ValueError: If any document is missing a vector.
        """

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Search by vector similarity.

        Filter syntax:
        - Simple match: ``{"key": "value"}``
        - IN query: ``{"key": ["val1", "val2"]}``
        - Range query: ``{"key": {"gte": 0, "lte": 100}}``
        - NOT query: ``{"key": {"not": "value"}}``

        Returns:
            Results sorted by similarity (highest first).
        """

    @abstractmethod
    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        """Get documents by IDs (may be shorter if some not found)."""

    @abstractmethod
    async def delete(self, collection: str, ids: list[str]) -> int:
        """Delete documents by IDs.

        Returns:
            Number of documents deleted.
        """

    @abstractmethod
    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int:
        """Delete documents matching filter (same syntax as search).

        Returns:
            Number of documents deleted.
        """

    @abstractmethod
    async def count(self, collection: str, filters: FilterDict | None = None) -> int:
        """Count documents in collection (with optional filter)."""

    @abstractmethod
    async def scroll(
        self,
        collection: str,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        """Cursor-based pagination through documents.

        Returns:
            Tuple of (documents, next_cursor). next_cursor is None when done.

        Example::

            docs, cursor = await store.scroll("col", limit=100)
            while cursor:
                docs, cursor = await store.scroll("col", limit=100, offset=cursor)
        """

    @abstractmethod
    async def close(self) -> None:
        """Release resources. Call when done using the store."""

    # Optional methods with default implementations

    async def health_check(self) -> bool:
        """Check store accessibility. Returns True if healthy."""
        try:
            await self.list_collections()
            return True
        except Exception:
            return False

    async def batch_upsert(
        self,
        collection: str,
        documents: Sequence[VectorDocument],
        batch_size: int = 500,
        max_concurrent: int = 4,
    ) -> list[str]:
        """Batch upsert with automatic chunking and concurrency control."""
        batches = [documents[i : i + batch_size] for i in range(0, len(documents), batch_size)]

        semaphore = asyncio.Semaphore(max_concurrent)

        async def _process(batch: Sequence[VectorDocument]) -> list[str]:
            async with semaphore:
                return await self.upsert(collection, batch)

        results = await asyncio.gather(*[_process(b) for b in batches])
        return [doc_id for batch_ids in results for doc_id in batch_ids]

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
        """Search using multiple named vectors with fusion (optional, backend-specific).

        Enables dual-channel or multi-vector search strategies by querying
        multiple named vectors in a single request and fusing results.

        Args:
            collection: Target collection name.
            named_vectors: Dict mapping vector names to query vectors,
                e.g. {"raw": [...], "summary": [...]}.
            limit: Maximum results to return after fusion.
            filters: Optional filter dict (same syntax as search()).
            score_threshold: Optional minimum score threshold.
            fusion: Fusion strategy, "rrf" (reciprocal rank fusion) or "weighted".

        Returns:
            Fused results sorted by combined score (highest first).

        Raises:
            NotImplementedError: If backend doesn't support multi-vector search.
                Callers should fallback to multiple search() calls + client-side fusion.

        Note:
            Default implementation raises NotImplementedError. Backends like
            Qdrant 1.10+ can override this for native multi-vector support.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} doesn't support search_multi_vector. "
            "Use multiple search() calls with client-side fusion."
        )
