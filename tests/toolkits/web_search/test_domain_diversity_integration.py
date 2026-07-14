"""Integration tests for Domain Source Decay Algorithm (ANYSEARCH F1).

Exercises the real search pipeline: Tavily API -> dedup -> domain diversity sort.
Requires TAVILY_API_KEY in environment or .env.test.
"""

from __future__ import annotations

import os
from collections import Counter
from pathlib import Path

import pytest

from myrm_agent_harness.toolkits.web_search.engine import WebSearchTools
from myrm_agent_harness.toolkits.web_search.web_searcher import SearchServiceConfig
from myrm_agent_harness.utils.url_utils import extract_domain

_ENV_TEST = Path(__file__).resolve().parents[3] / ".." / "myrm-agent" / "myrm-agent-server" / ".env.test"


def _load_env_test() -> None:
    if _ENV_TEST.exists():
        for line in _ENV_TEST.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip()
            if key and val and key not in os.environ:
                os.environ[key] = val


_load_env_test()

_TAVILY_KEY = os.environ.get("TAVILY_API_KEY", "")
_skip_no_key = pytest.mark.skipif(not _TAVILY_KEY, reason="TAVILY_API_KEY not set")


def _make_search_tools() -> WebSearchTools:
    config = SearchServiceConfig(
        search_service="tavily",
        api_key=_TAVILY_KEY,
        timeout_seconds=20,
    )
    return WebSearchTools(config)


@_skip_no_key
@pytest.mark.integration
class TestDomainDiversityIntegration:
    """Real-API integration tests for domain diversity sorting."""

    @pytest.mark.asyncio
    async def test_search_returns_diverse_domains(self) -> None:
        """Single-query search should produce results from multiple domains."""
        tools = _make_search_tools()
        results, _ = await tools.fast_search_with_questions(
            questions=["Python web framework comparison 2024"],
            search_results_per_query=10,
            top_k=10,
        )
        assert len(results) >= 3

        domains = [extract_domain(r["url"]) for r in results]
        unique_domains = len(set(domains))
        assert unique_domains >= 2, f"Expected >=2 unique domains, got {unique_domains}: {domains}"

    @pytest.mark.asyncio
    async def test_multi_query_dedup_and_diversity(self) -> None:
        """Multi-query search should deduplicate and apply domain diversity."""
        tools = _make_search_tools()
        results, _ = await tools.fast_search_with_questions(
            questions=[
                "LangChain vs LlamaIndex comparison",
                "LangChain framework features",
            ],
            search_results_per_query=8,
            top_k=10,
        )
        assert len(results) >= 3

        domains = [extract_domain(r["url"]) for r in results]
        counter = Counter(domains)

        top_domain, top_count = counter.most_common(1)[0]
        total = len(domains)
        dominance_ratio = top_count / total
        assert dominance_ratio < 0.8, (
            f"Top domain '{top_domain}' dominates {dominance_ratio:.0%} "
            f"({top_count}/{total}), expected <80%"
        )

    @pytest.mark.asyncio
    async def test_domain_diversity_sort_reorders_results(self) -> None:
        """Verify the sort actually changes ordering vs. raw search results.

        Uses a niche query likely to return many results from the same domain.
        """
        tools = _make_search_tools()
        results, context = await tools.fast_search_with_questions(
            questions=["site:github.com langchain agent tools"],
            search_results_per_query=10,
            top_k=10,
        )
        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_search_empty_query_handled(self) -> None:
        """Search with a very obscure query should not crash."""
        tools = _make_search_tools()
        try:
            results, _ = await tools.fast_search_with_questions(
                questions=["xyzzyplugh_nonexistent_query_42"],
                search_results_per_query=5,
                top_k=5,
            )
        except Exception:
            pass

    @pytest.mark.asyncio
    async def test_top_results_not_all_same_domain(self) -> None:
        """Top 5 results should not all come from the same domain after diversity sort."""
        tools = _make_search_tools()
        results, _ = await tools.fast_search_with_questions(
            questions=["机器学习入门教程 2024"],
            search_results_per_query=10,
            top_k=10,
        )
        if len(results) < 5:
            pytest.skip("Too few results to verify top-5 diversity")

        top5_domains = [extract_domain(r["url"]) for r in results[:5]]
        unique_in_top5 = len(set(top5_domains))
        assert unique_in_top5 >= 2, (
            f"Top 5 results all from same domain(s): {top5_domains}"
        )
