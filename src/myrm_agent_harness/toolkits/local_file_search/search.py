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
        """Search indexed local files using Vector + BM25 dual-path recall.

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

        # 1. Vector Search
        vector_results = await self._store.search(
            collection=VECTOR_COLLECTION_NAME,
            query_vector=query_vector,
            limit=candidate_k,
            filters=filters if filters else None,
            score_threshold=score_threshold if score_threshold > 0 else None,
        )

        # 2. BM25 Search (Path + Content approximation via scroll)
        # In a real production system, BM25 index should be maintained by the indexer.
        # Here we use the existing bm25_retrieval for exact filename and keyword matching
        # by scrolling the vector store to get the corpus.
        bm25_results = []
        try:
            from myrm_agent_harness.toolkits.retriever.bm25_retrieval import bm25_retrieval

            # Fetch all documents for BM25 (in a real system, this would be cached)
            # We fetch up to 10000 documents to avoid OOM
            all_docs = await self._store.scroll(
                collection=VECTOR_COLLECTION_NAME,
                limit=10000,
                filters=filters if filters else None
            )

            if all_docs:
                # We build the BM25 corpus using both the file path and the content
                corpus = [
                    f"{doc.metadata.get('source_path', '')} {doc.content}"
                    for doc in all_docs
                ]

                # Perform BM25 retrieval
                bm25_hits = bm25_retrieval(corpus, query, top_k=candidate_k, only_relevant=True)

                # Convert BM25 hits to SearchResult format (score normalized to 0-1 range roughly)
                max_bm25_score = max((score for _, score in bm25_hits), default=1.0)
                for idx, score in bm25_hits:
                    normalized_score = score / max_bm25_score if max_bm25_score > 0 else 0.0
                    if score_threshold > 0 and normalized_score < score_threshold:
                        continue

                    from myrm_agent_harness.toolkits.vector.base import SearchResult
                    bm25_results.append(
                        SearchResult(
                            document=all_docs[idx],
                            score=normalized_score
                        )
                    )
        except Exception as e:
            logger.warning(f"BM25 retrieval failed: {e}")

        # 3. RRF Fusion (Vector + BM25)
        fused_results = []
        if bm25_results:
            # Simple RRF implementation for the two lists
            rrf_k = 60
            scores: dict[str, float] = {}
            payloads: dict[str, SearchResult] = {}

            for rank, res in enumerate(vector_results):
                payloads[res.document.id] = res
                scores[res.document.id] = scores.get(res.document.id, 0.0) + 1.0 / (rrf_k + rank + 1)

            for rank, res in enumerate(bm25_results):
                payloads[res.document.id] = res
                scores[res.document.id] = scores.get(res.document.id, 0.0) + 1.0 / (rrf_k + rank + 1)

            # Sort by RRF score
            ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:candidate_k]

            # Reconstruct results
            for doc_id, _ in ordered:
                fused_results.append(payloads[doc_id])
        else:
            fused_results = vector_results

        results = fused_results

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
