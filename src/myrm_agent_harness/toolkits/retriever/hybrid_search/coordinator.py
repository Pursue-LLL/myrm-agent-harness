"""混合检索协调器

协调 BM25 稀疏检索 and Vector检索，implements高质量 混合检索。
All模型depends on（embedding, reranker） via MethodParameter显式传入，框架内零隐式depends on。

[INPUT]
- toolkits.retriever.bm25_retrieval::BM25Retriever (POS: BM25 sparse retrieval engine. Builds an in-memory inverted index from document chunks and returns keyword-matched results ranked by BM25 score.)
- toolkits.retriever.embedding::EmbeddingService (POS: Embedding protocol — text to vector abstraction.)
- toolkits.retriever.reranker::RerankerService (POS: Reranker contract layer. Declares the abstract interface and result type that every reranker backend must implement.)

[OUTPUT]
- HybridSearchCoordinator: class — Hybrid Search Coordinator

[POS]
Provides HybridSearchCoordinator.
"""

import asyncio
import logging

from langchain_core.documents import Document

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
    """混合检索协调器

    协调 BM25 稀疏检索 and Vector检索，provides两种检索Mode：
    1.  directly 重SortMode：适 for 小规模文档（< 100）
    2. 混合检索+重SortMode：适 for 大规模文档（> 100）

    All AI 模型（reranker/embedding） via MethodParameter传入， not depends on环境变量。
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
    ) -> list[Document]:
        """directly 重Sort（Skip混合检索，适 for 小规模文档）"""
        if not _validate_inputs(queries, documents, final_top_k):
            return []

        monitor = get_performance_monitor()
        pipeline = RerankingPipeline(reranker)

        async with monitor.track_operation(" directly 重Sort"):
            query_doc_mapping = {q: [(doc, 1.0) for doc in documents] for q in queries}
            query_reranked = await pipeline.rerank_query_results(query_doc_mapping)

        if not query_reranked:
            return []

        fusion = FusionPipeline(
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
        )
        async with monitor.track_operation("Result融合"):
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
    ) -> list[Document]:
        """混合检索 + 重Sort（适 for 大规模文档）"""
        if not _validate_inputs(queries, documents, final_top_k):
            return []

        monitor = get_performance_monitor()
        pipeline = RerankingPipeline(reranker)

        async with monitor.track_operation("混合检索"):
            doc_texts = [doc.page_content for doc in documents]
            query_hybrid_results = await _parallel_hybrid_retrieval(
                queries,
                documents,
                doc_texts,
                hybrid_top_k_per_query,
                embeddings,
            )

        async with monitor.track_operation("重Sort"):
            query_reranked = await pipeline.rerank_query_results(query_hybrid_results)

        if not query_reranked:
            return []

        fusion = FusionPipeline(
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
        )
        async with monitor.track_operation("Result融合"):
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
    ) -> list[Document]:
        """对 already  has   query-doc 映射Perform重Sort"""
        if not query_doc_mapping:
            return []

        total_pairs = sum(len(docs) for docs in query_doc_mapping.values())
        logger.warning(f" rerank_with_mapping: {len(query_doc_mapping)} Query, {total_pairs} pairs")

        monitor = get_performance_monitor()
        pipeline = RerankingPipeline(reranker)

        async with monitor.track_operation("重Sort（带映射）"):
            query_reranked = await pipeline.rerank_query_results(query_doc_mapping)

        if not query_reranked:
            return []

        fusion = FusionPipeline(
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
        )
        async with monitor.track_operation("Result融合"):
            selected = fusion.fuse_query_results(query_reranked, final_top_k)

        monitor.log_performance_summary()
        logger.warning(f" rerank_with_mapping Complete: Return {len(selected)} 个文档")
        return selected


def _validate_inputs(queries: list[str], documents: list[Document], final_top_k: int) -> bool:
    if not queries or not documents:
        logger.warning("QueryList or 文档List is Empty")
        return False
    if final_top_k <= 0:
        logger.warning(f"final_top_k={final_top_k}， no 法ReturnResult")
        return False
    return True


async def _parallel_hybrid_retrieval(
    queries: list[str],
    documents: list[Document],
    doc_texts: list[str],
    top_k: int,
    embeddings: EmbeddingService,
) -> dict[str, list[tuple[Document, float]]]:
    """parallel混合检索：BM25  and Vectorparallel检索，然后 RRF 融合"""
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
            logger.error(f"Query '{query}' 融合Failure: {e}")
            results[query] = []

    return results
