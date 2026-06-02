"""Document chunk filter

Provides BM25-based chunk pre-filtering for long document relevance filtering。

[INPUT]
- toolkits.retriever.bm25_retrieval::BM25Retriever (POS: BM25 sparse retrieval engine. Builds an in-memory inverted index from document chunks and returns keyword-matched results ranked by BM25 score.)
- toolkits.retriever.splitter::TextChunker (POS: Smart long-message splitter. Line-by-line processing with fence state machine, auto-closing and reopening code blocks that span chunks. "escape" fence protection 2. Enhanced: Supports both ``` and ~~~ fences (3-10 symbols) 3. Smart: Intelligent line splitting at whitespace/punctuation boundaries 4. Configurable: Overflow tolerance for semantic preservation)

[OUTPUT]
- ChunkFilter: Document chunk filter
- create_document_chunks_from_crawl_results: Create document chunks from crawl results, BM25 pre-filte...

[POS]
Document chunk filter
"""

import asyncio
import logging

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.retriever.bm25_retrieval import BM25Retriever
from myrm_agent_harness.toolkits.retriever.fusion_strategies import rrf_fusion
from myrm_agent_harness.toolkits.retriever.splitter import TextChunker
from myrm_agent_harness.utils.text_utils import detect_language

logger = logging.getLogger(__name__)


class ChunkFilter:
    """Document chunk filter

    Uses BM25 + RRF for relevance pre-filtering of long document chunks, reducing irrelevant content。

    Features:
    - Auto-identifies long documents (> 20000 chars)
    - Uses BM25 for chunk relevance scoring
    - Uses RRF to fuse multi-query results
    - Guarantees minimum and maximum retained chunk count
    """

    def __init__(
        self,
        long_doc_threshold: int = 20000,
        bm25_topk_ratio: int = 7,
        max_retained_chunks: int = 30,
        min_retained_chunks: int = 5,
    ):
        """Initialize chunk filter

        Args:
            long_doc_threshold: Long doc threshold (chars), triggers BM25 pre-filtering
            bm25_topk_ratio: BM25 filtering ratio, retains len(chunks) // bm25_topk_ratio chunks
            max_retained_chunks: Maximum retained chunk count
            min_retained_chunks: Minimum retained chunk count
        """
        self.long_doc_threshold = long_doc_threshold
        self.bm25_topk_ratio = bm25_topk_ratio
        self.max_retained_chunks = max_retained_chunks
        self.min_retained_chunks = min_retained_chunks
        self.text_chunker = TextChunker()

    async def filter_chunks_by_relevance(
        self,
        url: str,
        document: Document,
        queries: list[str],
    ) -> list[Document]:
        """Filter relevant chunks using BM25 + RRF

        Args:
            url: Document source URL
            document: Original document
            queries: Query list

        Returns:
            FilteredDocument chunk list
        """
        if not document or not document.page_content:
            logger.warning(f"URL {url} content is empty")
            return []

        # Get original metadata
        metadata = document.metadata
        original_length = len(document.page_content)

        # Chunk webpage content - pass document metadata for context injection
        chunks = self.text_chunker.chunk_text(
            document.page_content,
            document_metadata=metadata,
        )

        if not chunks:
            return []

        # Determine if BM25 pre-filtering is needed
        if original_length <= self.long_doc_threshold or not queries:
            # Short documents return all chunks directly
            return chunks

        logger.warning(
            f"URL {url} original length {original_length} > {self.long_doc_threshold}，Applying to {len(chunks)} chunks for BM25 pre-filtering"
        )

        # Extract chunk text content
        chunk_texts = [chunk.page_content for chunk in chunks]

        #  Unified BM25Retriever (build index once, reuse for multiple queries)
        retriever = await asyncio.to_thread(BM25Retriever, chunk_texts)

        # BM25 retrieval for all queries, RRF fusion of multi-query results
        query_rankings: list[list[tuple[int, float]]] = []
        bm25_topk = min(
            max(len(chunks) // self.bm25_topk_ratio, self.min_retained_chunks),
            self.max_retained_chunks,
        )

        for query in queries:
            bm25_results = retriever.search(query, top_k=bm25_topk, only_relevant=True)
            query_rankings.append(bm25_results)

        # Fuse multi-query rankings using RRF
        sorted_indices = rrf_fusion(query_rankings, k=60, top_k=self.max_retained_chunks)
        filtered_chunks = [chunks[idx] for idx, _ in sorted_indices if idx < len(chunks)]

        # BM25 Zero recall + cross-language -> skip filtering, retain all chunks
        if not filtered_chunks:
            query_lang = detect_language(" ".join(queries))
            doc_lang = detect_language(" ".join(chunk_texts[:3]))
            if query_lang != doc_lang and "mixed" not in (query_lang, doc_lang):
                logger.warning(
                    f"URL {url} BM25 cross-language skip: query={query_lang}, doc={doc_lang}, "
                    f"returning all {len(chunks)} chunks"
                )
                return chunks

        # Output RRF fusion results
        self._log_filtering_results(url, chunks, sorted_indices, query_rankings, queries)

        logger.warning(
            f"URL {url} BM25 pre-filtering done: {len(chunks)} chunks -> {len(filtered_chunks)} relevant chunks "
            f"(retention rate: {len(filtered_chunks) / len(chunks):.1%})"
        )

        return filtered_chunks

    def _log_filtering_results(
        self,
        url: str,
        chunks: list[Document],
        sorted_indices: list,
        query_rankings: list,
        queries: list[str],
    ):
        """Log filtering results"""
        logger.warning(f"\n{'=' * 100}")
        logger.warning(f"URL {url} - RRF fusion results (top {min(20, len(sorted_indices))} )")
        logger.warning(f"{'=' * 100}")
        logger.warning(f"{'Rank':<6} {'RRF Score':<12} {'Occurrences':<10} {'Doc Content'}")
        logger.warning(f"{'-' * 100}")

        for rank, (idx, rrf_score) in enumerate(sorted_indices[:20], 1):
            # Count queries in which this chunk appears
            appear_count = sum(1 for ranked_list in query_rankings if idx in [i for i, _ in ranked_list])
            content = chunks[idx].page_content[:800].replace("\n", " ")
            logger.warning(f"{rank:<6} {rrf_score:<12.6f} {appear_count}/{len(queries):<8} {content}...")

        logger.warning(f"{'=' * 100}\n")


# Global chunk filter instance
_chunk_filter = ChunkFilter()


async def create_document_chunks_from_crawl_results(
    success_results,
    queries: list[str] | None = None,
    long_doc_threshold: int = 20000,
    bm25_topk_ratio: int = 7,
    max_retained_chunks: int = 30,
    min_retained_chunks: int = 5,
) -> list[Document]:
    """Create document chunks from crawl results, BM25 pre-filter long documents

    Actually delegates to ChunkFilter。

    Args:
        success_results: Successfully crawled URL and document results
        queries: Query list, for BM25 pre-filtering
        long_doc_threshold: Long doc threshold (chars), triggers BM25 pre-filtering
        bm25_topk_ratio: BM25 filtering ratio, retains len(chunks) // bm25_topk_ratio chunks
        max_retained_chunks: Maximum retained chunk count，Avoid excessive irrelevant chunks from long documents
        min_retained_chunks: Minimum retained chunk count，Ensure each document has minimum info

    Returns:
        Document chunk list
    """
    # Create temp filter (if params differ from defaults)
    if long_doc_threshold != 20000 or bm25_topk_ratio != 7 or max_retained_chunks != 30 or min_retained_chunks != 5:
        chunk_filter = ChunkFilter(
            long_doc_threshold=long_doc_threshold,
            bm25_topk_ratio=bm25_topk_ratio,
            max_retained_chunks=max_retained_chunks,
            min_retained_chunks=min_retained_chunks,
        )
    else:
        chunk_filter = _chunk_filter

    all_chunk_documents = []

    for url, document in success_results:
        filtered_chunks = await chunk_filter.filter_chunks_by_relevance(url, document, queries or [])
        all_chunk_documents.extend(filtered_chunks)

    return all_chunk_documents
