"""Precision-mode search pipeline for the web search toolkit.

Chunk-level semantic filtering: smart chunking of long documents (concurrent),
BM25 coarse filtering, reranker fine ranking, then per-document chunk capping.
Pure functions over their arguments — they hold no toolkit state, so the engine
hands them the chunker, reranker, tools facade, and retriever manager explicitly.

[INPUT]
- toolkits.retriever.splitter::TextChunker (POS: Text chunking for retrieval)
- toolkits.web_search.engine::WebSearchTools (POS: WebSearchTools wrapper: parallel search + dedup + BM25/precision modes)

[OUTPUT]
- _precision_mode_search: run the precision-mode pipeline over unified documents
- _cap_chunks_per_doc: keep the top-N chunks per document
- _chunk_document_async: chunk a single long document off the event loop

[POS]
Precision-mode retrieval pipeline for the web search toolkit.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.splitter.splitter import TextChunker
from myrm_agent_harness.toolkits.web_search.core.metrics import web_search_metrics
from myrm_agent_harness.utils.text_utils import get_token_count

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.retriever.reranker import RerankerService
    from myrm_agent_harness.toolkits.retriever_tools import RetrieverManager
    from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools

logger = logging.getLogger(__name__)


def _cap_chunks_per_doc(
    chunks: list[Document],
    max_chunks_per_doc: int,
) -> list[Document]:
    """Select top relevance chunks per document URL and restore intra-document narrative order.

    Across documents: global ranking follows the highest-relevance chunk per URL.
    Within each document: retained chunks are sorted in ascending order of chunk_index
    to prevent temporal or causal inversions in the synthesized LLM prompt context.

    Args:
        chunks: Reranker-sorted chunk list (descending by relevance)
        max_chunks_per_doc: Max chunks to keep per document URL

    Returns:
        Filtered document list with at most max_chunks_per_doc chunks per URL,
        sorted by URL relevance descending and intra-URL chunk_index ascending.
    """
    if not chunks or max_chunks_per_doc <= 0:
        return chunks

    from collections import defaultdict

    url_to_chunks: dict[str, list[Document]] = defaultdict(list)
    url_order: list[str] = []

    for chunk in chunks:
        url = (chunk.metadata or {}).get("url", "unknown")
        if url not in url_to_chunks:
            url_order.append(url)
        if len(url_to_chunks[url]) < max_chunks_per_doc:
            url_to_chunks[url].append(chunk)

    selected: list[Document] = []
    for url in url_order:
        retained = url_to_chunks[url]
        retained.sort(key=lambda c: int((c.metadata or {}).get("chunk_index", 0)))
        selected.extend(retained)

    logger.info(
        f"Chunk capping: {len(chunks)} chunks → {len(selected)} chunks "
        f"(max {max_chunks_per_doc} per doc, restored intra-doc narrative order)"
    )
    return selected


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

    # 2. BM25 filter candidate mapping per query (prunes cross-product pairs)
    bm25_start = time.perf_counter()
    query_doc_mapping: dict[str, list[tuple[Document, float]]] | None = None
    if hasattr(retriever_manager, "bm25_retrieval_with_mapping"):
        try:
            res = retriever_manager.bm25_retrieval_with_mapping(
                queries=questions,
                documents=all_chunks,
                top_k_per_query=min(tools._BM25_TOP_K_CHUNKS, 20),
            )
            if asyncio.iscoroutine(res):
                res = await res
            if isinstance(res, dict):
                query_doc_mapping = res
        except Exception as e:
            logger.debug(f"bm25_retrieval_with_mapping failed, falling back: {e}")
            query_doc_mapping = None

    seen_ids: set[int] = set()
    bm25_filtered: list[Document] = []

    if query_doc_mapping is not None:
        for pairs in query_doc_mapping.values():
            if isinstance(pairs, list):
                for item in pairs:
                    if isinstance(item, tuple) and len(item) == 2:
                        doc = item[0]
                        if id(doc) not in seen_ids:
                            seen_ids.add(id(doc))
                            bm25_filtered.append(doc)

    if not bm25_filtered:
        # Fallback to bm25_retrieval_only if mapping unavailable or returned 0 hits
        bm25_filtered = await retriever_manager.bm25_retrieval_only(
            queries=questions, documents=all_chunks, top_k=tools._BM25_TOP_K_CHUNKS
        )
        if not bm25_filtered and all_chunks:
            bm25_filtered = all_chunks[: tools._BM25_TOP_K_CHUNKS]
        query_doc_mapping = {q: [(doc, 1.0) for doc in bm25_filtered] for q in questions}

    bm25_time_ms = (time.perf_counter() - bm25_start) * 1000
    total_pairs = sum(len(v) for v in query_doc_mapping.values()) if query_doc_mapping else 0
    logger.info(
        f"BM25 mapping: {len(all_chunks)} chunks → {len(bm25_filtered)} unique docs, "
        f"{total_pairs} rerank pairs across {len(questions)} queries in {bm25_time_ms:.0f}ms"
    )

    # 3. Reranker rerank top-20 chunks, auto-degrade to BM25 on failure
    rerank_start = time.perf_counter()
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
