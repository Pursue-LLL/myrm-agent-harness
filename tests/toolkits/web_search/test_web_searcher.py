"""web_searcher 模块测试

测试 WebSearcher 的核心搜索功能
"""

from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.core.config.gateway import ToolGatewayConfig
from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.exceptions import (
    AllQueriesFailedError,
    ErrorContext,
    SearchAPIError,
    SearchConfigError,
)
from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics
from myrm_agent_harness.toolkits.web_search.web_searcher import (
    SearchServiceConfig,
    WebSearcher,
)


class TestSearchServiceConfig:
    """测试搜索服务配置"""

    def test_basic_config(self):
        """测试基本配置"""
        config = SearchServiceConfig(
            search_service="tavily",
            api_key="test_key",
        )
        assert config.search_service == "tavily"
        assert config.api_key == "test_key"

    def test_searxng_config(self):
        """测试SearxNG配置"""
        config = SearchServiceConfig(
            search_service="searxng",
            api_base="http://localhost:8081",
        )
        assert config.search_service == "searxng"
        assert config.api_base == "http://localhost:8081"

    def test_config_with_extra_params(self):
        """测试额外参数"""
        config = SearchServiceConfig(
            search_service="tavily",
            api_key="key",
            extra_params={"categories": ["general"], "language": "en"},
        )
        assert config.extra_params["categories"] == ["general"]

    def test_config_mutable(self):
        """测试配置可运行时修改"""
        config = SearchServiceConfig(search_service="tavily", api_key="key")
        # 配置应该可以修改（移除了 frozen=True）
        config.search_service = "exa_ai"
        assert config.search_service == "exa_ai"

    def test_config_defaults(self):
        """测试默认值"""
        config = SearchServiceConfig(search_service="tavily", api_key="key")
        assert config.timeout_seconds == 20
        assert config.api_base is None
        assert config.extra_params is None
        assert config.search_max_retries == 2
        assert config.retry_backoff_base_seconds == 0.5
        assert config.retry_backoff_max_seconds == 8.0
        assert config.total_timeout_seconds is None

    def test_config_with_gateway(self):
        """测试网关配置"""
        gateway_config = ToolGatewayConfig(use_gateway=True, gateway_url="http://gw", auth_token="token")
        config = SearchServiceConfig(
            search_service="tavily",
            gateway_config=gateway_config,
        )
        assert config.gateway_config is not None
        assert config.gateway_config.use_gateway is True
        assert config.gateway_config.gateway_url == "http://gw"
        assert config.gateway_config.auth_token == "token"


class TestWebSearcherInit:
    """测试WebSearcher初始化"""

    def test_init_with_config(self):
        """测试使用配置初始化"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        assert searcher.config == config
        assert searcher._search_service is None

    def test_init_searxng(self):
        """测试SearxNG初始化"""
        config = SearchServiceConfig(search_service="searxng")
        searcher = WebSearcher(config)

        assert searcher.config.search_service == "searxng"


class TestWebSearcherGetService:
    """测试搜索服务获取"""

    @pytest.mark.asyncio
    async def test_get_service_tavily(self):
        """测试获取Tavily服务"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        service = await searcher._get_search_service()

        assert service is not None
        assert searcher._search_service is service

    @pytest.mark.asyncio
    async def test_get_service_cached(self):
        """测试服务缓存"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        service1 = await searcher._get_search_service()
        service2 = await searcher._get_search_service()

        # 应该返回同一个实例
        assert service1 is service2

    @pytest.mark.asyncio
    async def test_get_service_searxng_with_url(self):
        """测试SearxNG服务获取（带URL）"""
        config = SearchServiceConfig(
            search_service="searxng",
            api_base="http://localhost:8081",
        )
        searcher = WebSearcher(config)

        service = await searcher._get_search_service()
        assert service is not None

    @pytest.mark.asyncio
    async def test_get_service_searxng_requires_api_base(self):
        """SearxNG without api_base raises SearchConfigError (no env fallback)."""
        config = SearchServiceConfig(search_service="searxng")
        searcher = WebSearcher(config)

        with pytest.raises(SearchConfigError, match="api_base"):
            await searcher._get_search_service()

    @pytest.mark.asyncio
    async def test_get_service_missing_api_key(self):
        """测试其他服务缺少API key时报错"""
        config = SearchServiceConfig(search_service="tavily")
        searcher = WebSearcher(config)

        with pytest.raises(SearchConfigError, match="requires API key"):
            await searcher._get_search_service()

    @pytest.mark.asyncio
    async def test_get_service_with_gateway(self):
        """测试使用网关时的服务获取"""
        gateway_config = ToolGatewayConfig(use_gateway=True, gateway_url="http://gw", auth_token="token")
        config = SearchServiceConfig(
            search_service="tavily",
            gateway_config=gateway_config,
        )
        searcher = WebSearcher(config)

        service = await searcher._get_search_service()
        assert service is not None
        assert searcher.config.gateway_config.use_gateway is True
        # The underlying service should have its api_base and api_key overridden
        # We can test this by checking the service's internal state if accessible,
        # but since it's an interface, we just ensure it doesn't raise SearchConfigError for missing api_key.


class TestWebSearcherSearch:
    """测试基本搜索功能"""

    @pytest.mark.asyncio
    async def test_search_basic(self):
        """测试基本搜索"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        # Mock搜索服务
        mock_service = AsyncMock()
        mock_results = [
            SearchResult(link="https://test.com", title="Test", snippet="Snippet"),
        ]
        mock_service.search = AsyncMock(return_value=mock_results)

        with patch.object(searcher, "_get_search_service", return_value=mock_service):
            results = await searcher.search("unique test query basic", num_results=5)

            assert len(results) == 1
            assert results[0].link == "https://test.com"
            mock_service.search.assert_called_once()

    @pytest.mark.asyncio
    async def test_search_with_num_results(self):
        """测试指定结果数量"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(return_value=[])
        searcher._search_service = mock_service

        await searcher.search("unique_query_123", num_results=10)

        # 验证search被调用
        assert mock_service.search.call_count == 1

    @pytest.mark.asyncio
    async def test_search_with_extra_params(self):
        """测试额外参数传递"""
        config = SearchServiceConfig(
            search_service="searxng",
            extra_params={"categories": ["general"], "language": "zh"},
        )
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(return_value=[])
        searcher._search_service = mock_service

        await searcher.search("query")

        # 验证extra_params被传递
        call_args = mock_service.search.call_args
        assert "categories" in call_args[1]


class TestWebSearcherRetryAndErrors:
    """重试、结构化错误与指标"""

    @pytest.mark.asyncio
    async def test_retry_then_success(self):
        """可重试错误后成功应触发一次退避并最终成功"""
        config = SearchServiceConfig(
            search_service="tavily", api_key="test_key", search_max_retries=2
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(config, metrics=metrics)
        mock_service = AsyncMock()
        ok = [SearchResult(link="https://ok.com", title="OK", snippet="S")]
        mock_service.search = AsyncMock(
            side_effect=[Exception("503 Service Unavailable"), ok]
        )
        searcher._search_service = mock_service

        unique_q = f"retry_ok_{id(searcher)}"
        results = await searcher.search(unique_q, num_results=5)

        assert len(results) == 1
        assert mock_service.search.call_count == 2
        snap = metrics.snapshot()
        assert snap["search_retry_scheduled"] == 1
        assert snap["search_successes"] == 1
        assert snap["search_terminal_failures"] == 0

    @pytest.mark.asyncio
    async def test_search_api_error_includes_context(self):
        """不可重试错误应立即失败并携带 ErrorContext"""
        config = SearchServiceConfig(
            search_service="tavily", api_key="test_key", search_max_retries=0
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(config, metrics=metrics)
        mock_service = AsyncMock()
        mock_service.search = AsyncMock(side_effect=Exception("HTTP 401 Unauthorized"))
        searcher._search_service = mock_service

        with pytest.raises(SearchAPIError) as exc_info:
            await searcher.search(f"auth_fail_{id(searcher)}", 5)

        assert exc_info.value.context.query is not None
        assert exc_info.value.context.retryable is False
        assert metrics.snapshot()["search_terminal_failures"] == 1

    @pytest.mark.asyncio
    async def test_all_queries_failed_primary_context(self):
        """全部查询失败时应填充 failed_queries 与 primary_context"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        async def fake_process(
            q: str, n: int, override: dict[str, str] | None = None
        ) -> tuple[str, list, Exception | None]:
            ctx = ErrorContext(
                query=q, error_code="TestErr", metadata={"provider": "tavily"}
            )
            return q, [], SearchAPIError("failed", context=ctx)

        with patch.object(
            searcher,
            "search_and_process",
            new_callable=AsyncMock,
            side_effect=fake_process,
        ), pytest.raises(AllQueriesFailedError) as exc_info:
            await searcher.multi_query_parallel_search(["a", "b"], 5)

        assert len(exc_info.value.failed_queries) == 2
        assert exc_info.value.primary_context is not None
        assert exc_info.value.primary_context.query == "a"


class TestWebSearcherMultiQuery:
    """测试多查询并行搜索"""

    @pytest.mark.asyncio
    async def test_multi_query_parallel(self):
        """测试并行搜索多个查询"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        # Mock搜索服务
        mock_service = AsyncMock()
        mock_service.search = AsyncMock(
            side_effect=[
                [
                    SearchResult(
                        link="https://test1.com", title="R1", content="C1", snippet="S1"
                    )
                ],
                [
                    SearchResult(
                        link="https://test2.com", title="R2", content="C2", snippet="S2"
                    )
                ],
            ]
        )
        searcher._search_service = mock_service

        results = await searcher.multi_query_parallel_search(
            queries=["query1", "query2"],
            results_per_query=5,
        )

        # 返回格式是 [(query, docs, error), ...]
        assert len(results) == 2

        # 解包元组
        query1, docs1, err1 = results[0]
        query2, docs2, err2 = results[1]

        # 验证查询和错误
        assert query1 == "query1"
        assert query2 == "query2"
        assert err1 is None
        assert err2 is None

        # 验证文档列表
        assert len(docs1) == 1
        assert len(docs2) == 1
        assert docs1[0].metadata["url"] == "https://test1.com"
        assert docs2[0].metadata["url"] == "https://test2.com"

    @pytest.mark.asyncio
    async def test_multi_query_empty_list(self):
        """测试空查询列表"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        # 空查询列表应该抛出异常
        with pytest.raises(AllQueriesFailedError, match="no queries were executed"):
            await searcher.multi_query_parallel_search(queries=[], results_per_query=5)

    @pytest.mark.asyncio
    async def test_multi_query_with_exception(self):
        """测试并行搜索中某个查询失败"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        # 使用唯一查询避免缓存
        unique_q1 = f"success_query_{id(searcher)}"
        unique_q2 = f"fail_query_{id(searcher)}"

        # Mock一个成功一个失败
        mock_service = AsyncMock()
        mock_service.search = AsyncMock(
            side_effect=[
                [
                    SearchResult(
                        link="https://test1.com", title="R1", content="C1", snippet="S1"
                    )
                ],
                Exception("Search failed"),
            ]
        )
        searcher._search_service = mock_service

        results = await searcher.multi_query_parallel_search(
            queries=[unique_q1, unique_q2],
            results_per_query=5,
        )

        # 返回格式是 [(query, docs, error), ...]
        assert len(results) == 2
        # 验证有一个成功一个失败
        errors = [r[2] for r in results]
        assert errors.count(None) == 1  # 一个成功
        assert sum(1 for e in errors if e is not None) == 1  # 一个失败


class TestWebSearcherCache:
    """测试搜索缓存"""

    @pytest.mark.asyncio
    async def test_cache_hit_skips_network(self):
        """Cache hit must skip the network call entirely."""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_results = [
            SearchResult(
                link="https://cached.com", title="Cached", content="C", snippet="S"
            )
        ]
        mock_service.search = AsyncMock(return_value=mock_results)
        searcher._search_service = mock_service

        unique_query = f"cache_test_query_{id(searcher)}"

        results1 = await searcher.search(unique_query, num_results=5)
        results2 = await searcher.search(unique_query, num_results=5)

        assert results1 == results2
        assert (
            mock_service.search.call_count == 1
        ), "Second call should hit cache, not network"

    @pytest.mark.asyncio
    async def test_cache_miss_different_query(self):
        """测试不同查询不命中缓存"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(
            side_effect=[
                [
                    SearchResult(
                        link="https://r1.com", title="R1", content="C1", snippet="S1"
                    )
                ],
                [
                    SearchResult(
                        link="https://r2.com", title="R2", content="C2", snippet="S2"
                    )
                ],
            ]
        )
        searcher._search_service = mock_service

        # 使用唯一查询避免全局缓存冲突
        unique_q1 = f"unique_query_1_{id(searcher)}"
        unique_q2 = f"unique_query_2_{id(searcher)}"

        await searcher.search(unique_q1)
        await searcher.search(unique_q2)

        # 应该调用两次API
        assert mock_service.search.call_count == 2


class TestWebSearcherIntegration:
    """集成测试"""

    @pytest.mark.asyncio
    async def test_full_search_flow(self):
        """测试完整搜索流程"""
        config = SearchServiceConfig(
            search_service="tavily",
            api_key="test_key",
            timeout_seconds=30,
            extra_params={"search_depth": "advanced"},
        )
        searcher = WebSearcher(config)

        # Mock完整搜索流程
        mock_service = AsyncMock()
        mock_results = [
            SearchResult(
                link="https://python.org",
                title="Python",
                content="Python is a programming language.",
                snippet="Python intro",
            ),
        ]
        mock_service.search = AsyncMock(return_value=mock_results)
        searcher._search_service = mock_service

        results = await searcher.search("python programming", num_results=5)

        assert len(results) == 1
        assert results[0].title == "Python"

    @pytest.mark.asyncio
    async def test_multi_query_to_documents(self):
        """测试多查询转文档流程"""
        config = SearchServiceConfig(search_service="tavily", api_key="test_key")
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search = AsyncMock(
            side_effect=[
                [
                    SearchResult(
                        link="https://r1.com", title="R1", content="C1", snippet="S1"
                    )
                ],
                [
                    SearchResult(
                        link="https://r2.com", title="R2", content="C2", snippet="S2"
                    )
                ],
            ]
        )
        searcher._search_service = mock_service

        results = await searcher.multi_query_parallel_search(
            ["q1", "q2"], results_per_query=5
        )

        # 返回格式是 [(query, docs, error), ...]
        assert len(results) == 2
        assert results[0][0] == "q1"
        assert results[1][0] == "q2"
        assert len(results[0][1]) >= 1  # docs
        assert len(results[1][1]) >= 1
