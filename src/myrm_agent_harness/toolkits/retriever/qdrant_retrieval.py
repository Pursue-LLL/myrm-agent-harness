"""Qdrant persistent vector retriever.

Provides persistent vector storage and retrieval based on Qdrant.
For ephemeral in-memory retrieval, use ``vector_search.NumpyVectorRetriever``.

[INPUT]
myrm_agent_harness.toolkits.vector.base (POS: vector store abstraction layer)
myrm_agent_harness.toolkits.retriever.embedding (POS: embedding service)

[OUTPUT]
QdrantRetriever: Persistent vector retriever with single/batch query support
RetrievalResult: Search result dataclass

[POS]
Qdrant persistent vector retriever. Wraps vector store search capability, providing automatic text-to-vector conversion.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.embedding import EmbeddingService
from myrm_agent_harness.toolkits.vector.base import FilterDict, VectorStore

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    """Retrieval result.

    Also used by ``vector_search.NumpyVectorRetriever``.
    """

    document: Document
    score: float


class QdrantRetriever:
    """Persistent vector retriever backed by any VectorStore.

    Suitable for:
    - Large document collections (> 10,000 documents)
    - Long-term storage and querying
    - Metadata filtering and complex queries

    For ephemeral retrieval (web search results, etc.), use NumpyVectorRetriever.
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embeddings: EmbeddingService,
    ):
        self._store = vector_store
        self._embeddings = embeddings

    async def search(
        self,
        query: str,
        collection: str,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> list[RetrievalResult]:
        """Single-query retrieval."""
        query_vector = await self._embeddings.embed(query)

        results = await self._store.search(
            collection=collection,
            query_vector=query_vector,
            limit=limit,
            filters=filters,
            score_threshold=score_threshold,
        )

        return [
            RetrievalResult(
                document=Document(
                    page_content=r.document.content,
                    metadata={"score": r.score, **r.document.metadata},
                ),
                score=r.score,
            )
            for r in results
        ]

    async def batch_search(
        self,
        queries: list[str],
        collection: str,
        limit: int = 10,
        filters: FilterDict | None = None,
        score_threshold: float | None = None,
    ) -> dict[str, list[RetrievalResult]]:
        """Batch query retrieval."""
        if not queries:
            return {}

        query_vectors = await self._embeddings.embed_batch(queries)

        async def _search_one(query: str, vector: list[float]) -> tuple[str, list[RetrievalResult]]:
            results = await self._store.search(
                collection=collection,
                query_vector=vector,
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
            )
            return query, [
                RetrievalResult(
                    document=Document(
                        page_content=r.document.content,
                        metadata={"score": r.score, **r.document.metadata},
                    ),
                    score=r.score,
                )
                for r in results
            ]

        tasks = [_search_one(q, v) for q, v in zip(queries, query_vectors, strict=True)]
        results = await asyncio.gather(*tasks)
        return dict(results)
