"""Web search tools wrapper


[INPUT]
- retriever.autocut::AutocutConfig (POS: score-discontinuity autocut configuration)
- retriever_tools::RetrieverManager, RetrieverConfig (POS: retrieval tools providing BM25 / Reranker with index cache)
- web_search.common::SearchResult (POS: search result type)
- web_search.search_results_processor::combine_search_results_unified (POS: search result merger)
- web_search.web_searcher::WebSearcher, SearchServiceConfig, SearchServiceType (POS: web searcher supporting multiple engines)
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

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.autocut import AutocutConfig
from myrm_agent_harness.toolkits.retriever.splitter.splitter import TextChunker
from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.metrics import web_search_metrics
from myrm_agent_harness.toolkits.web_search.search_results_processor import combine_search_results_unified
from myrm_agent_harness.toolkits.web_search.web_searcher import SearchServiceConfig, SearchServiceType, WebSearcher
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

        Raises:
            ValueError: When all queries return 0 results
        """
        from myrm_agent_harness.toolkits.web_search.intent_optimizer import (
            detect_search_intent,
            resolve_search_params,
        )

        start_time = time.perf_counter()

        provider = self._searcher.config.search_service
        per_query_overrides: list[dict[str, str] | None] = []
        for q in questions:
            intent_result = detect_search_intent(q)
            override = resolve_search_params(intent_result, provider)
            per_query_overrides.append(override)
            if override:
                logger.info(
                    f"Intent detected: query='{q[:50]}' intent={intent_result.intent.value} "
                    f"confidence={intent_result.confidence:.2f} override={override}"
                )

        search_results = await self._searcher.multi_query_parallel_search(
            questions, search_results_per_query, per_query_overrides
        )
        _, unified_docs = combine_search_results_unified(search_results)
        search_time_ms = (time.perf_counter() - start_time) * 1000

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
            # Basic mode: BM25 full-document retrieval -> smart truncation
            if len(questions) <= 1:
                logger.info(f"Basic mode (single query): selecting top {top_k} from {len(unified_docs)} docs")
                selected_docs = unified_docs[:top_k]
            else:
                logger.info(f"Basic mode (multi-query BM25): {len(questions)} queries, {len(unified_docs)} docs")
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


def _merge_adjacent_chunks(
    chunks: list[Document],
    max_chunks_per_doc: int,
    enable_merge: bool,
) -> list[Document]:
    """Smart merge: only merge consecutive chunks, preserving semantic coherence.

    Algorithm:
    1. Group by URL
    2. Detect consecutive chunk sequences within each group (by chunk_index)
    3. Only merge consecutive chunks (e.g. [3,4,5]), not disjoint ones (e.g. [3,15,23])
    4. Select most relevant consecutive groups (up to max_chunks_per_doc)

    Args:
        chunks: Reranker-sorted chunk list (descending by relevance)
        max_chunks_per_doc: Max consecutive groups to keep per document
        enable_merge: Whether to enable adjacent chunk merging

    Returns:
        Processed document list (semantically coherent)
    """
    if not chunks or not enable_merge:
        return chunks

    # Group by document URL, preserving reranker relevance order and chunk_index
    doc_groups: dict[str, list[tuple[int, int, Document]]] = {}
    for rerank_order, chunk in enumerate(chunks):
        url = chunk.metadata.get("url", "unknown")
        chunk_index = chunk.metadata.get("chunk_index", -1)

        if url not in doc_groups:
            doc_groups[url] = []
        doc_groups[url].append((rerank_order, chunk_index, chunk))

    merged_docs = []

    for group in doc_groups.values():
        # Sort by chunk_index (positional order in original document)
        group_by_chunk_index = sorted(group, key=lambda x: x[1])

        # Detect consecutive chunk sequences
        continuous_sequences = []
        current_sequence = [group_by_chunk_index[0]]

        for i in range(1, len(group_by_chunk_index)):
            _prev_rerank_order, prev_chunk_idx, _prev_chunk = group_by_chunk_index[i - 1]
            _curr_rerank_order, curr_chunk_idx, _curr_chunk = group_by_chunk_index[i]

            # Check continuity (chunk_index=-1 treated as standalone chunk)
            if curr_chunk_idx != -1 and prev_chunk_idx != -1 and curr_chunk_idx == prev_chunk_idx + 1:
                # Consecutive, append to current sequence
                current_sequence.append(group_by_chunk_index[i])
            else:
                # Not consecutive, save current sequence and start new one
                continuous_sequences.append(current_sequence)
                current_sequence = [group_by_chunk_index[i]]

        # Save the last sequence
        continuous_sequences.append(current_sequence)

        # Sort sequences by highest relevance (lowest rerank_order in sequence)
        continuous_sequences.sort(key=lambda seq: min(item[0] for item in seq))

        # Select top max_chunks_per_doc most relevant consecutive sequences
        for sequence in continuous_sequences[:max_chunks_per_doc]:
            if len(sequence) == 1:
                # Single chunk, add directly
                _, _, chunk = sequence[0]
                merged_docs.append(chunk)
            else:
                # Multiple consecutive chunks, merge content (by chunk_index order)
                sequence_sorted = sorted(sequence, key=lambda x: x[1])
                merged_content = "\n\n".join(chunk.page_content for _, _, chunk in sequence_sorted)

                # Use first chunk metadata
                merged_metadata = sequence_sorted[0][2].metadata.copy()
                merged_metadata["merged_chunks_count"] = len(sequence)
                merged_metadata["merged_chunk_indices"] = [chunk_idx for _, chunk_idx, _ in sequence_sorted]

                merged_doc = Document(page_content=merged_content, metadata=merged_metadata)
                merged_docs.append(merged_doc)

    logger.info(
        f"Chunk merge: {len(chunks)} chunks → {len(merged_docs)} merged documents "
        f"(continuous sequences only, preserving semantic coherence)"
    )
    return merged_docs


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
    4. Smart merge: merge consecutive chunks, limit to 3 passage groups per document

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

    # 4. Merge adjacent chunks + limit chunks per document
    merge_start = time.perf_counter()
    merged_docs = _merge_adjacent_chunks(
        reranked_chunks,
        max_chunks_per_doc=tools._MAX_CHUNKS_PER_DOC,
        enable_merge=tools._ENABLE_CHUNK_MERGE,
    )
    merge_time_ms = (time.perf_counter() - merge_start) * 1000
    logger.info(f"Chunk merge: {len(reranked_chunks)} chunks → {len(merged_docs)} docs in {merge_time_ms:.0f}ms")

    total_time_ms = (time.perf_counter() - chunk_start) * 1000
    logger.info(
        f"Precision mode total: {total_time_ms:.0f}ms "
        f"(chunk={chunk_time_ms:.0f}ms, bm25={bm25_time_ms:.0f}ms, "
        f"rerank={rerank_time_ms:.0f}ms, merge={merge_time_ms:.0f}ms)"
    )

    return merged_docs
