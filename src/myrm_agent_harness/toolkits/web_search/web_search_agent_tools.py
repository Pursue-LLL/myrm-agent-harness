"""Web search meta-tool


[INPUT]
- toolkits.web_search.web_searcher::SearchServiceConfig (POS: search service configuration)
- toolkits.retriever.sufficiency (POS: Retrieval Sufficiency Guard for quality evaluation)
- langchain.tools::tool (POS: LangChain tool decorator)
- pydantic::BaseModel, Field, field_validator (POS: parameter validation)

[OUTPUT]
- create_web_search_tool: factory function to create web search tool

[POS]
Web search meta-tool. Integrates web search capability as a meta-tool (high frequency, 80%+ queries require search).
Supports batch queries, query rewriting, and cost control. Provides real-time information retrieval via
SearchServiceConfig-configured search engines.

When sufficiency evaluation is enabled, post-search results are evaluated for completeness
and negative constraint violations, with guidance appended for the agent to act upon.

Contains:
1. create_web_search_tool: web search tool
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from langchain.tools import tool
from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:
    from myrm_agent_harness.core.config.llm import LLMConfig
    from myrm_agent_harness.toolkits.retriever.reranker.factory import RerankerConfig
    from myrm_agent_harness.toolkits.retriever.sufficiency import SufficiencyConfig
    from myrm_agent_harness.toolkits.web_search.engine import SearchServiceConfig

from myrm_agent_harness.toolkits.web_search._web_search_tool_description import (
    resolve_web_search_tool_description,
)


def create_web_search_tool(
    search_service_cfg: SearchServiceConfig,
    reranker_config: RerankerConfig | None = None,
    sufficiency_config: SufficiencyConfig | None = None,
    sufficiency_llm_config: LLMConfig | None = None,
    *,
    description_locale: str | None = None,
):
    """Create a web search meta-tool.

    Args:
        search_service_cfg: Search service configuration
        reranker_config: Reranker model configuration (optional); when provided, precision mode is auto-enabled
        sufficiency_config: RSG configuration (optional); enables retrieval quality evaluation
        sufficiency_llm_config: LLM config for the sufficiency evaluator (required if sufficiency_config.enabled)
        description_locale: BCP-47 locale for LLM-facing tool description (default English).

    Returns:
        web_search_tool tool function
    """
    tool_description = resolve_web_search_tool_description(description_locale)

    class WebSearchInput(BaseModel):
        questions: list[str] = Field(
            description="Search query list (1-5), must follow query rewriting rules, ensuring independence, self-containment, and multi-dimensionality",
            min_length=1,
            max_length=5,
        )
        reason: str = Field(
            default="",
            description="Search rationale, express key information in minimal tokens, max 100 chars",
        )
        time_range: str | None = Field(
            default=None,
            description="Time range. Set only when the user explicitly mentions a time constraint: day/week/month/year or YYYY-MM-DD..YYYY-MM-DD.",
        )

        @field_validator("questions", mode="before")
        @classmethod
        def convert_string_to_list(cls, v: str | list[str]) -> list[str]:
            """Handle LLM passing comma-separated strings — auto-converts to list."""
            if isinstance(v, str):
                parts = re.split(r"[,，]", v)
                return [q.strip() for q in parts if q.strip()]
            return v

    @tool("web_search_tool", description=tool_description, args_schema=WebSearchInput)
    async def web_search_func(
        questions: list[str],
        reason: str = "",
        time_range: str | None = None,
    ) -> dict:
        """Execute web search and return structured results.

        Returns: {"content": "...", "metadata": {...}}
        - content: Formatted text content (for the LLM)
        - metadata: Structured metadata (for business layer, e.g., citation collection)

        Results are processed via BM25 + reranker model, returning the most relevant content snippets.
        """
        from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools

        explicit_params: dict[str, object] | None = None
        if time_range:
            explicit_params = {"time_range": time_range}

        web_search = WebSearchTools(search_service_cfg, reranker_config=reranker_config)
        sources_metadata, formatted_context = (
            await web_search.fast_search_with_questions(
                questions=questions,
                search_results_per_query=10,
                top_k=10,
                explicit_params=explicit_params,
            )
        )

        from myrm_agent_harness.toolkits.web_search.citation_resolver import (
            enrich_sources_with_resolved_urls,
        )

        sources_metadata = await enrich_sources_with_resolved_urls(sources_metadata)

        if formatted_context:
            from myrm_agent_harness.utils.context_format import (
                wrap_with_external_sources_tag,
            )

            content = wrap_with_external_sources_tag(
                formatted_context, source="web_search"
            )
        else:
            content = formatted_context

        sufficiency_metadata: dict[str, object] = {}

        if (
            sufficiency_config
            and sufficiency_config.enabled
            and sufficiency_llm_config
            and content
        ):
            from myrm_agent_harness.toolkits.retriever.sufficiency import (
                evaluate_sufficiency,
            )

            original_query = " | ".join(questions)
            verdict = await evaluate_sufficiency(
                query=original_query,
                snippets=content,
                llm_config=sufficiency_llm_config,
                config=sufficiency_config,
            )

            sufficiency_metadata = {
                "is_sufficient": verdict.is_sufficient,
                "confidence": verdict.confidence,
                "missing_aspects": list(verdict.missing_aspects),
                "suggested_queries": list(verdict.suggested_queries),
                "negative_constraint_violations": list(
                    verdict.negative_constraint_violations
                ),
            }

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
                    notice = "\n\n---\n⚠️ **Retrieval Sufficiency Notice**: The search results may be incomplete.\n"
                    content += notice + "\n".join(guidance_parts)

        return {
            "content": content,
            "metadata": {
                "sources": sources_metadata,
                "search_queries": questions,
                "total_results": len(sources_metadata),
                **(
                    {"sufficiency": sufficiency_metadata}
                    if sufficiency_metadata
                    else {}
                ),
            },
        }

    return web_search_func
