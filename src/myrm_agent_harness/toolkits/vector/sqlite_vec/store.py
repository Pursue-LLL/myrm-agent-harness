"""Single-file embedded SQLite vector store engine.

[POS]
Embedded single-file vector database providing zero-daemon persistent storage,
dual-track hardware/software adaptive execution, and temporal decay retrieval.

[INPUT]
- asyncio, collections.abc.Sequence
- myrm_agent_harness.toolkits.vector.base (CollectionInfo, FilterDict, SearchResult, VectorDocument, VectorStore)
- myrm_agent_harness.toolkits.vector.sqlite_vec.models (DecayedSearchResult, SqliteVecConfig, SqliteVecEngineMode)
- myrm_agent_harness.toolkits.vector.sqlite_vec.decay (TemporalDecayScorer)
- myrm_agent_harness.toolkits.vector.sqlite_vec.db (SqliteVecDatabase)

[OUTPUT]
- SqliteVecStore: Single-file embedded vector store implementing VectorStoreProtocol
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path

from myrm_agent_harness.toolkits.vector.base import (
    CollectionInfo,
    FilterDict,
    SearchResult,
    VectorDocument,
    VectorStore,
)
from myrm_agent_harness.toolkits.vector.sqlite_vec.db import SqliteVecDatabase
from myrm_agent_harness.toolkits.vector.sqlite_vec.decay import TemporalDecayScorer
from myrm_agent_harness.toolkits.vector.sqlite_vec.models import (
    DecayedSearchResult,
    SqliteVecConfig,
    SqliteVecEngineMode,
)


class SqliteVecStore(VectorStore):
    """Zero-daemon single-file SQLite vector store with dual-track adaptive engine."""

    def __init__(self, config: SqliteVecConfig | None = None) -> None:
        """Initialize vector store."""
        self.config: SqliteVecConfig = config or SqliteVecConfig()
        self.db_path: Path = self.config.resolved_path()
        self._lock: asyncio.Lock = asyncio.Lock()
        self._db: SqliteVecDatabase = SqliteVecDatabase(self.config)
        self._decay_scorer: TemporalDecayScorer = TemporalDecayScorer(
            default_half_life_seconds=self.config.default_half_life_seconds,
            floor_score=self.config.floor_score,
        )
        self._closed: bool = False

    @property
    def is_persistent(self) -> bool:
        """Single-file SQLite always survives process restarts."""
        return True

    @property
    def engine_mode(self) -> SqliteVecEngineMode:
        """Currently active execution engine track."""
        return self._db.engine_mode

    async def create_collection(
        self, name: str, dimension: int | None = None, distance: str = "cosine"
    ) -> bool:
        """Create vector collection metadata. Returns True if created, False if already exists."""
        dim = dimension or 1536
        exists = await self.collection_exists(name)
        if exists:
            return False

        async with self._lock:
            return await asyncio.to_thread(self._db.create_collection, name, dim, distance)

    async def delete_collection(self, name: str) -> bool:
        """Delete collection and all its documents. Returns True if deleted, False if not found."""
        exists = await self.collection_exists(name)
        if not exists:
            return False

        async with self._lock:
            return await asyncio.to_thread(self._db.delete_collection, name)

    async def list_collections(self) -> list[str]:
        """List all collection names."""
        return await asyncio.to_thread(self._db.list_collections)

    async def ensure_collection(
        self, name: str, dimension: int, *, distance: str = "cosine"
    ) -> None:
        """Ensure collection exists."""
        exists = await self.collection_exists(name)
        if not exists:
            await self.create_collection(name, dimension, distance=distance)

    async def collection_exists(self, name: str) -> bool:
        """Check if collection exists."""
        return await asyncio.to_thread(self._db.collection_exists, name)

    async def get_collection_info(self, name: str) -> CollectionInfo | None:
        """Get collection metadata info."""
        return await asyncio.to_thread(self._db.get_collection_info, name)

    async def upsert(self, collection: str, documents: Sequence[VectorDocument]) -> list[str]:
        """Insert or replace documents with embeddings."""
        if not documents:
            return []
        doc_list = list(documents)
        async with self._lock:
            return await asyncio.to_thread(self._db.upsert_documents, collection, doc_list)

    async def get(self, collection: str, ids: list[str]) -> list[VectorDocument]:
        """Fetch documents by IDs."""
        if not ids:
            return []
        return await asyncio.to_thread(self._db.get_documents, collection, ids)

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Perform similarity search on collection."""
        return await asyncio.to_thread(
            self._db.search_documents,
            collection,
            query_vector,
            limit,
            filters,
            score_threshold,
        )

    async def search_decayed(
        self,
        collection: str,
        query_vector: list[float],
        *,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
        half_life_seconds: float | None = None,
    ) -> list[DecayedSearchResult]:
        """Perform similarity search with temporal decay ranking."""
        raw_results = await self.search(
            collection=collection,
            query_vector=query_vector,
            limit=limit * 2,
            filters=filters,
        )
        decayed = self._decay_scorer.rerank(
            results=raw_results,
            half_life_seconds=half_life_seconds,
            score_threshold=score_threshold,
        )
        return decayed[:limit]

    async def delete(self, collection: str, ids: list[str]) -> int:
        """Delete documents by ID list."""
        if not ids:
            return 0
        async with self._lock:
            return await asyncio.to_thread(self._db.delete_documents, collection, ids)

    async def delete_by_filter(self, collection: str, filters: FilterDict) -> int:
        """Delete documents matching filter dictionary."""
        docs, _ = await self.scroll(collection=collection, limit=10000, filters=filters)
        if not docs:
            return 0
        ids_to_del = [d.id for d in docs]
        return await self.delete(collection=collection, ids=ids_to_del)

    async def scroll(
        self,
        collection: str,
        *,
        limit: int = 100,
        offset: str | None = None,
        filters: FilterDict | None = None,
        order_by: tuple[str, str] | None = None,
    ) -> tuple[list[VectorDocument], str | None]:
        """Scroll documents with cursor pagination."""
        return await asyncio.to_thread(
            self._db.scroll_documents,
            collection,
            limit,
            offset,
            filters,
        )

    async def count(self, collection: str, filters: FilterDict | None = None) -> int:
        """Count documents in collection."""
        if filters:
            docs, _ = await self.scroll(collection, limit=100000, filters=filters)
            return len(docs)
        return await asyncio.to_thread(self._db.count_documents, collection)

    async def health_check(self) -> bool:
        """Verify database connectivity and file health."""
        if self._closed:
            return False

        def _sync_health() -> bool:
            try:
                conn = self._db.open_connection()
                conn.execute("SELECT 1").fetchone()
                conn.close()
                return True
            except Exception:
                return False

        return await asyncio.to_thread(_sync_health)

    async def close(self) -> None:
        """Close store resources."""
        self._closed = True
