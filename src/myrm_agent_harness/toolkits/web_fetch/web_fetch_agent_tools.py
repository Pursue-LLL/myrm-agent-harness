"""Web fetch meta-tool

Contains:
1. create_web_fetch_tool: Web fetch tool (supports fetch_full_content / fetch_and_extract modes)

[INPUT]
- toolkits.retriever.embedding.factory::EmbeddingConfig (POS: Embedding factory. Centralises embedding-service instantiation and ensures process-wide singleton semantics per configuration tuple.)
- toolkits.retriever.reranker.factory::RerankerConfig (POS: Reranker factory. Centralises reranker-service instantiation and ensures process-wide singleton semantics per configuration tuple.)
- toolkits.retriever.sufficiency (POS: Retrieval Sufficiency Guard for quality evaluation)
- toolkits.web_fetch.task_store::CrawlTaskStore (POS: SQLite WAL-backed durable task store for deep_crawl operations.)
- utils.errors::ToolError (POS: Storage quota related errors.)

[OUTPUT]
- create_web_fetch_tool: Create web fetch meta-tool

[POS]
Web fetch meta-tool. Supports sufficiency evaluation on fetch_and_extract results
when configured, appending guidance for insufficient retrieval.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.core.config.llm import LLMConfig
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig
    from myrm_agent_harness.toolkits.retriever.reranker.factory import RerankerConfig
    from myrm_agent_harness.toolkits.retriever.sufficiency import SufficiencyConfig

from myrm_agent_harness.utils.errors import ToolError

_EXTRACT_SECTION = """
### fetch_and_extract

Retrieve **relevant content snippets** from known webpages, returning the most relevant snippets. (Supports single or multiple URLs)

**Use cases:**
- Retrieve relevant info from webpages that can answer user questions; use this operation in most cases

**Parameters:**
- urls: Known and real target webpage URL list, no fabrication allowed
- questions: Query list, must be rewritten according to "query rewriting rules"
- operation: "fetch_and_extract"

**Query rewriting rules:**
- *Generate 1-5 queries centered on user intent*
- **Language alignment**: Query language should match target webpage language as much as possible; same language improves BM25 and vector retrieval effectiveness
"""

_FULL_CONTENT_WITH_EXTRACT = """
### fetch_full_content

Get the **full content** of known webpages. (Supports single or multiple URLs)

**Use cases:**
-  User **explicitly requests** "full content", "all content", "entire page"
-  Need to summarize, analyze, or process the **entire webpage**

**Parameters:**
- urls: Known webpage URL list, no fabrication allowed
- operation: "fetch_full_content"
"""

_DEEP_CRAWL_SECTION = """
### deep_crawl

Recursively crawl an **entire website** starting from a seed URL. Pages are saved as Markdown files in sandbox storage.
Returns immediately with a task_group_id; use check_crawl_status to monitor progress.

**Use cases:**
- User needs to analyze/process an entire website or documentation site
- Collecting all pages from a site for offline analysis
- Building a knowledge base from a website

**Parameters:**
- urls: Single seed URL to start crawling from (only first URL is used)
- operation: "deep_crawl"
- max_depth: Maximum link depth (default 3)
- max_pages: Maximum pages to crawl (default 100)

### check_crawl_status

Check the progress of a running deep_crawl task.

**Parameters:**
- task_group_id: The group ID returned by deep_crawl
- operation: "check_crawl_status"

### cancel_crawl

Cancel a running deep_crawl task. Already completed pages are preserved.

**Parameters:**
- task_group_id: The group ID returned by deep_crawl
- operation: "cancel_crawl"
"""

_FULL_CONTENT_ONLY = """
Get full content from known webpage URLs (Markdown format). Supports single or multiple URLs.

**Parameters:**
- urls: Known and real target webpage URL list, no fabrication allowed
"""


def create_web_fetch_tool(
    reranker_config: RerankerConfig | None = None,
    embedding_config: EmbeddingConfig | None = None,
    *,
    use_raw_markdown: bool = False,
    allow_private_networks: bool = False,
    data_dir: str | None = None,
    sufficiency_config: SufficiencyConfig | None = None,
    sufficiency_llm_config: LLMConfig | None = None,
):
    """Create web fetch meta-tool

    Args:
        reranker_config: Reranker model configuration。
        embedding_config: Embedding model configuration。
        use_raw_markdown: When True, retains raw webpage content (including ads/sidebars); when False, smart-cleaned.
        allow_private_networks: Skip SSRF private-IP blocking (local mode).
        data_dir: Sandbox data directory for deep_crawl result storage.
        sufficiency_config: RSG configuration (optional); enables retrieval quality evaluation on extract results.
        sufficiency_llm_config: LLM config for sufficiency evaluator (required if sufficiency_config.enabled).

    When both reranker and embedding are provided, enables fetch_and_extract smart extraction;
    Otherwise only exposes fetch_full_content full crawl.
    """
    enable_extract = reranker_config is not None and embedding_config is not None
    if enable_extract:
        sections = _EXTRACT_SECTION + _FULL_CONTENT_WITH_EXTRACT + _DEEP_CRAWL_SECTION
        default_op = "fetch_and_extract"
    else:
        sections = _FULL_CONTENT_ONLY + _DEEP_CRAWL_SECTION
        default_op = "fetch_full_content"

    tool_description = f"""web_fetch_tooltool is used to extract detailed content from specific webpage URLs。
{sections}
""".strip()

    class WebFetchInput(BaseModel):
        urls: list[str] = Field(description="Real webpage URL list", min_length=1)
        operation: str = Field(default=default_op, description=f"Operation type（default '{default_op}'）")
        questions: list[str] = Field(
            default_factory=list,
            description="Retrieval query list (only for fetch_and_extract, 1-5 queries), must be rewritten per query rewriting rules",
            max_length=5,
        )
        reason: str = Field(description="State your reasoning, express key info with minimal tokens, max 100 chars")
        max_depth: int = Field(default=3, description="Max crawl depth for deep_crawl (default 3)", ge=1, le=5)
        max_pages: int = Field(default=100, description="Max pages for deep_crawl (default 100)", ge=1, le=500)
        task_group_id: str = Field(default="", description="Task group ID for check_crawl_status")

    @tool("web_fetch_tool", description=tool_description, args_schema=WebFetchInput)
    async def web_fetch_func(
        urls: list[str],
        operation: str = default_op,
        questions: list[str] | None = None,
        reason: str = "",
        max_depth: int = 3,
        max_pages: int = 100,
        task_group_id: str = "",
    ) -> dict[str, str | dict[str, object]]:
        """Execute web fetch and return formatted results。"""
        from myrm_agent_harness.utils.logger_utils import get_agent_logger

        logger = get_agent_logger(__name__)

        if operation == "deep_crawl":
            if not allow_private_networks:
                from myrm_agent_harness.core.security.guards.ssrf import validate_url_for_ssrf

                result = validate_url_for_ssrf(urls[0])
                if not result.safe:
                    raise ToolError(
                        f"URL blocked (SSRF protection): {result.error} — {urls[0]}",
                        user_hint="The URL is blocked for security reasons. Use a different, publicly accessible URL.",
                    )
            return await _deep_crawl(
                urls[0],
                max_depth=max_depth,
                max_pages=max_pages,
                allow_private_networks=allow_private_networks,
                data_dir=data_dir,
            )

        if operation == "check_crawl_status":
            if not task_group_id:
                raise ToolError(
                    "task_group_id is required for check_crawl_status",
                    user_hint="Provide the task_group_id returned by deep_crawl.",
                )
            return await _check_crawl_status(task_group_id, data_dir=data_dir)

        if operation == "cancel_crawl":
            if not task_group_id:
                raise ToolError(
                    "task_group_id is required for cancel_crawl",
                    user_hint="Provide the task_group_id returned by deep_crawl.",
                )
            return await _cancel_crawl(task_group_id, data_dir=data_dir)

        if not allow_private_networks:
            from myrm_agent_harness.core.security.guards.ssrf import validate_url_for_ssrf
            from myrm_agent_harness.utils.url_utils import check_url_exfiltration

            for url in urls:
                # SSRF protection
                result = validate_url_for_ssrf(url)
                if not result.safe:
                    raise ToolError(
                        f"URL blocked (SSRF protection): {result.error} — {url}",
                        user_hint="The URL is blocked for security reasons. Use a different, publicly accessible URL.",
                    )

                # Data exfiltration detection
                exfiltration_warnings = check_url_exfiltration(url, allow_private_networks=allow_private_networks)
                if exfiltration_warnings:
                    from myrm_agent_harness.utils.url_utils import sanitize_url_for_error

                    safe_url = sanitize_url_for_error(url)
                    logger.warning(f" Potential data exfiltration detected in URL: {safe_url}")
                    for warning in exfiltration_warnings:
                        logger.warning(f" - {warning}")
                    raise ToolError(
                        f"URL blocked (data exfiltration detection): {'; '.join(exfiltration_warnings)} — {safe_url}",
                        user_hint="The URL appears to contain sensitive data (API keys, file paths, or credentials). Remove sensitive data from the URL.",
                    )

        if questions is None:
            questions = []

        if operation == "fetch_full_content":
            return await _fetch_full_content(
                urls,
                use_raw_markdown=use_raw_markdown,
                allow_private_networks=allow_private_networks,
            )

        if not enable_extract:
            raise ToolError(
                "fetch_and_extract is disabled (requires both reranker_config and embedding_config)",
                user_hint="Use operation='fetch_full_content' instead, or ensure the server has reranker and embedding configured.",
            )
        if not questions:
            raise ToolError(
                "'questions' parameter is required for fetch_and_extract operation",
                user_hint="Provide 1-5 search queries in the 'questions' parameter for fetch_and_extract.",
            )
        assert reranker_config is not None and embedding_config is not None
        result = await _fetch_and_extract(
            urls,
            questions,
            reranker_config,
            embedding_config,
            allow_private_networks=allow_private_networks,
        )

        if sufficiency_config and sufficiency_config.enabled and sufficiency_llm_config and result.get("content"):
            from myrm_agent_harness.toolkits.retriever.sufficiency import evaluate_sufficiency

            original_query = " | ".join(questions)
            verdict = await evaluate_sufficiency(
                query=original_query,
                snippets=result["content"],
                llm_config=sufficiency_llm_config,
                config=sufficiency_config,
            )

            if not verdict.is_sufficient and verdict.confidence >= sufficiency_config.confidence_threshold:
                guidance_parts: list[str] = []
                if verdict.missing_aspects:
                    guidance_parts.append("**Missing information**: " + "; ".join(verdict.missing_aspects))
                if verdict.suggested_queries:
                    guidance_parts.append(
                        "**Suggested follow-up searches**: " + ", ".join(f'"{q}"' for q in verdict.suggested_queries)
                    )
                if verdict.negative_constraint_violations:
                    guidance_parts.append(
                        "**Exclusion violations** (user requested these be excluded): "
                        + "; ".join(verdict.negative_constraint_violations)
                    )
                if guidance_parts:
                    notice = "\n\n---\n⚠️ **Retrieval Sufficiency Notice**: The extracted content may be incomplete.\n"
                    result["content"] += notice + "\n".join(guidance_parts)

                metadata = result.get("metadata", {})
                if isinstance(metadata, dict):
                    metadata["sufficiency"] = {
                        "is_sufficient": verdict.is_sufficient,
                        "confidence": verdict.confidence,
                        "missing_aspects": list(verdict.missing_aspects),
                        "suggested_queries": list(verdict.suggested_queries),
                        "negative_constraint_violations": list(verdict.negative_constraint_violations),
                    }

        return result

    return web_fetch_func


MAX_FULL_CONTENT_CHARS = 100_000


async def _fetch_full_content(
    urls: list[str],
    *,
    use_raw_markdown: bool = False,
    allow_private_networks: bool = False,
) -> dict[str, str | dict[str, object]]:
    """Get full webpage content (truncated to MAX_FULL_CONTENT_CHARS chars)"""
    from myrm_agent_harness.toolkits.web_fetch import CrawlEngine, web_fetch_tools
    from myrm_agent_harness.utils.context_format import format_crawl_results, wrap_with_external_sources_tag

    need_custom_engine = use_raw_markdown or allow_private_networks
    engine = (
        CrawlEngine(
            use_raw_markdown=use_raw_markdown,
            allow_private_networks=allow_private_networks,
            session_vault=web_fetch_tools._http_fetcher._session_vault,
        )
        if need_custom_engine
        else web_fetch_tools
    )
    success_results, failed_results = await engine.crawl_many(urls, max_chars=MAX_FULL_CONTENT_CHARS)

    if not success_results and not failed_results:
        raise ToolError(
            "No results returned from crawl",
            user_hint="The URLs may be unreachable or blocked. Verify the URLs are correct and publicly accessible.",
        )

    sources_metadata = [
        {"url": doc.metadata.get("url", url), "title": doc.metadata.get("title", "")} for url, doc in success_results
    ]

    formatted_context = format_crawl_results(success_results=success_results, include_title=True, include_date=False)
    if not formatted_context:
        raise ToolError(
            "No content found in the provided URLs",
            user_hint="The pages may be empty, require authentication, or block automated access. Try different URLs.",
        )

    truncated = len(formatted_context) > MAX_FULL_CONTENT_CHARS
    if truncated:
        formatted_context = formatted_context[:MAX_FULL_CONTENT_CHARS]

    return {
        "content": wrap_with_external_sources_tag(formatted_context, source="web_fetch"),
        "metadata": {
            "sources": sources_metadata,
            "operation": "fetch_full_content",
            "truncated": truncated,
        },
    }


async def _fetch_and_extract(
    urls: list[str],
    questions: list[str],
    reranker_config: RerankerConfig,
    embedding_config: EmbeddingConfig,
    *,
    allow_private_networks: bool = False,
) -> dict[str, str | dict[str, object]]:
    """Retrieve relevant content snippets from webpages"""
    from myrm_agent_harness.toolkits.retriever.embedding.factory import get_embedding_service
    from myrm_agent_harness.toolkits.retriever.engine import retriever_tools
    from myrm_agent_harness.toolkits.retriever.reranker.factory import get_reranker_service
    from myrm_agent_harness.utils.context_format import wrap_with_external_sources_tag

    reranker = get_reranker_service(reranker_config)
    embeddings = get_embedding_service(embedding_config)
    url_metadata_list, formatted_context, error = await retriever_tools.retrieve_from_urls(
        urls=urls,
        questions=questions,
        reranker=reranker,
        embeddings=embeddings,
        top_k=10,
        allow_private_networks=allow_private_networks,
    )

    if error:
        raise ToolError(
            f"Fetch failed: {error}",
            user_hint="The fetch operation failed. Check if the URLs are valid and the pages are accessible.",
        )
    if not formatted_context:
        raise ToolError(
            "No relevant content found in the provided URLs",
            user_hint="The pages were fetched but no content matched the queries. Try broader or different questions.",
        )

    return {
        "content": wrap_with_external_sources_tag(formatted_context, source="web_fetch"),
        "metadata": {"sources": url_metadata_list, "operation": "fetch_and_extract", "questions": questions},
    }


async def _deep_crawl(
    seed_url: str,
    *,
    max_depth: int = 3,
    max_pages: int = 100,
    allow_private_networks: bool = False,
    data_dir: str | None = None,
) -> dict[str, str | dict[str, object]]:
    """Initiate asynchronous deep crawl of a website."""
    from pathlib import Path

    from myrm_agent_harness.toolkits.web_fetch import CrawlEngine
    from myrm_agent_harness.toolkits.web_fetch.deep_crawl import DeepCrawlPipeline
    from myrm_agent_harness.toolkits.web_fetch.rate_limiter import DomainRateLimiter
    from myrm_agent_harness.toolkits.web_fetch.robots_parser import RobotsParser
    from myrm_agent_harness.toolkits.web_fetch.task_executor import CrawlTaskExecutor
    from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore

    if not data_dir:
        data_dir = "/tmp/myrm_crawl_data"

    base_path = Path(data_dir)
    db_path = base_path / ".crawl_tasks.db"

    store = CrawlTaskStore(db_path)
    engine = CrawlEngine(allow_private_networks=allow_private_networks)
    rate_limiter = DomainRateLimiter(default_interval=1.5, max_concurrent_per_domain=2)
    robots_parser = RobotsParser()
    executor = CrawlTaskExecutor(store, engine, rate_limiter, max_workers=5)

    pipeline = DeepCrawlPipeline(
        store=store,
        executor=executor,
        engine=engine,
        robots_parser=robots_parser,
        rate_limiter=rate_limiter,
        data_dir=base_path,
    )

    result = await pipeline.start_deep_crawl(seed_url, max_depth=max_depth, max_pages=max_pages)

    return {
        "content": (
            f"Deep crawl initiated for: {seed_url}\n"
            f"Task Group ID: {result['task_group_id']}\n"
            f"Total pages discovered: {result['total_pages']}\n"
            f"Results will be saved to: {result['result_dir']}\n\n"
            f"Use check_crawl_status with task_group_id='{result['task_group_id']}' to monitor progress.\n"
            f"Once completed, use code_execution to read and process files from the result directory."
        ),
        "metadata": {
            "operation": "deep_crawl",
            **result,
        },
    }


async def _check_crawl_status(
    task_group_id: str,
    *,
    data_dir: str | None = None,
) -> dict[str, str | dict[str, object]]:
    """Check status of a deep_crawl task group."""
    import json
    from pathlib import Path

    from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore

    if not data_dir:
        data_dir = "/tmp/myrm_crawl_data"

    db_path = Path(data_dir) / ".crawl_tasks.db"
    if not db_path.exists():
        raise ToolError(
            f"No crawl database found at {db_path}",
            user_hint="No deep_crawl tasks have been started. Start one first with operation='deep_crawl'.",
        )

    store = CrawlTaskStore(db_path)
    summary = store.get_group_summary(task_group_id)

    if not summary:
        raise ToolError(
            f"Task group not found: {task_group_id}",
            user_hint="The task_group_id is invalid. Check the ID returned by deep_crawl.",
        )

    is_done = not store.has_pending_or_running(task_group_id)
    status = "completed" if is_done else "running"

    index_path = Path(summary.result_dir) / "_index.json"
    index_info = ""
    if index_path.exists():
        index_data = json.loads(index_path.read_text(encoding="utf-8"))
        pages = index_data.get("pages", [])
        if pages:
            index_info = "\n\nCrawled pages:\n"
            for page in pages[:20]:
                index_info += f"  - {page['file']}: {page['title']} ({page['url']})\n"
            if len(pages) > 20:
                index_info += f"  ... and {len(pages) - 20} more\n"

    return {
        "content": (
            f"Deep crawl status: {status}\n"
            f"Progress: {summary.completed}/{summary.total} pages completed"
            + (f" ({summary.failed} failed)" if summary.failed else "")
            + (f" ({summary.cancelled} cancelled)" if summary.cancelled else "")
            + f"\nPending: {summary.pending}, Running: {summary.running}\n"
            f"Results directory: {summary.result_dir}"
            + index_info
        ),
        "metadata": {
            "operation": "check_crawl_status",
            "group_id": task_group_id,
            "status": status,
            "total": summary.total,
            "completed": summary.completed,
            "failed": summary.failed,
            "pending": summary.pending,
            "running": summary.running,
            "cancelled": summary.cancelled,
            "result_dir": summary.result_dir,
        },
    }


async def _cancel_crawl(
    task_group_id: str,
    *,
    data_dir: str | None = None,
) -> dict[str, str | dict[str, object]]:
    """Cancel a running deep_crawl task group."""
    from pathlib import Path

    from myrm_agent_harness.toolkits.web_fetch.task_store import CrawlTaskStore

    if not data_dir:
        data_dir = "/tmp/myrm_crawl_data"

    db_path = Path(data_dir) / ".crawl_tasks.db"
    if not db_path.exists():
        raise ToolError(
            f"No crawl database found at {db_path}",
            user_hint="No deep_crawl tasks have been started. Start one first with operation='deep_crawl'.",
        )

    store = CrawlTaskStore(db_path)
    summary = store.get_group_summary(task_group_id)

    if not summary:
        raise ToolError(
            f"Task group not found: {task_group_id}",
            user_hint="The task_group_id is invalid. Check the ID returned by deep_crawl.",
        )

    cancelled_count = store.cancel_group(task_group_id)

    return {
        "content": (
            f"Deep crawl cancelled: {task_group_id}\n"
            f"Cancelled {cancelled_count} pending tasks.\n"
            f"Completed pages ({summary.completed}) are preserved in: {summary.result_dir}"
        ),
        "metadata": {
            "operation": "cancel_crawl",
            "group_id": task_group_id,
            "cancelled_count": cancelled_count,
            "completed": summary.completed,
            "result_dir": summary.result_dir,
        },
    }
