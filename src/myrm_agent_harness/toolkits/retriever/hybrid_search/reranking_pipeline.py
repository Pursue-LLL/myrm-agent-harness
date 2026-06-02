"""Reranking pipeline for batch reranking optimization.

[INPUT]
- toolkits.retriever.reranker::RerankerService (POS: Reranker contract layer. Declares the abstract interface and result type that every reranker backend must implement.)

[OUTPUT]
- RerankingPipeline: class — Reranking Pipeline

[POS]
Provides RerankingPipeline.
"""

import logging

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.reranker import RerankerService

logger = logging.getLogger(__name__)

_DEFAULT_RERANK_BATCH_SIZE = 32


class RerankingPipeline:
    """Batch reranking pipeline for retrieval quality improvement.

    Responsibilities:
    1. Check whether reranking is needed (document count check)
    2. Batch reranking (multi-query single model call for efficiency)
    3. Result reassembly and sorting

    Args:
        reranker: Reranker service instance
        min_docs_to_rerank: Minimum document count to trigger reranking
        batch_size: Documents per batch sent to the reranker per query.
                    Controls single API call payload to prevent timeouts or
                    exceeding provider limits. Default 32, suitable for most
                    cloud rerankers (Cohere/Jina/Voyage).
    """

    def __init__(
        self,
        reranker: RerankerService,
        *,
        min_docs_to_rerank: int = 3,
        batch_size: int = _DEFAULT_RERANK_BATCH_SIZE,
    ):
        self.reranker = reranker
        self.min_docs_to_rerank = min_docs_to_rerank
        self.batch_size = max(1, batch_size)

    async def rerank_query_results(
        self,
        query_results: dict[str, list[tuple[Document, float]]],
    ) -> dict[str, list[tuple[Document, float]]]:
        """Batch rerank results for multiple queries."""
        if not query_results:
            return {}

        unique_doc_count = self._count_unique_documents(query_results)

        if unique_doc_count == 0:
            logger.debug("No candidate documents, skipping reranking")
            return {}

        if unique_doc_count <= self.min_docs_to_rerank:
            logger.debug(
                "Candidate count (%d) <= min_docs_to_rerank (%d), skipping reranking",
                unique_doc_count,
                self.min_docs_to_rerank,
            )
            return query_results

        return await self._batch_rerank(query_results)

    def _count_unique_documents(self, query_results: dict[str, list[tuple[Document, float]]]) -> int:
        unique_docs = set()
        for doc_score_pairs in query_results.values():
            for doc, _ in doc_score_pairs:
                unique_docs.add(id(doc))
        return len(unique_docs)

    async def _batch_rerank(
        self, query_results: dict[str, list[tuple[Document, float]]]
    ) -> dict[str, list[tuple[Document, float]]]:
        pairs_with_metadata: list[tuple[str, str, str, Document]] = []
        for query, doc_score_pairs in query_results.items():
            for doc, _ in doc_score_pairs:
                pairs_with_metadata.append((query, doc.page_content, query, doc))

        all_pairs = [(query, doc_content) for query, doc_content, _, _ in pairs_with_metadata]

        all_scores: list[float] = []
        for start in range(0, len(all_pairs), self.batch_size):
            chunk = all_pairs[start : start + self.batch_size]
            chunk_scores = await self.reranker.rerank_pairs(chunk)
            all_scores.extend(chunk_scores)

        query_reranked_results: dict[str, list[tuple[Document, float]]] = {}
        for (_, _, query_key, doc), score in zip(pairs_with_metadata, all_scores, strict=True):
            if query_key not in query_reranked_results:
                query_reranked_results[query_key] = []
            query_reranked_results[query_key].append((doc, score))

        for query in query_reranked_results:
            query_reranked_results[query].sort(key=lambda x: x[1], reverse=True)

        logger.info(
            "Batch reranking completed: %d queries, batch_size=%d",
            len(query_reranked_results),
            self.batch_size,
        )
        return query_reranked_results
