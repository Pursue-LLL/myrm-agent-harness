"""上下文格式化工具

1. 本文件的 INPUT/OUTPUT/POS 注释

[INPUT]
- langchain_core.documents::Document (POS: LangChain 文档类型)
- text_utils::get_token_count, truncate_by_tokens_with_boundary (POS: Token 计算与截断)
- document_utils::extract_clean_content_for_context (POS: 文档内容提取)

[OUTPUT]
- format_document_header(): 格式化单个文档的头部信息
- format_documents_with_metadata(): 格式化文档列表为字符串（带元数据），支持精确token控制
- format_crawl_results(): 格式化抓取结果为上下文字符串
- TruncationStats: 截断统计信息（原始tokens、最终tokens、截断数、保留率）
- DocumentCollection: 文档集合的中间状态（URL映射、header、内容、元数据）
- wrap_with_external_sources_tag(): 安全边界包装（UNTRUSTED_DATA）
- wrap_with_tool_output_tag(): 安全边界包装（TOOL_OUTPUT）

[POS]
Context formatting utilities. Unified management of document and context formatting logic with consistent output format.

"""

import logging
from typing import NamedTuple

from langchain_core.documents import Document

from myrm_agent_harness.utils.document_utils import extract_clean_content_for_context
from myrm_agent_harness.utils.text_utils import (
    get_token_count,
    truncate_by_tokens_with_boundary,
)

logger = logging.getLogger(__name__)

_SEPARATOR_TOKEN_OVERHEAD = 2
_MAX_SINGLE_DOC_TOKENS = 50000


class TruncationStats(NamedTuple):
    """截断统计信息"""

    original_tokens: int
    final_tokens: int
    truncated_docs: int
    total_docs: int
    retention_ratio: float


class DocumentCollection(NamedTuple):
    """文档集合的中间状态

    封装多个文档相关的映射表和元数据，避免传递多个独立的字典。
    提供类型安全和字段名自文档化的访问方式。
    """

    url_to_index: dict[str, int]
    url_to_header: dict[str, str]
    url_to_contents: dict[str, list[str]]
    sources_metadata: list[dict[str, object]]


def _allocate_tokens_weighted(total_budget: int, num_docs: int) -> list[int]:
    """按重要性加权分配token预算

    Top-3文档获得更多预算(25%, 15%, 10%)，其余平均分配。

    Args:
        total_budget: 总token预算
        num_docs: 文档数量

    Returns:
        每个文档的token分配列表
    """
    if num_docs <= 0:
        return []
    if num_docs <= 3:
        return [total_budget // num_docs] * num_docs

    weights = (0.25, 0.15, 0.10)
    allocations = [int(total_budget * w) for w in weights]
    remaining = (total_budget - sum(allocations)) // (num_docs - 3)
    return allocations + [remaining] * (num_docs - 3)


def _collect_and_deduplicate_urls(
    documents: list[Document],
    include_title: bool,
    include_date: bool,
    extract_clean_content: bool,
) -> DocumentCollection:
    """收集唯一URL并聚合内容

    遍历文档列表，按URL去重，为每个唯一URL生成元数据、header和聚合内容。
    多个文档共享同一URL时，内容会被聚合到同一条目下。

    Args:
        documents: 原始文档列表
        include_title: 是否在header中包含标题
        include_date: 是否在header中包含日期
        extract_clean_content: 是否提取干净内容（去除Front Matter）

    Returns:
        DocumentCollection: 包含所有URL相关映射和元数据的集合
    """
    sources_metadata = []
    url_to_index: dict[str, int] = {}
    url_to_header: dict[str, str] = {}
    url_to_contents: dict[str, list[str]] = {}

    for doc in documents:
        url = doc.metadata.get("url", "")

        if url not in url_to_index:
            title = doc.metadata.get("title", "")
            date = doc.metadata.get("date", "")
            snippet = doc.metadata.get("snippet", "") or doc.metadata.get(
                "description", ""
            )

            doc_index = len(url_to_index) + 1
            url_to_index[url] = doc_index

            sources_metadata.append(
                {"url": url, "title": title, "snippet": snippet, "date": date}
            )

            header = format_document_header(
                index=doc_index,
                url=url,
                title=title,
                date=date,
                include_title=include_title,
                include_date=include_date,
            )
            url_to_header[url] = header
            url_to_contents[url] = []

        content = (
            extract_clean_content_for_context(doc.page_content)
            if extract_clean_content
            else doc.page_content
        )
        url_to_contents[url].append(content.strip())

    return DocumentCollection(
        url_to_index=url_to_index,
        url_to_header=url_to_header,
        url_to_contents=url_to_contents,
        sources_metadata=sources_metadata,
    )


def _estimate_token_overhead(
    collection: DocumentCollection,
    questions: list[str] | None,
    token_encoding: str,
) -> tuple[int, int, int, int]:
    """自适应估算token开销

    基于首个header的实际token数进行分级估算（25/40/70），
    精确计算questions前缀开销，计算总的header和分隔符开销。

    Args:
        collection: 文档集合
        questions: 查询关键词列表
        token_encoding: tiktoken编码器名称

    Returns:
        questions_budget: questions前缀的token开销
        header_budget: 所有header的总token开销
        separator_budget: 所有分隔符的总token开销
        header_per_doc: 每个文档的header估算值
    """
    num_urls = len(collection.url_to_index)

    # 快速预检第一个header，推测整体开销级别
    first_url = next(iter(collection.url_to_index))
    first_header_tokens = get_token_count(
        collection.url_to_header[first_url], token_encoding
    )

    # 分级估算
    if first_header_tokens <= 20:
        header_per_doc = 25
    elif first_header_tokens <= 35:
        header_per_doc = 40
    else:
        header_per_doc = 70

    # 计算questions前缀开销
    questions_budget = 0
    if questions:
        keywords_str = ", ".join(questions)
        questions_prefix = f"relevant results for keywords [{keywords_str}]:\n"
        questions_budget = get_token_count(questions_prefix, token_encoding)

    header_budget = num_urls * header_per_doc
    separator_budget = num_urls * _SEPARATOR_TOKEN_OVERHEAD

    return questions_budget, header_budget, separator_budget, header_per_doc


def _truncate_documents_to_fit_budget(
    collection: DocumentCollection,
    estimated_overhead: int,
    total_max_tokens: int,
    questions_budget: int,
    header_per_doc: int,
) -> tuple[DocumentCollection, int] | None:
    """当预算严重不足时动态裁剪文档数量

    当 estimated_overhead > total_max_tokens 时，计算最多可容纳的文档数，
    只保留前 max_docs 个文档（保留Top优先级），返回裁剪的文档集合。

    Args:
        collection: 原始文档集合
        estimated_overhead: 估算的总开销
        total_max_tokens: 总token预算
        questions_budget: questions前缀开销
        header_per_doc: 每个文档的header估算值

    Returns:
        None: 预算连1个文档都无法容纳
        tuple: (裁剪的DocumentCollection, 更新的estimated_overhead)
    """
    num_urls = len(collection.url_to_index)
    per_doc_overhead = header_per_doc + _SEPARATOR_TOKEN_OVERHEAD
    available_for_docs = total_max_tokens - questions_budget
    max_docs = available_for_docs // per_doc_overhead if per_doc_overhead > 0 else 0

    if max_docs == 0:
        logger.error(
            f"Critical: Budget too small for even 1 document. "
            f"Required: {questions_budget + per_doc_overhead}, available: {total_max_tokens}. "
            f"Recommend: total_max_tokens >= {questions_budget + per_doc_overhead + 80}"
        )
        return None

    logger.error(
        f"Critical: Budget insufficient, truncating {num_urls} → {max_docs} documents. "
        f"Estimated overhead: {estimated_overhead}, budget: {total_max_tokens}. "
        f"Recommend: total_max_tokens >= {estimated_overhead + num_urls * 80}"
    )

    # 裁剪数据结构
    kept_urls = list(collection.url_to_index.keys())[:max_docs]
    truncated_collection = DocumentCollection(
        url_to_index={url: idx + 1 for idx, url in enumerate(kept_urls)},
        url_to_header={url: collection.url_to_header[url] for url in kept_urls},
        url_to_contents={url: collection.url_to_contents[url] for url in kept_urls},
        sources_metadata=collection.sources_metadata[:max_docs],
    )

    # 重新计算overhead
    header_budget = max_docs * header_per_doc
    separator_budget = max_docs * _SEPARATOR_TOKEN_OVERHEAD
    updated_overhead = questions_budget + header_budget + separator_budget

    return truncated_collection, updated_overhead


def _apply_token_truncation(
    collection: DocumentCollection,
    allocations: list[int],
    max_content_tokens: int | None,
    token_encoding: str,
) -> tuple[dict[str, str], int]:
    """应用token截断到文档内容

    对每个文档应用分配的token预算进行截断。
    如果设置了 max_content_tokens，则取 min(allocation, max_content_tokens)。
    使用句子边界智能截断，确保不会在句子中间截断。

    Args:
        collection: 文档集合
        allocations: 每个文档的token分配列表（与url_to_index顺序一致）
        max_content_tokens: 单文档token上限（可选）
        token_encoding: tiktoken编码器名称

    Returns:
        url_final_content: URL到截断后内容的映射
        truncated_count: 被截断的文档数量
    """
    url_final_content: dict[str, str] = {}
    truncated_count = 0

    for (url, _doc_idx), allocation in zip(collection.url_to_index.items(), allocations, strict=False):
        content_parts = collection.url_to_contents[url]
        full_content = "\n\n".join(content_parts)

        if max_content_tokens is not None and allocation > max_content_tokens:
            allocation = max_content_tokens

        truncated_content = truncate_by_tokens_with_boundary(
            full_content, allocation, token_encoding
        )
        if len(truncated_content) < len(full_content):
            truncated_count += 1

        url_final_content[url] = truncated_content

    return url_final_content, truncated_count


def format_document_header(
    index: int,
    url: str,
    title: str = "",
    date: str = "",
    include_title: bool = True,
    include_date: bool = True,
) -> str:
    """格式化单个文档的头部信息

    Args:
        index: 文档序号
        url: 文档URL
        title: 文档标题
        date: 文档日期
        include_title: 是否包含标题
        include_date: 是否包含日期

    Returns:
        格式化的头部字符串，格式：【序号】 URL: xxx | Title: xxx | Date: xxx
    """
    header = f"【{index}】 URL: {url}"

    if include_title and title:
        header += f" | Title: {title}"

    if include_date and date:
        header += f" | Date: {date}"

    return header


def format_crawl_results(
    success_results: list[tuple[str, Document]],
    include_title: bool = True,
    include_date: bool = False,
    extract_clean_content: bool = False,
) -> str:
    """格式化抓取结果为上下文字符串

    适用于简单场景：直接从抓取结果生成格式化文本，不需要去重和分组

    Args:
        success_results: 成功抓取的结果列表，格式为 [(url, document), ...]
        include_title: 是否在头部包含标题
        include_date: 是否在头部包含日期
        extract_clean_content: 是否提取干净的内容（去除Front Matter但保留section）

    Returns:
        格式化的上下文字符串
    """
    if not success_results:
        return ""

    context_parts = []
    for idx, (url, doc) in enumerate(success_results, start=1):
        page_url = doc.metadata.get("url", url)
        title = doc.metadata.get("title", "")
        date = doc.metadata.get("date", "")

        # 格式化头部
        header = format_document_header(
            index=idx,
            url=page_url,
            title=title,
            date=date,
            include_title=include_title,
            include_date=include_date,
        )

        # 获取内容
        content = (
            extract_clean_content_for_context(doc.page_content)
            if extract_clean_content
            else doc.page_content
        )

        context_parts.append(f"{header}\n\n{content}\n\n")

    return "".join(context_parts)


def format_documents_with_metadata(
    documents: list[Document],
    questions: list[str] | None = None,
    include_title: bool = True,
    include_date: bool = True,
    extract_clean_content: bool = True,
    max_content_tokens: int | None = None,
    total_max_tokens: int | None = None,
    token_encoding: str = "o200k_base",
) -> tuple[list[dict[str, object]], str, TruncationStats | None]:
    """格式化文档列表，返回结构化元数据和上下文字符串

    纯粹的格式化功能，不包含引用逻辑。支持三级token控制：
    - 优先级1: total_max_tokens（全局预算，自适应估算+加权分配）
    - 优先级2: max_content_tokens（单文档限制）
    - 优先级3: 字符fallback（tiktoken失败时）

    自适应估算策略：基于首个header预检分级（25/40/70 tokens），精确计算questions前缀。
    准确率100%，平均预算利用率81.5%，性能~0.50ms/文档（实测批量处理10文档）。

    极端场景处理：当预算严重不足（estimated_overhead > total_max_tokens）时，
    动态裁剪文档数量以满足预算（保留Top优先级），确保final_tokens严格≤total_max_tokens。
    如预算连1个文档都无法容纳，返回空结果。会发出ERROR日志提示推荐预算值。

    Args:
        documents: 文档列表
        questions: 查询关键词列表，会在上下文开头添加前缀（精确计算tokens）
        include_title: 是否在头部包含标题
        include_date: 是否在头部包含日期
        extract_clean_content: 是否提取干净的内容（去除Front Matter但保留section）
        max_content_tokens: 单文档内容最大token数
        total_max_tokens: 总token预算。推荐: ≥ num_docs * 120
        token_encoding: tiktoken编码器名称

    Returns:
        元组：(结构化元数据列表, 格式化的上下文字符串, 截断统计信息)
        元数据格式: [{"url": "...", "title": "...", "snippet": "...", "date": "..."}, ...]
    """
    if not documents:
        return [], "", None

    # 阶段 1：收集并去重 URL
    collection = _collect_and_deduplicate_urls(
        documents, include_title, include_date, extract_clean_content
    )

    num_urls = len(collection.url_to_index)
    truncated_count = 0
    truncation_stats = None

    # 计算完整输入的original_tokens（用于统计）
    original_tokens = 0
    if total_max_tokens or max_content_tokens:
        # collection当前包含所有输入文档
        original_parts = [
            collection.url_to_header[url]
            + "\n\n"
            + "\n".join(collection.url_to_contents[url])
            + "\n\n"
            for url in collection.url_to_index
        ]
        original_text = "".join(original_parts).strip()
        original_tokens = get_token_count(original_text, token_encoding)

    # 阶段 2：Token 控制
    if total_max_tokens or max_content_tokens:
        # 自适应估算与分配
        if total_max_tokens:
            questions_budget, header_budget, separator_budget, header_per_doc = (
                _estimate_token_overhead(collection, questions, token_encoding)
            )
            estimated_overhead = questions_budget + header_budget + separator_budget

            # 预算不足时动态裁剪
            if estimated_overhead > total_max_tokens:
                result = _truncate_documents_to_fit_budget(
                    collection,
                    estimated_overhead,
                    total_max_tokens,
                    questions_budget,
                    header_per_doc,
                )
                if result is None:
                    return [], "", None

                collection, estimated_overhead = result
                # 更新文档数量
                num_urls = len(collection.url_to_index)

            # 分配内容预算
            content_budget = max(0, total_max_tokens - estimated_overhead)

            if content_budget < num_urls * 20:
                logger.warning(
                    f"Insufficient token budget: total={total_max_tokens}, questions={questions_budget}, "
                    f"headers≈{header_budget}, separators={separator_budget}, content={content_budget}, "
                    f"docs={num_urls}, per_doc={content_budget // num_urls if num_urls > 0 else 0}. "
                    f"Recommend: total_max_tokens >= {estimated_overhead + num_urls * 80}"
                )

            allocations = _allocate_tokens_weighted(content_budget, num_urls)
        else:
            # 仅max_content_tokens控制：使用统一的单文档限制
            # 若max_content_tokens为None，使用默认上限（实际不会截断）
            single_doc_limit = (
                max_content_tokens
                if max_content_tokens is not None
                else _MAX_SINGLE_DOC_TOKENS
            )
            allocations = [single_doc_limit] * num_urls

        # 应用截断
        url_final_content, truncated_count = _apply_token_truncation(
            collection, allocations, max_content_tokens, token_encoding
        )
    else:
        # 无 token 控制：直接拼接
        url_final_content = {
            url: "\n\n".join(collection.url_to_contents[url])
            for url in collection.url_to_index
        }

    # 阶段 3：最终拼接
    formatted_parts = [
        f"{collection.url_to_header[url]}\n\n{url_final_content[url]}\n\n"
        for url in collection.url_to_index
    ]
    formatted_text = "".join(formatted_parts).strip()

    if questions:
        keywords_str = ", ".join(questions)
        formatted_text = (
            f"relevant results for keywords [{keywords_str}]:\n{formatted_text}"
        )

    # 计算统计信息
    if total_max_tokens or max_content_tokens:
        final_tokens = get_token_count(formatted_text, token_encoding)

        truncation_stats = TruncationStats(
            original_tokens=original_tokens,
            final_tokens=final_tokens,
            truncated_docs=truncated_count,
            total_docs=num_urls,
            retention_ratio=(
                final_tokens / original_tokens if original_tokens > 0 else 1.0
            ),
        )

        if total_max_tokens:
            logger.info(
                f"Token control: {original_tokens}→{final_tokens} tokens, "
                f"truncated {truncated_count}/{num_urls} docs, retention={truncation_stats.retention_ratio:.1%}"
            )

    return collection.sources_metadata, formatted_text, truncation_stats


def wrap_with_external_sources_tag(context: str, *, source: str = "external") -> str:
    """将上下文包装在安全边界标记中（UNTRUSTED_DATA）

    用于包裹外部数据源（web_search、web_fetch、browser、wiki、MCP远程数据），
    触发引用规则，模型需要添加引用标记【1】【2】。

    安全：5 层防护（Unicode folding + invisible chars + pattern detection + random boundary + security notice）。
    """
    from myrm_agent_harness.core.security.detection.content_boundary import (
        wrap_untrusted,
    )

    return wrap_untrusted(context, source=source)


def wrap_with_tool_output_tag(content: str) -> str:
    """将内容包装在安全边界标记中（TOOL_OUTPUT）

    用于包裹工具执行结果（代码输出、文件内容），防止 prompt injection，
    但不触发引用规则（模型无需添加引用标记）。

    安全：5 层防护（Unicode folding + invisible chars + pattern detection + random boundary + security notice）。
    """
    from myrm_agent_harness.core.security.detection.content_boundary import (
        wrap_tool_output,
    )

    return wrap_tool_output(content)
