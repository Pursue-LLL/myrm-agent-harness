"""Search results processor.

Converts raw SearchResult objects into deduplicated, cleaned LangChain Documents
with normalised URLs and content-hash-based deduplication.

[INPUT]
web_search.common::SearchResult (POS: Unified search result dataclass)
web_search.exceptions::ErrorContext, SearchAPIError (POS: Search exception types)
utils.document_utils::enhance_document_content (POS: Document content enhancement)
utils.hash_utils::get_content_hash (POS: Content hashing for deduplication)
utils.text_cleaner::clean_search_snippet (POS: Search snippet cleaning)
utils.url_utils::normalize_url, extract_domain (POS: URL normalisation and domain extraction)

[OUTPUT]
search_results_to_documents: Converts SearchResult list to Document list
combine_search_results_unified: Merges multi-query results with two-layer deduplication (URL arbitration + content hash)
apply_domain_diversity_sort: Reorders documents with same-domain decay to improve source diversity

[POS]
Search result post-processor. Sits between raw search API responses and the consumer
layer, handling cleaning, deduplication, domain diversity sorting, and Document construction.

"""

import logging
from collections import Counter

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.exceptions import ErrorContext, SearchAPIError
from myrm_agent_harness.utils.document_utils import enhance_document_content
from myrm_agent_harness.utils.hash_utils import get_content_hash
from myrm_agent_harness.utils.text_cleaner import clean_search_snippet
from myrm_agent_harness.utils.url_utils import extract_domain, normalize_url

logger = logging.getLogger(__name__)


def search_results_to_documents(results: list[SearchResult]) -> list[Document]:
    """Convert SearchResult objects into LangChain Document objects.

    Args:
        results: List of SearchResult from search providers.

    Returns:
        List of Document with cleaned snippet as page_content.
    """
    documents = []

    for result in results:
        cleaned_snippet = clean_search_snippet(result.snippet)

        metadata: dict[str, object] = {
            "title": result.title,
            "url": result.url,
            "description": cleaned_snippet,
        }

        if result.date:
            metadata["date"] = result.date
        if result.engines:
            metadata["engines"] = result.engines

        if result.citations:
            metadata["citations"] = [
                {
                    "url": c.url,
                    "title": c.title,
                    "start_index": c.start_index,
                    "end_index": c.end_index,
                }
                for c in result.citations
            ]

        doc = Document(page_content=cleaned_snippet, metadata=metadata)
        documents.append(doc)

    return documents


def combine_search_results_unified(
    search_results: list[tuple[str, list[Document], Exception | None]],
) -> tuple[list[dict[str, str]], list[Document]]:
    """Merge multi-query search results with two-layer deduplication.

    Deduplication strategy:
    - Layer 1 (URL arbitration): Same normalized URL keeps only the version with
      the longest page_content (information density proxy).
    - Layer 2 (Content hash): Different URLs with identical content_hash (mirror sites)
      keep only the first encountered.

    Args:
        search_results: Raw search results [(query, documents, optional exception), ...]

    Returns:
        (url_metadata_list, deduplicated_documents)
    """
    if not search_results:
        return [], []

    # Layer 1: URL → best candidate (longest content wins)
    url_best: dict[str, tuple[int, Document, str]] = {}  # url → (content_len, doc, semantic_url)
    # Layer 2: content_hash → first seen URL (for mirror site dedup)
    content_hash_seen: dict[str, str] = {}  # hash → normalized_url

    total_docs = 0
    failed_queries = 0
    zero_result_queries = 0

    for query, documents, error in search_results:
        if error is not None:
            failed_queries += 1
            logger.debug(f"Query '{query}' failed: {error}")
            continue

        doc_count = len(documents)
        total_docs += doc_count

        if doc_count == 0:
            zero_result_queries += 1
            continue

        logger.debug(f"Query '{query}' returned {doc_count} documents")

        for doc in documents:
            metadata = doc.metadata
            original_url = metadata.get("url", "")
            if not original_url:
                continue

            page_content = doc.page_content

            normalized_url_dedup, normalized_url_semantic = normalize_url(original_url)
            if not normalized_url_dedup:
                continue

            content_len = len(page_content)
            content_prefix = page_content if content_len <= 500 else page_content[:500]
            content_hash = get_content_hash(content_prefix, strategy="builtin", use_cache=True)

            # Layer 2: mirror site dedup (different URL, same content)
            existing_url = content_hash_seen.get(content_hash)
            if existing_url is not None and existing_url != normalized_url_dedup:
                continue
            content_hash_seen.setdefault(content_hash, normalized_url_dedup)

            # Layer 1: URL arbitration (same URL, keep longest content)
            prev = url_best.get(normalized_url_dedup)
            if prev is not None:
                if content_len <= prev[0]:
                    continue
            url_best[normalized_url_dedup] = (content_len, doc, normalized_url_semantic)

    total_queries = len(search_results)
    successful_queries = total_queries - failed_queries - zero_result_queries

    if total_docs == 0:
        logger.debug(
            f"Document pool: 0 docs "
            f"(queries={total_queries}: success={successful_queries}, empty={zero_result_queries}, failed={failed_queries})"
        )
        raise SearchAPIError(
            "Search API is unavailable: all queries returned 0 results",
            context=ErrorContext(
                metadata={
                    "total_queries": str(total_queries),
                    "successful_queries": str(successful_queries),
                    "zero_result_queries": str(zero_result_queries),
                    "failed_queries": str(failed_queries),
                },
            ),
        )

    # Build final document list preserving insertion order
    unified_docs: list[Document] = []
    url_metadata_list: list[dict[str, str]] = []

    for _content_len, doc, semantic_url in url_best.values():
        doc.metadata["url"] = semantic_url
        enhanced_content = enhance_document_content(doc)

        new_metadata = {
            "title": doc.metadata.get("title", ""),
            "url": semantic_url,
            "description": doc.metadata.get("description", ""),
        }

        unified_docs.append(Document(page_content=enhanced_content, metadata=new_metadata))
        url_metadata_list.append({"url": semantic_url, "title": new_metadata["title"]})

    logger.debug(
        f"Document pool: {total_docs} raw -> {len(unified_docs)} deduplicated "
        f"(queries={total_queries}: success={successful_queries}, empty={zero_result_queries}, failed={failed_queries})"
    )

    return url_metadata_list, unified_docs


def apply_domain_diversity_sort(
    docs: list[Document],
    decay_factor: float = 0.8,
) -> list[Document]:
    """Reorder documents with same-domain decay to improve source diversity.

    Algorithm: For each document, compute decay_score = base_score × decay_factor^(n-1),
    where base_score = 1/(rank+1) preserves original search ranking weight, and n is the
    number of times that domain has appeared. Final ordering is by decay_score descending.

    Args:
        docs: Deduplicated document list (preserving original search order).
        decay_factor: Same-domain decay coefficient. 0.8 means the 2nd doc from the
                      same domain gets ×0.8, 3rd ×0.64, 4th ×0.512, rapidly deprioritized.

    Returns:
        Documents reordered by decay_score descending.
    """
    if len(docs) <= 1:
        return docs

    domain_counter: Counter[str] = Counter()
    scored: list[tuple[float, int, Document]] = []

    for rank, doc in enumerate(docs):
        url = doc.metadata.get("url", "")
        domain = extract_domain(url) if url else ""

        domain_counter[domain] += 1
        n = domain_counter[domain]

        base_score = 1.0 / (rank + 1)
        decay_score = base_score * (decay_factor ** (n - 1))

        scored.append((decay_score, rank, doc))

    scored.sort(key=lambda x: (-x[0], x[1]))

    top_domain = domain_counter.most_common(1)
    if top_domain and top_domain[0][1] > 1:
        logger.info(
            f"Domain diversity: {len(docs)} docs, "
            f"top_domain={top_domain[0][0]}({top_domain[0][1]}), "
            f"unique_domains={len(domain_counter)}"
        )

    return [doc for _, _, doc in scored]
