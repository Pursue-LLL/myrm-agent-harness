"""Web search tools wrapper


[INPUT]
- retriever.autocut::AutocutConfig (POS: score-discontinuity autocut configuration)
- retriever_tools::RetrieverManager, RetrieverConfig (POS: retrieval tools providing BM25 / Reranker with index cache)
- web_search.core.common::SearchResult (POS: search result type)
- web_search.processing._explicit_params::normalize_explicit_params, apply_tavily_site_constraint (POS: Agent explicit param normalizer)
- web_search.processing.search_results_processor::combine_search_results_unified, apply_domain_diversity_sort (POS: search result merger and domain diversity sorting)
- web_search.providers.web_searcher::WebSearcher, SearchServiceConfig, SearchServiceType (POS: web searcher supporting multiple engines)
- utils.context_format::format_documents_with_metadata (POS: document formatting utility)
- utils.text_utils::get_token_count (POS: token counting utility)

[OUTPUT]
- WebSearchTools: web search tools class providing basic/precise two search modes
- SearchServiceConfig: search service config class (re-export)
- SearchServiceType: search service type enum (re-export)

Note: BM25/RRF parameters managed by RetrieverConfig; precise mode internal parameters are constants.

[POS]
Web search tools wrapper. Provides two modes: basic mode (BM25 full-document retrieval without Reranker)
and precise mode (chunk-level semantic filtering, requires Reranker). Basic mode suits most scenarios
with performance priority; precise mode suits long-document scenarios with accuracy priority.
Supports multiple search engines; BM25 index cache managed by RetrieverManager. As the toolkit's
external interface, provides unified web search capability for Agent and business layer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.autocut import AutocutConfig
from myrm_agent_harness.toolkits.retriever.splitter.splitter import TextChunker
from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.core.metrics import web_search_metrics
from myrm_agent_harness.toolkits.web_search.processing._explicit_params import (
    apply_tavily_site_constraint,
    normalize_explicit_params,
)
from myrm_agent_harness.toolkits.web_search.processing.search_results_processor import (
    apply_domain_diversity_sort,
    combine_search_results_unified,
)
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
    SearchServiceConfig,
    SearchServiceType,
    WebSearcher,
)
from myrm_agent_harness.utils.context_format import format_documents_with_metadata
from myrm_agent_harness.utils.text_utils import get_token_count

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.retriever.engine import RetrieverConfig, RetrieverManager
    from myrm_agent_harness.toolkits.retriever.reranker import RerankerConfig, RerankerService

__all__ = ["SearchServiceConfig", "SearchServiceType", "WebSearchTools"]

logger = logging.getLogger(__name__)


class WebSearchTools:
    """Web search tool integrating parallel search + deduplication + ranking.

    Two modes (auto-selected):
    - Basic mode (default): BM25 full-document retrieval -> smart truncation
      No reranker, performance-first, suitable for most scenarios

    - Precision mode (auto-enabled): chunking -> BM25 filtering -> reranker reranking -> merging
      Auto-enabled when reranker_config is provided, accuracy-first, for long documents

    Args:
        config: Search service configuration
        reranker_config: Reranker service configuration (optional), enables precision mode
        retriever_config: Retrieval configuration (optional, for tuning BM25/RRF parameters)
    """

    # Precision mode internal parameters (constants)
    _CHUNK_SIZE: int = 400
    _CHUNK_OVERLAP: int = 100
    _MAX_CHUNKS_PER_DOC: int = 3
    _BM25_TOP_K_CHUNKS: int = 50
    _RERANK_TOP_K: int = 20
    _RERANK_SCORE_THRESHOLD: float = 0.6
    _ENABLE_CHUNK_MERGE: bool = True
    _FUSION_WEIGHTS: tuple[float, float, float, float] = (0.6, 0.1, 0.2, 0.1)
    _FUSION_SCORE_THRESHOLD: float = 0.6
    _AUTOCUT_CONFIG: AutocutConfig = AutocutConfig(enabled=True, jump_ratio=0.2, min_keep=1)

    def __init__(
        self,
        config: SearchServiceConfig,
        reranker_config: RerankerConfig | None = None,
        retriever_config: RetrieverConfig | None = None,
    ):
        from myrm_agent_harness.toolkits.retriever.engine import RetrieverManager

        self._searcher = WebSearcher(config)
        self._retriever_manager = RetrieverManager(retriever_config)

        if reranker_config:
            from myrm_agent_harness.toolkits.retriever.reranker import get_reranker_service

            self._reranker: RerankerService | None = get_reranker_service(reranker_config)
            self._use_precision_mode = True
            logger.info(f"Precision mode enabled with reranker model: {reranker_config.model}")
        else:
            self._reranker = None
            self._use_precision_mode = False

    async def search(self, query: str, num_results: int = 5) -> list[SearchResult]:
        """Single-query basic search."""
        return await self._searcher.search(query, num_results)

    async def fast_search_with_questions(
        self,
        questions: list[str],
        search_results_per_query: int = 10,
        top_k: int = 10,
        explicit_params: dict[str, object] | None = None,
        blocked_hostnames: tuple[str, ...] | None = None,
    ) -> tuple[list[dict[str, object]], str]:
        """Multi-query parallel search + deduplication + ranking (auto-selects optimal mode).

        Two modes (auto-selected):
        - Basic mode (default): BM25 full-document retrieval -> smart truncated output
          - Single query: uses search engine ordering
          - Multi-query: BM25 + RRF fusion
          - No reranker, performance-first

        - Precision mode (optional): chunking -> BM25 filtering -> reranker reranking -> merge adjacent chunks
          - Enabled when: enable_precision_mode=True + reranker configured
          - For: long documents, uncertain key info location, accuracy-first
          - Requires reranker

        Args:
            questions: Query list (rewritten)
            search_results_per_query: Number of search results per query
            top_k: Final number of documents to return
            explicit_params: Agent-level explicit search parameters (highest priority).
                Supported keys: time_range.
            blocked_hostnames: Optional hostname blocklist (exact or ``*.`` wildcard). Results whose
                URL host matches a pattern are dropped before ranking/formatting — a generic content
                policy hook callers can use for benchmark decontamination (e.g. Hugging Face hosts).
                None disables it.

        Returns:
            (sources_metadata, formatted_context). May be empty when every result is filtered out
            by the hostname blocklist — callers treat that as "no usable results", not an error.
        """
        from myrm_agent_harness.toolkits.web_search.processing.intent_optimizer import (
            SearchIntent,
            detect_search_intent,
            extract_and_pin_structured_identifiers,
            resolve_search_params,
        )

        start_time = time.perf_counter()

        provider = self._searcher.config.search_service
        normalized_explicit = normalize_explicit_params(explicit_params, provider) if explicit_params else None

        per_query_overrides: list[dict[str, str | int | bool] | None] = []
        effective_questions: list[str] = []
        bilibili_queries: list[str] = []
        for q in questions:
            # Pin structured domain identifiers (CVE/DOI/tickers) to preserve exact match
            pinned_q, _ = extract_and_pin_structured_identifiers(q)
            intent_result = detect_search_intent(q)
            if intent_result.intent == SearchIntent.PLATFORM_BILIBILI:
                bilibili_queries.append(pinned_q)
            override = resolve_search_params(intent_result, provider)

            # Fusion: explicit_params > intent_optimizer > config.extra_params
            if normalized_explicit:
                override = {**(override or {}), **normalized_explicit}

            search_query = pinned_q
            if provider == "tavily":
                search_query, override = apply_tavily_site_constraint(pinned_q, override)

            effective_questions.append(search_query)
            per_query_overrides.append(override)
            if override:
                logger.info(
                    f"Intent detected: query='{q[:50]}' intent={intent_result.intent.value} "
                    f"confidence={intent_result.confidence:.2f} override={override}"
                )

        # Bilibili fast-path: when all queries target Bilibili, use native API
        if bilibili_queries and len(bilibili_queries) == len(questions):
            from myrm_agent_harness.toolkits.web_search.processing.search_results_processor import (
                search_results_to_documents,
            )
            from myrm_agent_harness.toolkits.web_search.providers.bilibili_search import search_bilibili

            all_bili_results = []
            for q in bilibili_queries:
                bili_results = await search_bilibili(q, max_results=search_results_per_query)
                if bili_results:
                    all_bili_results.extend(bili_results)

            if all_bili_results:
                unified_docs = search_results_to_documents(all_bili_results)
                unified_docs = apply_domain_diversity_sort(unified_docs)
                search_time_ms = (time.perf_counter() - start_time) * 1000
                logger.info(
                    f"Bilibili fast-path: {len(bilibili_queries)} queries, "
                    f"{len(unified_docs)} docs in {search_time_ms:.0f}ms"
                )
            else:
                logger.info("Bilibili fast-path failed, falling back to generic search with site:bilibili.com")
                fallback_questions = [f"{q} site:bilibili.com" for q in questions]
                search_results = await self._searcher.multi_query_parallel_search(
                    fallback_questions, search_results_per_query, [None] * len(fallback_questions)
                )
                _, unified_docs = combine_search_results_unified(search_results)
                unified_docs = apply_domain_diversity_sort(unified_docs)
                search_time_ms = (time.perf_counter() - start_time) * 1000
        else:
            search_results = await self._searcher.multi_query_parallel_search(
                effective_questions, search_results_per_query, per_query_overrides
            )
            _, unified_docs = combine_search_results_unified(search_results)
            unified_docs = apply_domain_diversity_sort(unified_docs)
            search_time_ms = (time.perf_counter() - start_time) * 1000

        if blocked_hostnames:
            unified_docs = _drop_blocked_hostname_docs(unified_docs, blocked_hostnames)

        # Evaluate document characteristics to decide precision mode
        avg_doc_tokens = (
            sum(get_token_count(d.page_content) for d in unified_docs) / len(unified_docs) if unified_docs else 0
        )
        has_long_docs = avg_doc_tokens > 1500

        # Select processing path based on mode
        ranking_start = time.perf_counter()

        # Precision mode trigger: enabled + (multi-query OR long document scenario)
        if self._use_precision_mode and (len(questions) > 1 or has_long_docs):
            # Precision mode: chunking -> BM25 -> reranker -> merge
            assert self._reranker is not None, "Precision mode requires reranker"
            logger.info(
                f"Precision mode: {len(questions)} queries, {len(unified_docs)} docs, "
                f"avg_tokens={avg_doc_tokens:.0f}, chunk_size={self._CHUNK_SIZE}"
            )
            selected_docs = await _precision_mode_search(
                questions, unified_docs, self._reranker, self, self._retriever_manager
            )
        else:
            # Basic mode: Dual-track hybrid consensus (search engine prior + BM25 consensus) -> smart truncation
            logger.info(
                f"Basic mode (dual-track RRF): {len(questions)} queries, {len(unified_docs)} docs, top_k={top_k}"
            )
            selected_docs = await self._retriever_manager.bm25_retrieval_only(
                queries=questions,
                documents=unified_docs,
                top_k=top_k,
            )

        ranking_time_ms = (time.perf_counter() - ranking_start) * 1000
        total_time_ms = (time.perf_counter() - start_time) * 1000

        mode_str = "precision" if self._use_precision_mode else "basic"
        logger.info(
            f"Search completed [{mode_str}]: queries={len(questions)}, unified={len(unified_docs)}, "
            f"selected={len(selected_docs)}, search_time={search_time_ms:.0f}ms, "
            f"ranking_time={ranking_time_ms:.0f}ms, total={total_time_ms:.0f}ms"
        )

        if total_time_ms > 5000:
            logger.warning(f"Slow search detected: {total_time_ms:.0f}ms for {len(questions)} queries")

        sources_metadata, formatted_context, truncation_stats = format_documents_with_metadata(
            selected_docs,
            questions=questions,
        )

        if truncation_stats:
            logger.info(
                f"Token usage: {truncation_stats.original_tokens}→{truncation_stats.final_tokens}, "
                f"retention={truncation_stats.retention_ratio:.1%}"
            )

        return sources_metadata, formatted_context


def _cap_chunks_per_doc(
    chunks: list[Document],
    max_chunks_per_doc: int,
) -> list[Document]:
    """Select top relevance chunks per document, maintaining global rerank order.

    Each chunk remains an independent, semantically coherent search snippet with distinct chunk boundaries.

    Args:
        chunks: Reranker-sorted chunk list (descending by relevance)
        max_chunks_per_doc: Max chunks to keep per document URL

    Returns:
        Filtered document list with at most max_chunks_per_doc chunks per URL.
    """
    if not chunks or max_chunks_per_doc <= 0:
        return chunks

    from collections import Counter

    url_counts: Counter[str] = Counter()
    selected: list[Document] = []

    for chunk in chunks:
        url = (chunk.metadata or {}).get("url", "unknown")
        if url_counts[url] < max_chunks_per_doc:
            url_counts[url] += 1
            selected.append(chunk)

    logger.info(
        f"Chunk capping: {len(chunks)} chunks → {len(selected)} chunks "
        f"(max {max_chunks_per_doc} per doc, preserving discrete boundaries and rerank order)"
    )
    return selected


def _merge_adjacent_chunks(
    chunks: list[Document],
    max_chunks_per_doc: int,
    enable_merge: bool = True,
) -> list[Document]:
    """Compatibility alias for per-document chunk capping."""
    if not chunks or not enable_merge:
        return chunks
    return _cap_chunks_per_doc(chunks, max_chunks_per_doc)


async def _chunk_document_async(
    doc: Document,
    text_chunker: TextChunker,
    chunk_threshold: int,
) -> tuple[list[Document], bool]:
    """Chunk a single document concurrently.

    Args:
        doc: Document to process
        text_chunker: Text chunker
        chunk_threshold: Chunking threshold (tokens)

    Returns:
        (chunk_list, was_chunked)
        - chunk_list: Chunked document list (original doc if not chunked)
        - was_chunked: True if chunked, False if kept intact
    """
    token_count = await asyncio.to_thread(get_token_count, doc.page_content)

    if token_count > chunk_threshold:
        chunks = await asyncio.to_thread(text_chunker.chunk_text, doc.page_content, document_metadata=doc.metadata)
        return chunks, True
    else:
        return [doc], False


async def _precision_mode_search(
    questions: list[str],
    unified_docs: list[Document],
    reranker: RerankerService,
    tools: WebSearchTools,
    retriever_manager: RetrieverManager,
) -> list[Document]:
    """Precision mode search: chunk-level semantic filtering.

    Pipeline:
    1. Smart chunking: chunk long docs (>1000 tokens), keep short ones intact, concurrent processing
    2. BM25 coarse filtering: select top-50 from all chunks
    3. Reranker fine ranking: semantic reranking, output top-20
    4. Per-document chunk capping: keep top-N chunks per URL without content merging

    Args:
        questions: Query list
        unified_docs: Original documents from search engine
        reranker: Reranker service instance
        tools: WebSearchTools instance (for accessing internal parameters)
        retriever_manager: Retrieval manager

    Returns:
        Processed document list
    """
    chunk_start = time.perf_counter()

    text_chunker = TextChunker(min_chunk_tokens=tools._CHUNK_SIZE, model_name="gpt-4")

    # Only chunk long docs, threshold = 2.5x chunk_size (avoids over-chunking short docs)
    chunk_threshold = int(tools._CHUNK_SIZE * 2.5)

    # Concurrently chunk all documents
    tasks = [_chunk_document_async(doc, text_chunker, chunk_threshold) for doc in unified_docs]
    results = await asyncio.gather(*tasks)

    # Collect results
    all_chunks = []
    chunked_count = 0
    kept_intact_count = 0

    for chunks, is_chunked in results:
        all_chunks.extend(chunks)
        if is_chunked:
            chunked_count += 1
        else:
            kept_intact_count += 1

    chunk_time_ms = (time.perf_counter() - chunk_start) * 1000
    logger.info(
        f"Chunking: {len(unified_docs)} docs → {len(all_chunks)} chunks "
        f"(chunked={chunked_count}, intact={kept_intact_count}) in {chunk_time_ms:.0f}ms"
    )

    # 2. BM25 filter top-50 chunks
    bm25_start = time.perf_counter()
    bm25_filtered = await retriever_manager.bm25_retrieval_only(
        queries=questions, documents=all_chunks, top_k=tools._BM25_TOP_K_CHUNKS
    )
    bm25_time_ms = (time.perf_counter() - bm25_start) * 1000
    logger.info(f"BM25 filtering: {len(all_chunks)} chunks → {len(bm25_filtered)} chunks in {bm25_time_ms:.0f}ms")

    if not bm25_filtered:
        logger.warning("BM25 returned 0 chunks in precision mode")
        return []

    # 3. Reranker rerank top-20 chunks, auto-degrade to BM25 on failure
    rerank_start = time.perf_counter()
    query_doc_mapping = {q: [(doc, 1.0) for doc in bm25_filtered] for q in questions}
    degraded = False

    try:
        reranked_chunks = await retriever_manager.rerank_with_mapping(
            query_doc_mapping=query_doc_mapping,
            reranker=reranker,
            final_top_k=tools._RERANK_TOP_K,
            dedup_strategy="content",
            fusion_weights=tools._FUSION_WEIGHTS,
            rerank_score_threshold=tools._RERANK_SCORE_THRESHOLD,
            fusion_score_threshold=tools._FUSION_SCORE_THRESHOLD,
            autocut_config=tools._AUTOCUT_CONFIG,
        )
    except Exception as e:
        logger.error(
            f"Reranker failed: {e}. Falling back to BM25 results. "
            f"THIS IS A DEGRADED RESPONSE! Please check Reranker service health.",
            exc_info=True,
        )
        try:
            from myrm_agent_harness.utils.event_utils import dispatch_custom_event

            await dispatch_custom_event(
                "agent_status",
                {
                    "event": "tool_fallback",
                    "tool": "web_search_tool",
                    "fallback_type": "reranker_degraded",
                    "message": "语义重排服务异常，已自动降级为 BM25 基础检索以保证结果返回...",
                },
            )
        except Exception:
            pass
        web_search_metrics.record_reranker_degraded()
        reranked_chunks = bm25_filtered[: tools._RERANK_TOP_K]
        degraded = True

    rerank_time_ms = (time.perf_counter() - rerank_start) * 1000

    if degraded:
        logger.warning(
            f"Reranker degraded: using BM25 fallback, {len(bm25_filtered)} chunks → "
            f"{len(reranked_chunks)} chunks in {rerank_time_ms:.0f}ms"
        )
        for doc in reranked_chunks:
            doc.metadata["_degraded_mode"] = "reranker_failed"
    else:
        logger.info(f"Reranker: {len(bm25_filtered)} chunks → {len(reranked_chunks)} chunks in {rerank_time_ms:.0f}ms")

    if not reranked_chunks:
        logger.warning("No chunks available after reranking/degradation in precision mode")
        return []

    # 4. Limit chunks per document
    cap_start = time.perf_counter()
    capped_docs = _cap_chunks_per_doc(
        reranked_chunks,
        max_chunks_per_doc=tools._MAX_CHUNKS_PER_DOC,
    )
    cap_time_ms = (time.perf_counter() - cap_start) * 1000
    logger.info(f"Chunk capping: {len(reranked_chunks)} chunks → {len(capped_docs)} docs in {cap_time_ms:.0f}ms")

    total_time_ms = (time.perf_counter() - chunk_start) * 1000
    logger.info(
        f"Precision mode total: {total_time_ms:.0f}ms "
        f"(chunk={chunk_time_ms:.0f}ms, bm25={bm25_time_ms:.0f}ms, "
        f"rerank={rerank_time_ms:.0f}ms, cap={cap_time_ms:.0f}ms)"
    )

    return capped_docs


def _drop_blocked_hostname_docs(
    documents: list[Document],
    blocked_hostnames: tuple[str, ...],
) -> list[Document]:
    """Drop documents whose URL host matches the blocklist (exact or ``*.`` wildcard).

    Applied to raw search results before ranking/formatting so filtered hosts never
    surface in the LLM context — a generic content policy hook (benchmark decontamination
    uses it to hide Hugging Face results that may carry reference material).
    """
    from myrm_agent_harness.toolkits.browser.domain_filter import DomainBlocklist

    blocklist = DomainBlocklist.from_strings(blocked_hostnames)
    kept: list[Document] = []
    dropped = 0
    for doc in documents:
        hostname = (urlparse(str((doc.metadata or {}).get("url") or "")).hostname or "").lower()
        if hostname and blocklist.is_blocked(hostname):
            dropped += 1
            continue
        kept.append(doc)
    if dropped:
        logger.info(
            "Hostname blocklist dropped %d search result(s) before formatting",
            dropped,
        )
    return kept
