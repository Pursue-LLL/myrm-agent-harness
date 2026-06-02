"""Search results processor.

Converts raw SearchResult objects into deduplicated, cleaned LangChain Documents
with normalised URLs and content-hash-based deduplication.

[INPUT]
web_search.common::SearchResult (POS: Unified search result dataclass)
web_search.exceptions::ErrorContext, SearchAPIError (POS: Search exception types)
utils.document_utils::enhance_document_content (POS: Document content enhancement)
utils.hash_utils::get_content_hash (POS: Content hashing for deduplication)
utils.text_cleaner::clean_search_snippet (POS: Search snippet cleaning)
utils.url_utils::normalize_url (POS: URL normalisation)

[OUTPUT]
search_results_to_documents: Converts SearchResult list to deduplicated Document list
process_search_response: Parses raw API responses into SearchResult objects

[POS]
Search result post-processor. Sits between raw search API responses and the consumer
layer, handling cleaning, deduplication, and Document construction.

"""

import logging

from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.exceptions import ErrorContext, SearchAPIError
from myrm_agent_harness.utils.document_utils import enhance_document_content
from myrm_agent_harness.utils.hash_utils import get_content_hash
from myrm_agent_harness.utils.text_cleaner import clean_search_snippet
from myrm_agent_harness.utils.url_utils import normalize_url

logger = logging.getLogger(__name__)


def search_results_to_documents(results: list[SearchResult]) -> list[Document]:
    """将SearchResultConvert is DocumentObject

    Args:
        results: SearchResultList

    Returns:
        DocumentList
    """
    documents = []

    for result in results:
        # 对snippetPerform基本Clean up
        cleaned_snippet = clean_search_snippet(result.snippet)

        # Set元Data
        metadata: dict[str, object] = {
            "title": result.title,
            "url": result.url,
            "description": cleaned_snippet[:100],  #  using Clean up后 Content作 is Description
        }

        # Include citations in metadata when present
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
    """Merge多QuerySearchResult并做Global去重。

    行 is Description：
    - 单次遍历input： in 同一循环内CompleteFailure/EmptyResultStatistics、去重 and 目标ListBuild。
    - 去重Key：规范化 URL（去 fragment） and 正文前 500 Characters 哈希（更长正文则Truncate后哈希）。
    -  via Query 文档 in 进入去重分支前累计 ``total_docs``， no 额外全量预扫描。

    Args:
        search_results: originalSearchResultList [(Query, 文档List, 可能 Exception), ...]

    Returns:
        (GlobalURL元DataList, Global去重后 文档List)
    """
    if not search_results:
        return [], []

    # 统一文档池，Global去重（ using  URL+Content哈希 作 is 去重Key）
    seen_keys = set()  # Storage (normalized_url_dedup, content_hash) 元组
    unified_docs = []
    url_metadata_list = []
    total_docs = 0
    failed_queries = 0
    zero_result_queries = 0  # 没 has ReturnResult Query数

    for query, documents, error in search_results:
        # SkipFailure Query（Exception）
        if error is not None:
            failed_queries += 1
            logger.warning(f"Query '{query}' Failure: {error}")
            continue

        # Statistics文档数
        doc_count = len(documents)
        total_docs += doc_count

        # ProcessReturn0Result Query
        if doc_count == 0:
            zero_result_queries += 1
            continue

        # 只Record has Result Query
        logger.warning(f"Query '{query}' Return了 {doc_count} 个文档")

        # Process文档
        for doc in documents:
            metadata = doc.metadata
            original_url = metadata.get("url", "")
            if not original_url:
                logger.warning(f"Query '{query}'  某个文档缺少URL， already Skip")
                continue

            page_content = doc.page_content

            normalized_url_dedup, normalized_url_semantic = normalize_url(original_url)
            if not normalized_url_dedup:
                logger.warning(f"Query '{query}'  URLstandard化Failure: {original_url}")
                continue

            content_len = len(page_content)
            content_prefix = page_content if content_len <= 500 else page_content[:500]
            content_hash = get_content_hash(content_prefix, strategy="builtin", use_cache=True)

            dedup_key = (normalized_url_dedup, content_hash)
            if dedup_key in seen_keys:
                continue

            seen_keys.add(dedup_key)

            doc.metadata["url"] = normalized_url_semantic

            enhanced_content = enhance_document_content(doc)

            new_metadata = {
                "title": metadata.get("title", ""),
                "url": normalized_url_semantic,
                "description": metadata.get("description", ""),
            }

            unified_docs.append(Document(page_content=enhanced_content, metadata=new_metadata))

            url_metadata_list.append({"url": normalized_url_semantic, "title": new_metadata["title"]})

    total_queries = len(search_results)
    successful_queries = total_queries - failed_queries - zero_result_queries

    if total_docs == 0:
        logger.warning(
            f"统一文档池: original0个文档 "
            f"(总Query{total_queries}: {successful_queries}个 has Result, {zero_result_queries}个 no Result, {failed_queries}个Failure)"
        )
        logger.warning("Search failed: All queries returned 0 results")
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

    logger.warning(
        f"统一文档池: original{total_docs}个文档 -> 去重后{len(unified_docs)}个文档 "
        f"(总Query{total_queries}: {successful_queries}个 has Result, {zero_result_queries}个 no Result, {failed_queries}个Failure)"
    )

    return url_metadata_list, unified_docs
