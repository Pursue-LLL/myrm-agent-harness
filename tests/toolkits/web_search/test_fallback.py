"""Priority provider chain tests."""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.web_search.core.common import SearchResult
from myrm_agent_harness.toolkits.web_search.core.exceptions import (
    AllQueriesFailedError,
    SearchAPIError,
)
from myrm_agent_harness.toolkits.web_search.providers.web_searcher import (
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

    def setup_method(self):
        from myrm_agent_harness.toolkits.web_search.coalescing.search_coalescing import (
            reset_search_coalescing_state_for_tests,
        )
        from myrm_agent_harness.toolkits.web_search.providers.chain import default_quota_tracker

        # The quota tracker is a process-wide singleton: a depleted provider marked by a sibling test would be
        # skipped here and the hop counts below would no longer describe the code under test.
        reset_search_coalescing_state_for_tests()
        default_quota_tracker.reset_all()

    @pytest.mark.asyncio
    async def test_chain_on_auth_error(self):
        cfg = _chain_config(
            SearchServiceConfig(search_service="tavily", api_key="invalid"),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        )
        searcher = WebSearcher(cfg)

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

        assert results == fallback_results
        mock_primary.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chain_hops_on_quota_error(self):
        cfg = _chain_config(
            SearchServiceConfig(search_service="tavily", api_key="key", search_max_retries=0),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        )
        searcher = WebSearcher(cfg)

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

        assert results == fallback_results
        mock_primary.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chain_hops_on_provider_outage(self):
        cfg = _chain_config(
            SearchServiceConfig(search_service="tavily", api_key="key", search_max_retries=0),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        )
        searcher = WebSearcher(cfg)

        mock_primary = AsyncMock()
        mock_primary.search = AsyncMock(side_effect=Exception("Connection timeout"))

        fallback_results = [SearchResult(link="https://fallback.com", title="Fallback", snippet="S")]

        async def mock_get_service(instance, bypass_gateway=False):
            if instance.config.search_service == "tavily":
                return mock_primary
            fb = AsyncMock()
            fb.search = AsyncMock(return_value=fallback_results)
            return fb

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            results = await searcher.search("chain_hops_on_outage_unique", num_results=5)

        assert results == fallback_results
        mock_primary.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_chain_fails_when_every_provider_is_down(self):
        cfg = _chain_config(
            SearchServiceConfig(search_service="tavily", api_key="key", search_max_retries=0),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        )
        searcher = WebSearcher(cfg)

        mock_down = AsyncMock()
        mock_down.search = AsyncMock(side_effect=Exception("Connection timeout"))

        with (
            patch.object(WebSearcher, "_get_search_service", return_value=mock_down),
            pytest.raises(AllQueriesFailedError),
        ):
            await searcher.search("chain_all_down_unique", num_results=5)

        # The head provider is tried once (no retries configured) and the backup after it, so both reached the service.
        assert mock_down.search.await_count >= 2

    @pytest.mark.asyncio
    async def test_no_chain_config(self):
        config = SearchServiceConfig(search_service="tavily", api_key="key")
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(side_effect=Exception("HTTP 429 Quota exceeded"))

        with patch.object(searcher, "_get_search_service", return_value=mock_service), pytest.raises(SearchAPIError):
            await searcher.search("no_chain_config_unique", num_results=5)

        mock_service.search.assert_awaited_once()

    def test_provider_chain_structure(self):
        chain = [
            SearchServiceConfig(search_service="tavily", api_key="key1"),
            SearchServiceConfig(search_service="searxng", api_base="http://127.0.0.1:8081"),
        ]
        primary = SearchServiceConfig(search_service="tavily", api_key="key1", provider_chain=chain)

        assert primary.provider_chain is not None
        assert len(primary.provider_chain) == 2
        assert primary.provider_chain[1].search_service == "searxng"
