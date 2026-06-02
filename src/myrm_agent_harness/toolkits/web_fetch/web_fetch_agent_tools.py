"""Web fetch meta-tool

Contains:
1. create_web_fetch_tool: Web fetch tool (supports fetch_full_content / fetch_and_extract modes)

[INPUT]
- toolkits.retriever.embedding.factory::EmbeddingConfig (POS: Embedding factory. Centralises embedding-service instantiation and ensures process-wide singleton semantics per configuration tuple.)
- toolkits.retriever.reranker.factory::RerankerConfig (POS: Reranker factory. Centralises reranker-service instantiation and ensures process-wide singleton semantics per configuration tuple.)
- utils.errors::ToolError (POS: Storage quota related errors.)

[OUTPUT]
- create_web_fetch_tool: Create web fetch meta-tool

[POS]
Web fetch meta-tool
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig
    from myrm_agent_harness.toolkits.retriever.reranker.factory import RerankerConfig

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
):
    """Create web fetch meta-tool

    Args:
        reranker_config: Reranker model configuration。
        embedding_config: Embedding model configuration。
        use_raw_markdown: When True, retains raw webpage content (including ads/sidebars); when False, smart-cleaned.
        allow_private_networks: Skip SSRF private-IP blocking (local mode).

    When both are provided, enables fetch_and_extract smart extraction；
    Otherwise only exposes fetch_full_content full crawl。
    """
    enable_extract = reranker_config is not None and embedding_config is not None
    if enable_extract:
        sections = _EXTRACT_SECTION + _FULL_CONTENT_WITH_EXTRACT
        default_op = "fetch_and_extract"
    else:
        sections = _FULL_CONTENT_ONLY
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

    @tool("web_fetch_tool", description=tool_description, args_schema=WebFetchInput)
    async def web_fetch_func(
        urls: list[str],
        operation: str = default_op,
        questions: list[str] | None = None,
        reason: str = "",
    ) -> dict[str, str | dict[str, object]]:
        """Execute web fetch and return formatted results。"""
        from myrm_agent_harness.utils.logger_utils import get_agent_logger

        logger = get_agent_logger(__name__)

        if not allow_private_networks:
            from myrm_agent_harness.utils.url_utils import check_url_exfiltration, validate_url_for_ssrf

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
        return await _fetch_and_extract(
            urls,
            questions,
            reranker_config,
            embedding_config,
            allow_private_networks=allow_private_networks,
        )

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
