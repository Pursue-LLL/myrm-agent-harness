"""Web fetch meta-tool

Contains:
1. create_web_fetch_tool: Web fetch tool (fetch_full_content / fetch_and_extract)

[INPUT]
- toolkits.retriever.embedding.factory::EmbeddingConfig
- toolkits.retriever.reranker.factory::RerankerConfig
- toolkits.retriever.sufficiency (POS: Retrieval Sufficiency Guard)
- toolkits.web_fetch.spill::maybe_spill_web_fetch_content
- toolkits.web_fetch._web_fetch_tool_description::resolve_web_fetch_tool_description
- agent.errors.tool_error_category::ToolErrorCategory
- utils.errors::ToolError

[OUTPUT]
- create_web_fetch_tool: Create web fetch meta-tool

[POS]
Web fetch meta-tool for known-URL full read and RAG extract modes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from langchain.tools import tool
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from myrm_agent_harness.core.config.llm import LLMConfig
    from myrm_agent_harness.toolkits.retriever.embedding.factory import EmbeddingConfig
    from myrm_agent_harness.toolkits.retriever.reranker.factory import RerankerConfig
    from myrm_agent_harness.toolkits.retriever.sufficiency import SufficiencyConfig

from myrm_agent_harness.agent.errors import ToolErrorCategory
from myrm_agent_harness.toolkits.web_fetch._web_fetch_tool_description import (
    resolve_web_fetch_tool_description,
)
from myrm_agent_harness.utils.errors import ToolError


def create_web_fetch_tool(
    reranker_config: RerankerConfig | None = None,
    embedding_config: EmbeddingConfig | None = None,
    *,
    use_raw_markdown: bool = False,
    allow_private_networks: bool = False,
    sufficiency_config: SufficiencyConfig | None = None,
    sufficiency_llm_config: LLMConfig | None = None,
    model_preview_chars: int | None = None,
    blocked_hostnames: tuple[str, ...] | None = None,
    description_locale: str | None = None,
):
    """Create web fetch meta-tool.

    ``blocked_hostnames`` is an optional hostname blocklist (exact or ``*.``
    wildcard patterns). When set, URLs whose host matches a pattern are
    rejected before fetching — a generic content policy hook callers can use
    for benchmark decontamination or domain filtering. None disables it.

    ``description_locale`` selects the LLM-facing tool description locale
    (default English).
    """
    enable_extract = reranker_config is not None and embedding_config is not None
    default_op = "fetch_and_extract" if enable_extract else "fetch_full_content"

    tool_description = resolve_web_fetch_tool_description(
        enable_extract, description_locale
    )

    preview_budget = model_preview_chars

    class WebFetchInput(BaseModel):
        urls: list[str] = Field(description="Real webpage URL list", min_length=1)
        operation: str = Field(
            default=default_op, description=f"Operation type (default '{default_op}')"
        )
        questions: list[str] = Field(
            default_factory=list,
            description="Retrieval query list (fetch_and_extract only, 1-5 queries)",
            max_length=5,
        )
        reason: str = Field(
            description="State your reasoning, express key info with minimal tokens, max 100 chars"
        )

    @tool("web_fetch_tool", description=tool_description, args_schema=WebFetchInput)
    async def web_fetch_func(
        urls: list[str],
        operation: str = default_op,
        questions: list[str] | None = None,
        reason: str = "",
    ) -> dict[str, str | dict[str, object] | None]:
        """Execute web fetch and return formatted results."""
        from myrm_agent_harness.utils.logger_utils import get_agent_logger

        logger = get_agent_logger(__name__)

        if blocked_hostnames:
            from myrm_agent_harness.toolkits.browser.domain_filter import (
                DomainBlocklist,
            )

            blocklist = DomainBlocklist.from_strings(blocked_hostnames)
            for url in urls:
                hostname = (urlparse(url).hostname or "").lower()
                if blocklist.is_blocked(hostname):
                    raise ToolError(
                        f"URL blocked: {url}",
                        user_hint="The URL host is excluded from fetching. Use a different URL.",
                        error_code="BENCHMARK_BLOCKED_HOST",
                        diagnostic_info={
                            "error_category": ToolErrorCategory.BENCHMARK_BLOCKED.value,
                            "hostname": hostname,
                        },
                    )

        if not allow_private_networks:
            from myrm_agent_harness.core.security.guards.ssrf import (
                validate_url_for_ssrf,
            )
            from myrm_agent_harness.utils.url_utils import check_url_exfiltration

            for url in urls:
                result = validate_url_for_ssrf(url)
                if not result.safe:
                    raise ToolError(
                        f"URL blocked (SSRF protection): {result.error} — {url}",
                        user_hint="The URL is blocked for security reasons. Use a different, publicly accessible URL.",
                    )

                exfiltration_warnings = check_url_exfiltration(
                    url, allow_private_networks=allow_private_networks
                )
                if exfiltration_warnings:
                    from myrm_agent_harness.utils.url_utils import (
                        sanitize_url_for_error,
                    )

                    safe_url = sanitize_url_for_error(url)
                    logger.warning(
                        " Potential data exfiltration detected in URL: %s", safe_url
                    )
                    for warning in exfiltration_warnings:
                        logger.warning(" - %s", warning)
                    raise ToolError(
                        f"URL blocked (data exfiltration detection): {'; '.join(exfiltration_warnings)} — {safe_url}",
                        user_hint="The URL appears to contain sensitive data. Remove secrets from the URL.",
                    )

        if questions is None:
            questions = []

        if operation == "fetch_full_content":
            result = await _fetch_full_content(
                urls,
                use_raw_markdown=use_raw_markdown,
                allow_private_networks=allow_private_networks,
                preview_chars=preview_budget,
            )
            evicted_ref = result.get("evicted_ref")
            if isinstance(evicted_ref, str) and evicted_ref:
                from myrm_agent_harness.toolkits.web_fetch.spill import (
                    emit_web_fetch_evicted_ref,
                )

                await emit_web_fetch_evicted_ref(
                    evicted_ref,
                    stored_chars=(
                        result["evicted_stored_chars"]
                        if isinstance(result.get("evicted_stored_chars"), int)
                        else None
                    ),
                    total_lines=(
                        result["evicted_total_lines"]
                        if isinstance(result.get("evicted_total_lines"), int)
                        else None
                    ),
                    storage_truncated=bool(result.get("evicted_storage_truncated")),
                )
            return result

        if not enable_extract:
            raise ToolError(
                "fetch_and_extract is disabled (requires both reranker_config and embedding_config)",
                user_hint="Use operation='fetch_full_content' instead.",
            )
        if not questions:
            raise ToolError(
                "'questions' parameter is required for fetch_and_extract operation",
                user_hint="Provide 1-5 search queries in the 'questions' parameter.",
            )
        assert reranker_config is not None and embedding_config is not None
        result = await _fetch_and_extract(
            urls,
            questions,
            reranker_config,
            embedding_config,
            allow_private_networks=allow_private_networks,
        )

        if (
            sufficiency_config
            and sufficiency_config.enabled
            and sufficiency_llm_config
            and result.get("content")
        ):
            from myrm_agent_harness.toolkits.retriever.sufficiency import (
                evaluate_sufficiency,
            )

            original_query = " | ".join(questions)
            verdict = await evaluate_sufficiency(
                query=original_query,
                snippets=result["content"],
                llm_config=sufficiency_llm_config,
                config=sufficiency_config,
            )

            if (
                not verdict.is_sufficient
                and verdict.confidence >= sufficiency_config.confidence_threshold
            ):
                guidance_parts: list[str] = []
                if verdict.missing_aspects:
                    guidance_parts.append(
                        "**Missing information**: " + "; ".join(verdict.missing_aspects)
                    )
                if verdict.suggested_queries:
                    guidance_parts.append(
                        "**Suggested follow-up searches**: "
                        + ", ".join(f'"{q}"' for q in verdict.suggested_queries)
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
                        "negative_constraint_violations": list(
                            verdict.negative_constraint_violations
                        ),
                    }

        return result

    return web_fetch_func


async def _fetch_full_content(
    urls: list[str],
    *,
    use_raw_markdown: bool = False,
    allow_private_networks: bool = False,
    preview_chars: int | None = None,
) -> dict[str, str | dict[str, object] | None]:
    """Get webpage content with head/tail preview and optional sandbox spill."""
    from myrm_agent_harness.toolkits.web_fetch import FetchEngine, web_fetch_tools
    from myrm_agent_harness.toolkits.web_fetch.spill import (
        DEFAULT_MODEL_PREVIEW_CHARS,
        maybe_spill_web_fetch_content,
    )
    from myrm_agent_harness.utils.context_format import (
        format_crawl_results,
        wrap_with_external_sources_tag,
    )

    budget = preview_chars if preview_chars is not None else DEFAULT_MODEL_PREVIEW_CHARS

    need_custom_engine = use_raw_markdown or allow_private_networks
    engine = (
        FetchEngine(
            use_raw_markdown=use_raw_markdown,
            allow_private_networks=allow_private_networks,
            session_vault=web_fetch_tools._http_fetcher._session_vault,
        )
        if need_custom_engine
        else web_fetch_tools
    )
    success_results, failed_results = await engine.crawl_many(urls, max_chars=0)

    if not success_results and not failed_results:
        raise ToolError(
            "No results returned from crawl",
            user_hint="The URLs may be unreachable or blocked. Verify the URLs are correct and publicly accessible.",
        )

    sources_metadata = [
        {"url": doc.metadata.get("url", url), "title": doc.metadata.get("title", "")}
        for url, doc in success_results
    ]

    formatted_context = format_crawl_results(
        success_results=success_results, include_title=True, include_date=False
    )
    if not formatted_context:
        raise ToolError(
            "No content found in the provided URLs",
            user_hint="The pages may be empty, require authentication, or block automated access. Try different URLs.",
        )

    from myrm_agent_harness.toolkits.web_fetch.content_sanitize import (
        strip_base64_images_from_markdown,
    )

    formatted_context = strip_base64_images_from_markdown(formatted_context)

    spill = await maybe_spill_web_fetch_content(formatted_context, preview_chars=budget)

    return {
        "content": wrap_with_external_sources_tag(spill.preview, source="web_fetch"),
        "metadata": {
            "sources": sources_metadata,
            "operation": "fetch_full_content",
            "truncated": spill.spilled,
            "raw_chars": len(formatted_context),
        },
        "evicted_ref": spill.evicted_ref,
        "evicted_stored_chars": spill.stored_chars,
        "evicted_total_lines": spill.total_lines,
        "evicted_storage_truncated": spill.storage_truncated,
    }


async def _fetch_and_extract(
    urls: list[str],
    questions: list[str],
    reranker_config: RerankerConfig,
    embedding_config: EmbeddingConfig,
    *,
    allow_private_networks: bool = False,
) -> dict[str, str | dict[str, object]]:
    """Retrieve relevant content snippets from webpages."""
    from myrm_agent_harness.toolkits.retriever.embedding.factory import (
        get_embedding_service,
    )
    from myrm_agent_harness.toolkits.retriever.engine import retriever_tools
    from myrm_agent_harness.toolkits.retriever.reranker.factory import (
        get_reranker_service,
    )
    from myrm_agent_harness.utils.context_format import wrap_with_external_sources_tag

    reranker = get_reranker_service(reranker_config)
    embeddings = get_embedding_service(embedding_config)
    url_metadata_list, formatted_context, error = (
        await retriever_tools.retrieve_from_urls(
            urls=urls,
            questions=questions,
            reranker=reranker,
            embeddings=embeddings,
            top_k=10,
            allow_private_networks=allow_private_networks,
        )
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
        "content": wrap_with_external_sources_tag(
            formatted_context, source="web_fetch"
        ),
        "metadata": {
            "sources": url_metadata_list,
            "operation": "fetch_and_extract",
            "questions": questions,
        },
    }
