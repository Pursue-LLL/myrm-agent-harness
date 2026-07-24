"""Regression gate: preserve mid-tier-tuned web_search tool description."""

from __future__ import annotations

from myrm_agent_harness.agent.streaming.model_discipline import (
    resolve_execution_discipline,
)
from myrm_agent_harness.toolkits.web_search.engine import SearchServiceConfig
from myrm_agent_harness.toolkits.web_search.web_search_agent_tools import (
    create_web_search_tool,
)

GOLDEN_SEARCH_INTENTS: tuple[str, ...] = (
    "Python 3.12 vs 3.11 feature comparison 2025",
    "OpenAI latest product release announcement",
    "Bitcoin price today USD",
    "Rust ecosystem adoption 2026",
    "League of Legends S15 schedule results",
    "Next.js 15 performance issues fix",
    "DeepSeek-V3 benchmark vs GPT-4",
    "EU AI Act compliance deadline 2025",
    "Apple M4 MacBook release date specs",
    "PostgreSQL 17 new features migration",
    "Tesla Cybertruck delivery wait time 2025",
    "Kubernetes 1.31 release notes breaking changes",
    "Claude 3.5 Sonnet API pricing per token",
    "React 19 stable release date features",
    "AWS Lambda Python 3.13 runtime availability",
    "Google Gemini 2.0 flash context window",
    "NVIDIA H200 GPU availability price",
    "Stripe Connect platform fee structure 2025",
    "Open source LLM license comparison Apache MIT",
    "Cloudflare Workers AI pricing free tier limits",
)


class TestWebSearchDescriptionBaseline:
    def test_golden_intent_catalog_has_twenty_entries(self) -> None:
        assert len(GOLDEN_SEARCH_INTENTS) == 20

    def test_tool_description_retains_mid_tier_rewrite_rules(self) -> None:
        tool = create_web_search_tool(
            search_service_cfg=SearchServiceConfig(
                search_service="tavily", api_key="test-key"
            ),
        )
        description = tool.description or ""
        assert "Query Rewriting Rules" in description
        assert "rewrite_rules" in description
        assert "Aggregation and Decomposition" in description

    def test_rewrite_rules_not_in_execution_discipline(self) -> None:
        from unittest.mock import MagicMock

        from langchain_core.language_models import BaseChatModel

        llm = MagicMock(spec=BaseChatModel)
        llm.model_name = "gpt-4o"
        discipline = resolve_execution_discipline(llm)
        assert "Query Rewriting Rules" not in discipline
        assert "<rewrite_rules>" not in discipline
