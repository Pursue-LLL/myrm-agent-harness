"""Fallback Provider功能测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.exceptions import SearchAPIError
from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics
from myrm_agent_harness.toolkits.web_search.web_searcher import SearchServiceConfig, WebSearcher


class TestFallbackProvider:
    """测试Fallback Provider功能"""

    @pytest.mark.asyncio
    async def test_fallback_on_auth_error(self):
        """测试认证失败时触发fallback"""
        fallback_config = SearchServiceConfig(search_service="searxng")
        primary_config = SearchServiceConfig(
            search_service="tavily",
            api_key="invalid",
            fallback_config=fallback_config,
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(primary_config, metrics=metrics)

        mock_primary = AsyncMock()
        mock_primary.search = AsyncMock(side_effect=Exception("HTTP 401 Unauthorized"))

        fallback_results = [SearchResult(link="https://fallback.com", title="Fallback", snippet="S")]

        with patch.object(searcher, "_get_search_service", return_value=mock_primary):
            mock_fb = MagicMock()
            mock_fb.search = AsyncMock(return_value=fallback_results)

            with patch("myrm_agent_harness.toolkits.web_search.web_searcher.WebSearcher", return_value=mock_fb):
                results = await searcher.search("fallback_auth_unique_456", num_results=5)

                assert len(results) == 1
                snap = metrics.snapshot()
                assert snap["fallback_triggered_count"] == 1
                assert snap["fallback_successes"] == 1

    @pytest.mark.asyncio
    async def test_no_fallback_when_retryable_error(self):
        """测试可重试错误不触发fallback"""
        fallback_config = SearchServiceConfig(search_service="searxng")
        primary_config = SearchServiceConfig(
            search_service="tavily",
            api_key="key",
            fallback_config=fallback_config,
            search_max_retries=0,
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(primary_config, metrics=metrics)

        mock_primary = AsyncMock()
        mock_primary.search = AsyncMock(side_effect=Exception("Connection timeout"))

        with patch.object(searcher, "_get_search_service", return_value=mock_primary):
            with pytest.raises(SearchAPIError):
                await searcher.search("no_fallback_retryable_unique", num_results=5)

            snap = metrics.snapshot()
            assert snap["fallback_triggered_count"] == 0

    @pytest.mark.asyncio
    async def test_no_fallback_config(self):
        """测试无fallback配置时正常失败"""
        config = SearchServiceConfig(search_service="tavily", api_key="key")
        metrics = WebSearchMetrics()
        searcher = WebSearcher(config, metrics=metrics)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(side_effect=Exception("HTTP 429 Quota exceeded"))

        with patch.object(searcher, "_get_search_service", return_value=mock_service):
            with pytest.raises(SearchAPIError):
                await searcher.search("no_fallback_config_unique", num_results=5)

            snap = metrics.snapshot()
            assert snap["fallback_triggered_count"] == 0

    def test_fallback_config_structure(self):
        """测试fallback配置结构"""
        fallback = SearchServiceConfig(search_service="searxng")
        primary = SearchServiceConfig(search_service="tavily", api_key="key", fallback_config=fallback)

        assert primary.fallback_config is not None
        assert primary.fallback_config.search_service == "searxng"
        assert primary.fallback_config.fallback_config is None

    def test_nested_fallback_config(self):
        """测试多层fallback配置"""
        level2 = SearchServiceConfig(search_service="exa_ai", api_key="key2")
        level1 = SearchServiceConfig(search_service="searxng", fallback_config=level2)
        primary = SearchServiceConfig(search_service="tavily", api_key="key1", fallback_config=level1)

        assert primary.fallback_config.search_service == "searxng"
        assert primary.fallback_config.fallback_config.search_service == "exa_ai"
