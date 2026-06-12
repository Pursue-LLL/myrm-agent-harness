"""Hybrid search coordinator.

Coordinates BM25 sparse retrieval and vector retrieval for high-quality hybrid search.
All model dependencies (embedding, reranker) are passed explicitly via method parameters.

[INPUT]
- toolkits.retriever.bm25_retrieval::BM25Retriever (POS: BM25 sparse retrieval engine)
- toolkits.retriever.embedding::EmbeddingService (POS: Embedding protocol)
- toolkits.retriever.reranker::RerankerService (POS: Reranker contract layer)
- toolkits.retriever.autocut::AutocutConfig (POS: autocut configuration)

[OUTPUT]
- HybridSearchCoordinator: class — Hybrid Search Coordinator

[POS]
Provides HybridSearchCoordinator.
"""

from __future__ import annotations

import asyncio
import logging

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.autocut import AutocutConfig
from myrm_agent_harness.toolkits.retriever.bm25_retrieval import BM25Retriever
from myrm_agent_harness.toolkits.retriever.embedding import EmbeddingService
from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.toolkits.retriever.hybrid_search.fusion_pipeline import FusionPipeline
from myrm_agent_harness.toolkits.retriever.hybrid_search.reranking_pipeline import RerankingPipeline
from myrm_agent_harness.toolkits.retriever.performance_monitor import get_performance_monitor
from myrm_agent_harness.toolkits.retriever.reranker import RerankerService
from myrm_agent_harness.toolkits.retriever.vector_search import search_with_numpy_retriever

logger = logging.getLogger(__name__)


class HybridSearchCoordinator:
    """Hybrid search coordinator.

    Coordinates BM25 sparse retrieval and vector retrieval with two modes:
    1. Direct reranking: for small document sets (< 100 docs).
    2. Hybrid retrieval + reranking: for large document sets (> 100 docs).

    All AI models (reranker/embedding) are passed via method parameters.
    """

    async def direct_reranking_only(
        self,
        queries: list[str],
        documents: list[Document],
        reranker: RerankerService,
        *,
        final_top_k: int = 10,
        dedup_strategy: str = "content",
        fusion_weights: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        rerank_score_threshold: float = 0.0,
        fusion_score_threshold: float = 0.0,
        autocut_config: AutocutConfig | None = None,
    ) -> list[Document]:
        """Direct reranking (skips hybrid retrieval, for small document sets)."""
        if not _validate_inputs(queries, documents, final_top_k):
            return []

        monitor = get_performance_monitor()
        pipeline = RerankingPipeline(reranker)

        async with monitor.track_operation("direct reranking"):
            query_doc_mapping = {q: [(doc, 1.0) for doc in documents] for q in queries}
            query_reranked = await pipeline.rerank_query_results(query_doc_mapping)

        if not query_reranked:
            return []

        fusion = FusionPipeline(
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
            autocut_config=autocut_config,
        )
        async with monitor.track_operation("result fusion"):
            selected = fusion.fuse_query_results(query_reranked, final_top_k)

        monitor.log_performance_summary()
        return selected

    async def hybrid_retrieval_with_reranking(
        self,
        queries: list[str],
        documents: list[Document],
        reranker: RerankerService,
        embeddings: EmbeddingService,
        *,
        final_top_k: int = 10,
        hybrid_top_k_per_query: int = 20,
        dedup_strategy: str = "content",
        fusion_weights: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        rerank_score_threshold: float = 0.0,
        fusion_score_threshold: float = 0.0,
        autocut_config: AutocutConfig | None = None,
    ) -> list[Document]:
        """Hybrid retrieval + reranking (for large document sets)."""
        if not _validate_inputs(queries, documents, final_top_k):
            return []

        monitor = get_performance_monitor()
        pipeline = RerankingPipeline(reranker)

        async with monitor.track_operation("hybrid retrieval"):
            doc_texts = [doc.page_content for doc in documents]
            query_hybrid_results = await _parallel_hybrid_retrieval(
                queries,
                documents,
                doc_texts,
                hybrid_top_k_per_query,
                embeddings,
            )

        async with monitor.track_operation("reranking"):
            query_reranked = await pipeline.rerank_query_results(query_hybrid_results)

        if not query_reranked:
            return []

        fusion = FusionPipeline(
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
            autocut_config=autocut_config,
        )
        async with monitor.track_operation("result fusion"):
            selected = fusion.fuse_query_results(query_reranked, final_top_k)

        monitor.log_performance_summary()
        return selected

    async def rerank_with_mapping(
        self,
        query_doc_mapping: dict[str, list[tuple[Document, float]]],
        reranker: RerankerService,
        *,
        final_top_k: int = 10,
        dedup_strategy: str = "url",
        fusion_weights: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        rerank_score_threshold: float = 0.0,
        fusion_score_threshold: float = 0.0,
        autocut_config: AutocutConfig | None = None,
    ) -> list[Document]:
        """Rerank with pre-built query-doc mapping."""
        if not query_doc_mapping:
            return []

        total_pairs = sum(len(docs) for docs in query_doc_mapping.values())
        logger.info(f"rerank_with_mapping: {len(query_doc_mapping)} queries, {total_pairs} pairs")

        monitor = get_performance_monitor()
        pipeline = RerankingPipeline(reranker)

        async with monitor.track_operation("reranking (with mapping)"):
            query_reranked = await pipeline.rerank_query_results(query_doc_mapping)

        if not query_reranked:
            return []

        fusion = FusionPipeline(
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
            autocut_config=autocut_config,
        )
        async with monitor.track_operation("result fusion"):
            selected = fusion.fuse_query_results(query_reranked, final_top_k)

        monitor.log_performance_summary()
        logger.info(f"rerank_with_mapping complete: returning {len(selected)} documents")
        return selected


def _validate_inputs(queries: list[str], documents: list[Document], final_top_k: int) -> bool:
    if not queries or not documents:
        logger.warning("Query list or document list is empty")
        return False
    if final_top_k <= 0:
        logger.warning(f"final_top_k={final_top_k}, cannot return results")
        return False
    return True


async def _parallel_hybrid_retrieval(
    queries: list[str],
    documents: list[Document],
    doc_texts: list[str],
    top_k: int,
    embeddings: EmbeddingService,
) -> dict[str, list[tuple[Document, float]]]:
    """Parallel hybrid retrieval: BM25 + vector search in parallel, then RRF fusion."""
    vector_search_task = search_with_numpy_retriever(
        queries=queries,
        documents=documents,
        embeddings=embeddings,
        limit=len(documents),
        score_threshold=0.0,
    )
    bm25_retriever_task = asyncio.to_thread(BM25Retriever, doc_texts)
    query_vector_results, bm25_retriever = await asyncio.gather(vector_search_task, bm25_retriever_task)

    doc_to_idx = {id(doc): idx for idx, doc in enumerate(documents)}

    results: dict[str, list[tuple[Document, float]]] = {}
    for query in queries:
        try:
            bm25_results = bm25_retriever.search(query, top_k=len(documents))
            bm25_scores = dict(bm25_results)

            vector_scores: dict[int, float] = {}
            for doc, score in query_vector_results.get(query, []):
                doc_idx = doc_to_idx.get(id(doc))
                if doc_idx is not None:
                    vector_scores[doc_idx] = score

            bm25_ranked = sorted(bm25_scores.items(), key=lambda x: x[1], reverse=True)
            vector_ranked = sorted(vector_scores.items(), key=lambda x: x[1], reverse=True)
            hybrid_scores = rrf_fusion([bm25_ranked, vector_ranked], k=60, top_k=top_k)

            results[query] = [(documents[idx], score) for idx, score in hybrid_scores if idx < len(documents)]
        except Exception as e:
            logger.error(f"Query '{query}' fusion failed: {e}")
            results[query] = []

    return results
