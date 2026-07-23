"""Web search meta-tool


[INPUT]
- toolkits.web_search_tools::SearchServiceConfig (POS: search service configuration)
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


def create_web_search_tool(
    search_service_cfg: SearchServiceConfig,
    reranker_config: RerankerConfig | None = None,
    sufficiency_config: SufficiencyConfig | None = None,
    sufficiency_llm_config: LLMConfig | None = None,
):
    """Create a web search meta-tool.

    Args:
        search_service_cfg: Search service configuration
        reranker_config: Reranker model configuration (optional); when provided, precision mode is auto-enabled
        sufficiency_config: RSG configuration (optional); enables retrieval quality evaluation
        sufficiency_llm_config: LLM config for the sufficiency evaluator (required if sufficiency_config.enabled)

    Returns:
        web_search_tool tool function
    """
    tool_description = """
web_search_tool is used to search the internet for real-time information, news, academic materials, or specific facts. Use this tool when the user's question involves facts that the model's own knowledge base cannot confirm.

## Parameter Guide

- questions: List of search queries (1-5)
  - Must follow the "query rewriting rules" below
  - Prefer generating 1-2 queries; only generate 3-5 when necessary

## Important: Search Cost Control
This tool supports batch searching of multiple queries in a single call, reducing the need for multiple calls and improving performance. However, be mindful of cost — the number of queries per search directly affects expenses:

- Most questions only need 1-2 queries, and each query should be high-value (containing as much relevant information as possible) to maximize the valid information obtained per query and reduce cost.
- A single search should cover 80% of the question's information needs. Do not repeatedly search for similar information unless critical information is missing.

## Query Rewriting Rules (Core)

<role>
You are a "search intent analysis and query rewriting" expert.
Analyze the user's question and conversation history, converting them into high-quality, independent, and diverse search queries.
**Prefer generating 1-2 queries when sufficient; only generate 3-5 for complex or multi-faceted questions to obtain essential information**, up to 5 maximum.
</role>

<rewrite_rules desc="Core principles for query rewriting">

1. Context Fusion and Independence

- You must first consider whether the user is asking a follow-up to an existing conversation.
- If the user's question is a follow-up (contains pronouns like "it", "that", "he", etc., or follow-up markers like "what about", "how about"), you must analyze the conversation history, find the specific entity the pronoun refers to, and replace the pronoun with that entity.
- The rewritten query must be **independent and self-contained** — anyone should be able to understand its exact meaning even without the conversation history.
- **No semantic coupling**: Each query is used independently in the search engine and must contain complete, standalone information without coupling to other queries.
- Example:
  - History: "What's new in Python 3.12?" → Current: "How does it compare to 3.11?"
  - Rewritten: "Python 3.12 vs 3.11 new feature comparison"

2. Intent Correction and Standardization

After understanding the context, you must clean up and standardize the query.
- **Auto-correction**: Fix obvious spelling, grammar, or terminology errors in user input.
- **Expression standardization**: Convert colloquial or non-standard expressions into search-engine-friendly standardized queries.
- Example: "Why is it so slow?" → "Next.js 15.0 performance issues"

3. Ambiguous Query Disambiguation

For queries with unclear intent (e.g., no time constraints), you must infer intent based on common sense and timeliness.

- **Guess the mainstream intent**: Infer **one** most likely mainstream entity or event the user is querying.
- **Add timeliness**: When necessary (e.g., querying events, versions, schedules, prices), proactively add current date or "latest" to ensure search result validity.
- **Appropriately extend query intent**: For schedule queries, the user likely also wants results, so extend with a query about outcomes based on the multi-angle principle.

Example:
  "S15 schedule" → "2025 League of Legends S15 match results", "2028 League of Legends S15 World Championship schedule"
  "Bitcoin price" → "Today's latest Bitcoin price"

4. Aggregation and Decomposition

- Complex questions: Besides generating specific queries for each sub-question, you must also generate an "aggregate query" that encompasses all sub-question intents.
- This aggregate query aims to find a single, high-quality document that comprehensively covers all sub-questions (e.g., comparison reviews, version update overviews), complementing rather than replacing specific sub-queries.

5. Precision and Multi-dimensionality (Highest Priority)

- **Entity anchoring**:
    - Must precisely identify the core entity of the user's query (e.g., "S15 World Championship", "DeepSeek-V3").
    - Core entities and constraints (version numbers, dates, locations) must not be arbitrarily changed — they are the common foundation of all queries.

- **No information overlap**: Each generated query must point to **completely different** information sources or topics. If query A's search results might contain query B's answer, then query B is redundant.
  -  Wrong (synonymous repetition): ["S15 schedule", "S15 schedule arrangement", "S15 timetable", "When does S15 start"] → (completely wrong — all asking about timing, same dimension repeated)

- **Enforce multi-dimensional perspectives (important)**: Must use the following **"thinking checklist"** to force queries into different angles:
    - **[Results/Prediction]**: User queries a process → they inevitably want results (e.g., match results, standings).
    - **[Comparison/Decision]**: Horizontal comparison (e.g., vs competitors, pros and cons analysis).
    - **[Cause/Depth]**: Why is it this way? (e.g., principles, background, origins).
    - **[Practical/Pitfalls]**: How to do it? (e.g., best practices, tutorials, solutions).

- **No dimension misalignment**: Do not generate "tutorials" for "S15 schedule" (e.g., "How to organize S15"); generate logically appropriate dimensions.

</rewrite_rules>

""".strip()

    class WebSearchInput(BaseModel):
        questions: list[str] = Field(
            description="Search query list (1-5), must follow query rewriting rules, ensuring independence, self-containment, and multi-dimensionality",
            min_length=1,
            max_length=5,
        )
        reason: str = Field(
            default="", description="Search rationale, express key information in minimal tokens, max 100 chars"
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
    async def web_search_func(questions: list[str], reason: str = "") -> dict:
        """Execute web search and return structured results.

        Returns: {"content": "...", "metadata": {...}}
        - content: Formatted text content (for the LLM)
        - metadata: Structured metadata (for business layer, e.g., citation collection)

        Results are processed via BM25 + reranker model, returning the most relevant content snippets.
        """
        from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools

        web_search = WebSearchTools(search_service_cfg, reranker_config=reranker_config)
        sources_metadata, formatted_context = await web_search.fast_search_with_questions(
            questions=questions,
            search_results_per_query=10,
            top_k=10,
        )

        from myrm_agent_harness.toolkits.web_search.citation_resolver import enrich_sources_with_resolved_urls

        sources_metadata = await enrich_sources_with_resolved_urls(sources_metadata)

        if formatted_context:
            from myrm_agent_harness.utils.context_format import wrap_with_external_sources_tag

            content = wrap_with_external_sources_tag(formatted_context, source="web_search")
        else:
            content = formatted_context

        sufficiency_metadata: dict[str, object] = {}

        if sufficiency_config and sufficiency_config.enabled and sufficiency_llm_config and content:
            from myrm_agent_harness.toolkits.retriever.sufficiency import evaluate_sufficiency

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
                "negative_constraint_violations": list(verdict.negative_constraint_violations),
            }

            if not verdict.is_sufficient and verdict.confidence >= sufficiency_config.confidence_threshold:
                guidance_parts: list[str] = []
                if verdict.missing_aspects:
                    guidance_parts.append(
                        "**Missing information**: " + "; ".join(verdict.missing_aspects)
                    )
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
                    notice = "\n\n---\n⚠️ **Retrieval Sufficiency Notice**: The search results may be incomplete.\n"
                    content += notice + "\n".join(guidance_parts)

        return {
            "content": content,
            "metadata": {
                "sources": sources_metadata,
                "search_queries": questions,
                "total_results": len(sources_metadata),
                **({"sufficiency": sufficiency_metadata} if sufficiency_metadata else {}),
            },
        }

    return web_search_func
