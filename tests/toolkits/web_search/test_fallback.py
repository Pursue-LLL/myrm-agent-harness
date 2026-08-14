"""Priority provider chain tests."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.exceptions import (
    AllQueriesFailedError,
    SearchAPIError,
)
from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics
from myrm_agent_harness.toolkits.web_search.web_searcher import (
    SearchServiceConfig,
    WebSearcher,
)


def _chain_config(*hops: SearchServiceConfig) -> SearchServiceConfig:
    head = hops[0]
    return SearchServiceConfig(
        search_service=head.search_service,
        api_key=head.api_key,
        api_base=head.api_base,
        provider_chain=list(hops),
    )


class TestProviderChain:
    """测试 provider chain 故障转移"""

    @pytest.mark.asyncio
    async def test_chain_on_auth_error(self):
        cfg = _chain_config(
            SearchServiceConfig(search_service="tavily", api_key="invalid"),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(cfg, metrics=metrics)

        mock_primary = AsyncMock()
        mock_primary.search = AsyncMock(side_effect=Exception("HTTP 401 Unauthorized"))

        fallback_results = [SearchResult(link="https://fallback.com", title="Fallback", snippet="S")]

        async def mock_get_service(instance, bypass_gateway=False):
            if instance.config.search_service == "tavily":
                return mock_primary
            fb = AsyncMock()
            fb.search = AsyncMock(return_value=fallback_results)
            return fb

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            results = await searcher.search("fallback_auth_unique_456", num_results=5)

        assert len(results) == 1
        assert metrics.chain_hop_count >= 1

    @pytest.mark.asyncio
    async def test_chain_hops_on_quota_error(self):
        cfg = _chain_config(
            SearchServiceConfig(search_service="tavily", api_key="key", search_max_retries=0),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(cfg, metrics=metrics)

        mock_primary = AsyncMock()
        mock_primary.search = AsyncMock(side_effect=Exception("API Error [10406]: quota exhausted"))

        fallback_results = [SearchResult(link="https://fallback.com", title="Fallback", snippet="S")]

        async def mock_get_service(instance, bypass_gateway=False):
            if instance.config.search_service == "tavily":
                return mock_primary
            fb = AsyncMock()
            fb.search = AsyncMock(return_value=fallback_results)
            return fb

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            results = await searcher.search("quota_hop_unique", num_results=5)

        assert len(results) == 1
        assert metrics.chain_hop_count >= 1

    @pytest.mark.asyncio
    async def test_no_chain_advance_on_retryable_error(self):
        cfg = _chain_config(
            SearchServiceConfig(search_service="tavily", api_key="key", search_max_retries=0),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(cfg, metrics=metrics)

        mock_primary = AsyncMock()
        mock_primary.search = AsyncMock(side_effect=Exception("Connection timeout"))

        with (
            patch.object(WebSearcher, "_get_search_service", return_value=mock_primary),
            pytest.raises(AllQueriesFailedError),
        ):
            await searcher.search("no_chain_retryable_unique", num_results=5)

        assert metrics.chain_hop_count == 0

    @pytest.mark.asyncio
    async def test_no_chain_config(self):
        config = SearchServiceConfig(search_service="tavily", api_key="key")
        metrics = WebSearchMetrics()
        searcher = WebSearcher(config, metrics=metrics)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(side_effect=Exception("HTTP 429 Quota exceeded"))

        with patch.object(searcher, "_get_search_service", return_value=mock_service), pytest.raises(SearchAPIError):
            await searcher.search("no_chain_config_unique", num_results=5)

        assert metrics.chain_hop_count == 0

    def test_provider_chain_structure(self):
        chain = [
            SearchServiceConfig(search_service="tavily", api_key="key1"),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        ]
        primary = SearchServiceConfig(search_service="tavily", api_key="key1", provider_chain=chain)

        assert primary.provider_chain is not None
        assert len(primary.provider_chain) == 2
        assert primary.provider_chain[1].search_service == "searxng"
