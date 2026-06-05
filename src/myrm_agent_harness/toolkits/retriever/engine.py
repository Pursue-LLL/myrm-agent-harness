"""Retrieval tools


[INPUT]
- retriever.bm25_retrieval::BM25Retriever (POS: BM25 retriever class, build index once query many times)
- retriever.preprocessing::create_document_chunks_from_crawl_results (POS: document preprocessing, convert crawl results to document chunks)
- retriever.fusion_strategies::rrf_fusion (POS: RRF fusion strategy, merge multiple retrieval results)
- retriever.hybrid_retriever::hybrid_retriever (POS: hybrid retriever, combining vector and keyword search)
- web_fetch::SuccessResult, FailedResult (POS: web crawl result types)
- utils.context_format::format_documents_with_metadata (POS: document formatting utility)
- utils.hash_utils::get_content_hash (POS: content hash calculation for BM25 index cache keys)
- utils.text_utils::is_cross_language (POS: cross-language detection, fallback when BM25 has zero recall)
- pydantic::BaseModel, Field (POS: configuration validation)

[OUTPUT]
- RetrieverConfig: retrieval config class, unified management of retrieval parameters (cache size, sample size, etc.)
- RetrieverManager: retrieval manager class, providing hybrid retrieval and reranking (with BM25 index cache)
- BM25CacheStats: BM25 index cache statistics class (hit rate, request count, evictions, memory usage)

[POS]
Retrieval tools wrapper. Provides hybrid retrieval and reranking, integrating BM25, vector search,
and Reranker with multi-query fusion support. Includes BM25 index cache (LRU policy), computing cache
keys from document URL hashes (order-independent), reusing built indexes for identical document sets.
As the toolkit's external interface, provides unified retrieval capability for Agent and business layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field

from myrm_agent_harness.toolkits.retriever.bm25_retrieval import BM25Retriever
from myrm_agent_harness.toolkits.retriever.embedding import EmbeddingService
from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.toolkits.retriever.hybrid_retriever import hybrid_retriever
from myrm_agent_harness.toolkits.retriever.preprocessing import create_document_chunks_from_crawl_results
from myrm_agent_harness.toolkits.retriever.reranker import RerankerService
from myrm_agent_harness.toolkits.web_fetch import FailedResult, SuccessResult
from myrm_agent_harness.utils.context_format import format_documents_with_metadata
from myrm_agent_harness.utils.hash_utils import get_content_hash
from myrm_agent_harness.utils.text_utils import is_cross_language

logger = logging.getLogger(__name__)


class RetrieverConfig(BaseModel):
    """Retrieval configuration (tunable per scenario, supports runtime adjustment).

    Fields:
    - bm25_cache_max_size: Max BM25 index cache entries (LRU eviction)
    - content_hash_sample_size: Content hash sample size (chars, for cache key computation)
    - hybrid_top_k_per_query: Docs returned per query in hybrid retrieval
    - rrf_k_parameter: RRF fusion k parameter (larger = more friendly to lower-ranked results)
    - bm25_candidate_multiplier: BM25 candidate pool expansion factor (for pre-filtering)
    """

    model_config = ConfigDict()

    bm25_cache_max_size: int = Field(default=10, ge=1, le=100, description="Max BM25 index cache entries")
    content_hash_sample_size: int = Field(default=500, ge=100, le=5000, description="Content hash sample size (chars)")
    hybrid_top_k_per_query: int = Field(
        default=50, ge=10, le=200, description="Docs returned per query in hybrid retrieval"
    )
    rrf_k_parameter: int = Field(default=60, ge=1, le=1000, description="RRF fusion k parameter")
    bm25_candidate_multiplier: int = Field(default=2, ge=1, le=10, description="BM25 candidate pool expansion factor")


DEFAULT_RETRIEVER_CONFIG = RetrieverConfig()


@dataclass
class BM25CacheStats:
    """BM25 index cache statistics."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    last_eviction_time: float = 0.0
    total_cached_docs: int = 0

    @property
    def hit_rate(self) -> float:
        """Cache hit rate."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    @property
    def total_requests(self) -> int:
        """Total request count."""
        return self.hits + self.misses

    @property
    def cache_memory_mb(self) -> float:
        """Estimated cache memory usage (MB)

        Based on measured data: BM25Retriever averages ~0.13KB per document
        (including index structure overhead; 100 docs ≈ 13.5KB measured)
        """
        return self.total_cached_docs * 0.13 / 1024


class RetrieverManager:
    """Retrieval manager providing hybrid search and reranking

    Core methods:
    - retrieve_from_crawl_results: Retrieve from crawl results (auto-selects optimal strategy)
    - direct_reranking_only: Direct reranking (for small document sets)
    - hybrid_retrieval_with_reranking: Hybrid retrieval + reranking (for large document sets)
    - bm25_retrieval_only: Pure BM25 retrieval (fast filtering, with index cache)
    - retrieve_from_urls: Crawl URLs and retrieve relevant content

    Features:
    - BM25 index cache (LRU): reuses built index for same document set
    - Cache key based on sorted URL hash, order-independent
    - Cache stats: hit_rate, total_requests, cache_memory_mb
    - Performance tracking: slow query logging, BM25 recall rate
    """

    def __init__(self, config: RetrieverConfig | None = None):
        # Deep copy to avoid race conditions from shared config
        self.config = (config or DEFAULT_RETRIEVER_CONFIG).model_copy(deep=True)
        self._bm25_cache: dict[str, BM25Retriever] = {}
        self._bm25_cache_order: list[str] = []
        self._bm25_cache_doc_counts: dict[str, int] = {}
        self.bm25_cache_stats = BM25CacheStats()
        self._cache_lock = asyncio.Lock()

    def _compute_bm25_cache_key(self, documents: list[Document]) -> str:
        """Compute BM25 index cache key (order-independent, URL-hash based)

        Strategy selection:
        - Prefer URLs (search result scenario, best performance)
        - Fall back to content hash (generic document scenario, best accuracy)

        Optimization: frozenset + sorted ensures order-independence, O(n log n)

        Args:
            documents: Document list

        Returns:
            Cache key (hash string)
        """
        if all(doc.metadata.get("url") for doc in documents):
            url_set = frozenset(doc.metadata["url"] for doc in documents)
            return get_content_hash(str(sorted(url_set)), strategy="builtin", use_cache=False)

        sample_size = self.config.content_hash_sample_size
        hash_set = frozenset(
            get_content_hash(doc.page_content[:sample_size], strategy="builtin", use_cache=False) for doc in documents
        )
        return get_content_hash(str(sorted(hash_set)), strategy="builtin", use_cache=False)

    def _touch_bm25_cache_hit(self, cache_key: str, doc_count: int) -> BM25Retriever:
        """Update LRU and hit stats while holding `_cache_lock`, then return cached instance."""
        self.bm25_cache_stats.hits += 1
        self._bm25_cache_order.remove(cache_key)
        self._bm25_cache_order.append(cache_key)
        logger.debug(
            f"BM25 cache hit: docs={doc_count}, rate={self.bm25_cache_stats.hit_rate:.1%}, "
            f"memory={self.bm25_cache_stats.cache_memory_mb:.2f}MB"
        )
        return self._bm25_cache[cache_key]

    async def _get_cached_bm25_retriever(self, documents: list[Document]) -> BM25Retriever:
        """Get or create a cached BM25 retriever (LRU, coroutine-safe)

        Implementation: `BM25Retriever` is built outside the lock; the locked phase only performs
        cache key lookup, LRU update, and miss insertion/eviction. Concurrency covered by `tests/toolkits/web_search/test_concurrent_safety.py`.

        Args:
            documents: Document list

        Returns:
            BM25 retriever instance
        """
        cache_key = self._compute_bm25_cache_key(documents)
        doc_count = len(documents)

        async with self._cache_lock:
            if cache_key in self._bm25_cache:
                return self._touch_bm25_cache_hit(cache_key, doc_count)

        doc_contents = [doc.page_content for doc in documents]
        start_time = time.perf_counter()
        built = BM25Retriever(doc_contents)
        build_time_ms = (time.perf_counter() - start_time) * 1000

        async with self._cache_lock:
            if cache_key in self._bm25_cache:
                return self._touch_bm25_cache_hit(cache_key, doc_count)

            self.bm25_cache_stats.misses += 1
            self._bm25_cache[cache_key] = built
            self._bm25_cache_order.append(cache_key)
            self._bm25_cache_doc_counts[cache_key] = doc_count
            self.bm25_cache_stats.total_cached_docs += doc_count

            if len(self._bm25_cache) > self.config.bm25_cache_max_size:
                oldest_key = self._bm25_cache_order.pop(0)
                evicted_doc_count = self._bm25_cache_doc_counts.pop(oldest_key, 0)
                del self._bm25_cache[oldest_key]
                self.bm25_cache_stats.evictions += 1
                self.bm25_cache_stats.last_eviction_time = time.time()
                self.bm25_cache_stats.total_cached_docs -= evicted_doc_count

            logger.debug(
                f"BM25 cache miss: docs={doc_count}, build_time={build_time_ms:.2f}ms, "
                f"rate={self.bm25_cache_stats.hit_rate:.1%}, memory={self.bm25_cache_stats.cache_memory_mb:.2f}MB"
            )
            return built

    async def retrieve_from_crawl_results(
        self,
        queries: str | list[str],
        reranker: RerankerService,
        embeddings: EmbeddingService,
        *,
        top_k: int = 10,
        pre_crawled_results: tuple[SuccessResult, FailedResult] = ([], []),
        hybrid_top_k_per_query: int | None = None,
        fusion_weights: tuple[float, float, float, float] | None = None,
        rerank_score_threshold: float = 0.0,
        fusion_score_threshold: float = 0.0,
    ) -> tuple[list[dict[str, object]], str]:
        """Retrieve relevant docs from crawl results and return formatted text (auto-selects optimal strategy)

        Strategy selection:
        - Chunks ≤ hybrid_top_k_per_query: direct reranking
        - Chunks > hybrid_top_k_per_query: hybrid retrieval (BM25 + vector) + reranking
        """
        hybrid_top_k_per_query = hybrid_top_k_per_query or self.config.hybrid_top_k_per_query
        fusion_weights = fusion_weights or (1.0, 0.0, 0.0, 0.0)

        success_results, _ = pre_crawled_results

        if not success_results:
            logger.warning("All URLs failed to crawl")
            return [], ""

        query_list = queries if isinstance(queries, list) else [queries]

        all_chunk_documents = await create_document_chunks_from_crawl_results(
            success_results,
            queries=query_list,
        )
        logger.info(f"Successfully created {len(all_chunk_documents)} document chunks")

        if not all_chunk_documents:
            return [], ""

        logger.info(f"Unified document pool: {len(all_chunk_documents)} chunks, {len(query_list)} queries")

        if len(all_chunk_documents) <= hybrid_top_k_per_query:
            logger.info(
                f"Document count ({len(all_chunk_documents)}) <= {hybrid_top_k_per_query}, using direct reranking"
            )
            relevant_docs = await hybrid_retriever.direct_reranking_only(
                queries=query_list,
                documents=all_chunk_documents,
                reranker=reranker,
                final_top_k=top_k,
                dedup_strategy="content",
                fusion_weights=fusion_weights,
                rerank_score_threshold=rerank_score_threshold,
                fusion_score_threshold=fusion_score_threshold,
            )
        else:
            logger.info(
                f"Document count ({len(all_chunk_documents)}) > {hybrid_top_k_per_query}, using hybrid retrieval + reranking"
            )
            relevant_docs = await hybrid_retriever.hybrid_retrieval_with_reranking(
                queries=query_list,
                documents=all_chunk_documents,
                reranker=reranker,
                embeddings=embeddings,
                final_top_k=top_k,
                hybrid_top_k_per_query=hybrid_top_k_per_query,
                dedup_strategy="content",
                fusion_weights=fusion_weights,
                rerank_score_threshold=rerank_score_threshold,
                fusion_score_threshold=fusion_score_threshold,
            )

        sources_metadata, formatted_context, _ = format_documents_with_metadata(
            relevant_docs,
            questions=query_list,
        )
        return sources_metadata, formatted_context

    async def direct_reranking_only(
        self,
        queries: list[str],
        documents: list[Document],
        reranker: RerankerService,
        *,
        final_top_k: int = 10,
        dedup_strategy: str = "content",
        fusion_weights: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 0.0),
        rerank_score_threshold: float = 0.6,
        fusion_score_threshold: float = 0.6,
    ) -> list[Document]:
        """Direct reranking entry point, skipping hybrid retrieval (for small document sets)."""
        return await hybrid_retriever.direct_reranking_only(
            queries=queries,
            documents=documents,
            reranker=reranker,
            final_top_k=final_top_k,
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
        )

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
        """Hybrid retrieval + reranking entry point."""
        return await hybrid_retriever.hybrid_retrieval_with_reranking(
            queries=queries,
            documents=documents,
            reranker=reranker,
            embeddings=embeddings,
            final_top_k=final_top_k,
            hybrid_top_k_per_query=hybrid_top_k_per_query,
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
        )

    async def bm25_retrieval_only(
        self,
        queries: list[str],
        documents: list[Document],
        top_k: int = 10,
    ) -> list[Document]:
        """Pure BM25 retrieval (with index cache)

        Uses cached BM25 retriever + RRF fusion. Queries on the same document set reuse the built index.

        Args:
            queries: Query list
            documents: Unified document pool
            top_k: Final number of documents to return

        Returns:
            BM25-retrieved relevant document list
        """
        start_time = time.perf_counter()

        if not documents:
            return []

        if not queries:
            return documents[:top_k]

        retriever = await self._get_cached_bm25_retriever(documents)

        query_results: list[list[tuple[int, float]]] = []
        total_raw_results = 0
        for query in queries:
            results = retriever.search(query, top_k * self.config.bm25_candidate_multiplier, only_relevant=True)
            query_results.append(results)
            total_raw_results += len(results)

        fused_results = rrf_fusion(query_results, k=self.config.rrf_k_parameter, top_k=top_k)
        selected_docs = [documents[idx] for idx, _ in fused_results if idx < len(documents)]

        elapsed_ms = (time.perf_counter() - start_time) * 1000
        recall_rate = len(selected_docs) / min(top_k, len(documents)) if documents else 0.0

        logger.info(
            f"BM25 retrieval: queries={len(queries)}, docs={len(documents)}, "
            f"raw_results={total_raw_results}, selected={len(selected_docs)}, "
            f"recall={recall_rate:.1%}, elapsed={elapsed_ms:.2f}ms, "
            f"cache_hit_rate={self.bm25_cache_stats.hit_rate:.1%}"
        )

        if elapsed_ms > 1000:
            logger.warning(
                f"Slow BM25 query detected: {elapsed_ms:.0f}ms for {len(queries)} queries on {len(documents)} docs"
            )

        if not selected_docs and documents and is_cross_language(queries, documents):
            logger.warning("BM25 zero recall with cross-language detected, returning top_k by original order")
            return documents[:top_k]

        return selected_docs

    async def bm25_retrieval_with_mapping(
        self,
        queries: list[str],
        documents: list[Document],
        top_k_per_query: int = 20,
    ) -> dict[str, list[tuple[Document, float]]]:
        """BM25 retrieval preserving query-doc mappings (with index cache)

        Difference from bm25_retrieval_only:
        - bm25_retrieval_only: Returns fused document list, loses query-doc mappings
        - bm25_retrieval_with_mapping: Returns per-query results, preserves mappings

        Use case:
        - Pass BM25 results to reranking stage, avoiding redundant query-doc pair matching

        Args:
            queries: Query list
            documents: Unified document pool
            top_k_per_query: Documents returned per query

        Returns:
            Retrieval results per query {query: [(doc, bm25_score), ...]}
        """
        if not documents or not queries:
            return {}

        retriever = await self._get_cached_bm25_retriever(documents)

        query_doc_mapping: dict[str, list[tuple[Document, float]]] = {}
        for query in queries:
            results = retriever.search(query, top_k_per_query, only_relevant=True)
            query_doc_mapping[query] = [(documents[idx], score) for idx, score in results if idx < len(documents)]

        return query_doc_mapping

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
        """Rerank existing query-doc mappings (uses provided mappings directly, avoids redundant pairs)."""
        return await hybrid_retriever.rerank_with_mapping(
            query_doc_mapping=query_doc_mapping,
            reranker=reranker,
            final_top_k=final_top_k,
            dedup_strategy=dedup_strategy,
            fusion_weights=fusion_weights,
            rerank_score_threshold=rerank_score_threshold,
            fusion_score_threshold=fusion_score_threshold,
        )

    async def retrieve_from_urls(
        self,
        urls: list[str],
        questions: str | list[str],
        reranker: RerankerService,
        embeddings: EmbeddingService,
        *,
        top_k: int = 10,
        use_raw_markdown: bool = False,
        allow_private_networks: bool = False,
    ) -> tuple[list[dict[str, object]], str, str | None]:
        """Crawl webpages and retrieve relevant content snippets

        Args:
            urls: Target webpage URL list
            questions: Retrieval queries (single string or list)
            reranker: Reranker service instance
            embeddings: Embedding service instance
            top_k: Maximum document chunks to return
            use_raw_markdown: Whether to use raw markdown format
            allow_private_networks: Skip SSRF private-IP blocking (local mode).

        Returns:
            (metadata list, formatted context, error info)
        """
        from myrm_agent_harness.toolkits.web_fetch import CrawlEngine, web_fetch_tools

        if not urls:
            return [], "", "No URLs provided"

        if not questions:
            return [], "", "No queries provided"

        try:
            engine = CrawlEngine(
                use_raw_markdown=use_raw_markdown,
                allow_private_networks=allow_private_networks,
                session_vault=web_fetch_tools._http_fetcher._session_vault,
            )
            success_results, failed_results = await engine.crawl_many(urls)

            if not success_results:
                error_msg = "All URLs failed to crawl"
                if failed_results:
                    failed_urls = [url for url, _ in failed_results]
                    error_msg = f"Failed to crawl URLs: {failed_urls}"
                return [], "", error_msg

            query_list = questions if isinstance(questions, list) else [questions]

            url_metadata_list, formatted_context = await self.retrieve_from_crawl_results(
                query_list,
                reranker,
                embeddings,
                top_k=top_k,
                pre_crawled_results=(success_results, failed_results),
            )

            return url_metadata_list, formatted_context, ""

        except Exception as e:
            error_msg = str(e).split("\n")[0][:200]
            logger.error(f"Retrieve from URLs failed: {error_msg}")
            return [], "", f"Retrieve from URLs failed: {e!s}"


__all__ = [
    "DEFAULT_RETRIEVER_CONFIG",
    "BM25CacheStats",
    "RetrieverConfig",
    "RetrieverManager",
]
