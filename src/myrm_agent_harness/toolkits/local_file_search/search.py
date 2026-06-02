"""Search engine for local file search.

[INPUT]
- .config::VECTOR_COLLECTION_NAME (POS: vector collection name constant)
- .models::SearchHit, SearchResponse (POS: search result models)
- myrm_agent_harness.toolkits.retriever.embedding (POS: embedding service for query vectorization)
- myrm_agent_harness.toolkits.retriever.reranker (POS: reranker service for precision)
- myrm_agent_harness.toolkits.vector.base (POS: vector store search interface)

[OUTPUT]
- LocalFileSearchEngine: Hybrid search engine combining vector similarity + optional reranking

[POS]
Search engine for local file content. Queries the vector store built by the indexer,
applies optional reranking for precision, and returns scored results with file metadata.
"""

from __future__ import annotations

import logging
import time

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.local_file_search.config import VECTOR_COLLECTION_NAME
from myrm_agent_harness.toolkits.local_file_search.models import SearchHit, SearchResponse
from myrm_agent_harness.toolkits.retriever.embedding import EmbeddingService
from myrm_agent_harness.toolkits.retriever.reranker import RerankerService
from myrm_agent_harness.toolkits.vector.base import FilterDict, VectorStore

logger = logging.getLogger(__name__)


class LocalFileSearchEngine:
    """Hybrid search engine for local indexed files.

    Search flow:
    1. Embed query text → vector
    2. Vector similarity search in the local_file_search collection
    3. Optional reranking for higher precision
    4. Return SearchResponse with scored hits
    """

    def __init__(
        self,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        reranker: RerankerService | None = None,
    ):
        self._store = vector_store
        self._embeddings = embedding_service
        self._reranker = reranker

    async def search(
        self,
        query: str,
        *,
        top_k: int = 10,
        file_type_filter: str | None = None,
        directory_id_filter: str | None = None,
        score_threshold: float = 0.0,
    ) -> SearchResponse:
        """Search indexed local files.

        Args:
            query: Natural language search query
            top_k: Maximum number of results to return
            file_type_filter: Optional filter by file extension (e.g. "pdf")
            directory_id_filter: Optional filter by directory ID
            score_threshold: Minimum similarity score (0.0 = no threshold)

        Returns:
            SearchResponse with ranked results
        """
        start_time = time.perf_counter()

        exists = await self._store.collection_exists(VECTOR_COLLECTION_NAME)
        if not exists:
            return SearchResponse(query=query, search_time_ms=0.0)

        query_vector = await self._embeddings.embed(query)

        filters: FilterDict = {}
        if file_type_filter:
            filters["file_type"] = file_type_filter
        if directory_id_filter:
            filters["directory_id"] = directory_id_filter

        candidate_k = top_k * 3 if self._reranker else top_k

        results = await self._store.search(
            collection=VECTOR_COLLECTION_NAME,
            query_vector=query_vector,
            limit=candidate_k,
            filters=filters if filters else None,
            score_threshold=score_threshold if score_threshold > 0 else None,
        )

        if not results:
            elapsed = (time.perf_counter() - start_time) * 1000
            return SearchResponse(query=query, search_time_ms=elapsed)

        if self._reranker and len(results) > 1:
            documents = [
                Document(
                    page_content=r.document.content,
                    metadata=dict(r.document.metadata),
                )
                for r in results
            ]
            reranked = await self._reranker.rerank(query, documents, top_k=top_k)
            hits = [
                SearchHit(
                    file_path=str(doc.metadata.get("source_path", "")),
                    relative_path=str(doc.metadata.get("relative_path", "")),
                    snippet=doc.page_content[:500],
                    score=float(doc.metadata.get("rerank_score", doc.metadata.get("score", 0.0))),
                    file_type=str(doc.metadata.get("file_type", "")),
                    section=str(doc.metadata.get("section", "")),
                )
                for doc in reranked
            ]
        else:
            hits = [
                SearchHit(
                    file_path=str(r.document.metadata.get("source_path", "")),
                    relative_path=str(r.document.metadata.get("relative_path", "")),
                    snippet=r.document.content[:500],
                    score=r.score,
                    file_type=str(r.document.metadata.get("file_type", "")),
                    section=str(r.document.metadata.get("section", "")),
                )
                for r in results[:top_k]
            ]

        elapsed = (time.perf_counter() - start_time) * 1000
        logger.info(
            "Local file search: query='%s', hits=%d, elapsed=%.0fms",
            query[:80],
            len(hits),
            elapsed,
        )

        return SearchResponse(
            hits=hits,
            total_hits=len(hits),
            query=query,
            search_time_ms=elapsed,
        )
