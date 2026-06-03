"""web_search 错误处理和边缘情况测试

测试未覆盖的关键错误处理路径和边缘情况
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from myrm_agent_harness.toolkits.web_search.common import SearchResult
from myrm_agent_harness.toolkits.web_search.error_handling import (
    build_search_error_context,
    is_retryable_search_error,
)
from myrm_agent_harness.toolkits.web_search.exceptions import SearchAPIError
from myrm_agent_harness.toolkits.web_search.web_searcher import SearchServiceConfig, WebSearcher


class _FakeAPIConnectionError(Exception):
    """Simulates LiteLLM's APIConnectionError(status=500) wrapper."""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(f"litellm.APIConnectionError: {message}")
        self.status_code = status_code


class TestErrorClassification:
    """测试错误分类逻辑"""

    def test_retryable_timeout_errors(self):
        """测试超时错误可重试"""
        assert is_retryable_search_error(TimeoutError())
        assert is_retryable_search_error(TimeoutError())

    def test_retryable_connection_errors(self):
        """测试连接错误可重试"""
        assert is_retryable_search_error(ConnectionError("Connection failed"))
        assert is_retryable_search_error(OSError("Network error"))

    def test_retryable_status_codes(self):
        """测试可重试的HTTP状态码"""
        for code in [408, 425, 429, 500, 502, 503, 504]:
            exc = Exception()
            exc.status_code = code
            assert is_retryable_search_error(exc), f"Status {code} should be retryable"

    def test_non_retryable_status_codes(self):
        """测试不可重试的HTTP状态码"""
        for code in [400, 401, 403, 404, 405, 422]:
            exc = Exception()
            exc.status_code = code
            assert not is_retryable_search_error(exc), f"Status {code} should not be retryable"

    def test_retryable_error_messages(self):
        """测试通过错误消息判断可重试"""
        test_cases = [
            "Rate limit exceeded (429)",
            "502 Bad Gateway",
            "Connection timeout",
            "Server timed out",
            "Connection refused",
            "Broken pipe error",
        ]
        for msg in test_cases:
            assert is_retryable_search_error(Exception(msg)), f"Message '{msg}' should be retryable"

    def test_http_status_attribute(self):
        """测试 http_status 属性"""
        exc = Exception()
        exc.http_status = 503
        assert is_retryable_search_error(exc)

    def test_quota_exceeded_not_retryable(self):
        """配额超限不可重试（即使 status=500）"""
        exc = _FakeAPIConnectionError(
            'TavilyException - {"detail":{"error":"This request exceeds your plan\'s set usage limit."}}'
        )
        assert not is_retryable_search_error(exc)

    def test_invalid_api_key_not_retryable(self):
        """无效 API key 不可重试"""
        exc = _FakeAPIConnectionError('TavilyException - {"detail":{"error":"Invalid API key"}}')
        assert not is_retryable_search_error(exc)

    def test_real_connection_refused_still_retryable(self):
        """真实连接拒绝仍可重试"""
        assert is_retryable_search_error(ConnectionError("Connection refused"))

    def test_apiconnectionerror_wrapper_not_matched_as_connection_error(self):
        """LiteLLM APIConnectionError 包装器不应被当作真实连接错误"""
        exc = _FakeAPIConnectionError("Something went wrong with the provider")
        # status=500 makes it retryable, but not because of "connection" keyword
        assert is_retryable_search_error(exc)  # retryable due to status=500


class TestErrorContext:
    """测试错误上下文构建"""

    def test_build_context_with_status_code(self):
        """测试带状态码的上下文"""
        exc = Exception("API error")
        exc.status_code = 429

        ctx = build_search_error_context(
            exc,
            query="test query",
            provider="tavily",
            attempt_index=0,
        )

        assert ctx.query == "test query"
        assert ctx.status_code == 429
        assert ctx.retryable is True
        assert ctx.metadata["provider"] == "tavily"
        assert ctx.metadata["attempt_index"] == "0"

    def test_build_context_with_response_body(self):
        """测试带响应体的上下文"""
        exc = Exception()
        exc.status_code = 400
        exc.response = "Invalid request: missing field 'query'"

        ctx = build_search_error_context(
            exc,
            query="test",
            provider="searxng",
            attempt_index=1,
            error_code="ValidationError",
        )

        assert ctx.response_body == "Invalid request: missing field 'query'"
        assert ctx.error_code == "ValidationError"
        assert ctx.retryable is False

    def test_build_context_with_body_attribute(self):
        """测试 body 属性"""
        exc = Exception()
        exc.body = "Error body content"

        ctx = build_search_error_context(
            exc,
            query="test",
            provider="test",
            attempt_index=0,
        )

        assert ctx.response_body == "Error body content"


class TestTimeoutHandling:
    """测试超时处理"""

    @pytest.mark.asyncio
    async def test_search_and_process_timeout(self):
        """测试 search_and_process 超时错误处理"""
        config = SearchServiceConfig(
            search_service="tavily",
            api_key="test_key",
        )
        searcher = WebSearcher(config)

        with patch.object(
            searcher,
            "search",
            side_effect=TimeoutError("Search timeout"),
        ):
            query, docs, error = await searcher.search_and_process("test", 5)

            assert query == "test"
            assert docs == []
            assert error is not None
            assert isinstance(error, SearchAPIError)
            assert "time budget" in error.message
            assert error.context.retryable is True
            assert error.context.error_code == "TimeoutError"


class TestLiteLLMSearchEdgeCases:
    """测试 LiteLLMSearch 边缘情况"""

    def test_result_parsing_with_all_fields(self):
        """测试带完整字段的结果解析"""
        mock_result = Mock()
        mock_result.title = "Test Article"
        mock_result.url = "https://example.com"
        mock_result.snippet = "Test snippet"
        mock_result.date = "2024-03-19"

        result_dict = {
            "title": mock_result.title if hasattr(mock_result, "title") else "",
            "link": mock_result.url if hasattr(mock_result, "url") else "",
            "snippet": mock_result.snippet if hasattr(mock_result, "snippet") else "",
        }
        if hasattr(mock_result, "date") and mock_result.date:
            result_dict["date"] = mock_result.date

        result = SearchResult.from_dict(result_dict)
        assert result.title == "Test Article"
        assert result.link == "https://example.com"
        assert result.date == "2024-03-19"

    def test_result_parsing_with_missing_attributes(self):
        """测试缺少属性的结果解析"""
        mock_result = Mock(spec=[])  # Empty spec, no attributes

        result_dict = {
            "title": mock_result.title if hasattr(mock_result, "title") else "",
            "link": mock_result.url if hasattr(mock_result, "url") else "",
            "snippet": mock_result.snippet if hasattr(mock_result, "snippet") else "",
        }

        result = SearchResult.from_dict(result_dict)
        assert result.title == " no Heading"
        assert result.link == ""
        assert result.snippet == ""


class TestSearchResultEdgeCases:
    """测试 SearchResult 边缘情况"""

    def test_from_dict_with_content_field(self):
        """测试使用 content 字段"""
        data = {
            "title": "Test",
            "link": "https://example.com",
            "content": "Content from content field",
        }
        result = SearchResult.from_dict(data)
        assert result.snippet == "Content from content field"

    def test_from_dict_with_text_field(self):
        """测试使用 text 字段"""
        data = {
            "title": "Test",
            "url": "https://example.com",
            "text": "Content from text field",
        }
        result = SearchResult.from_dict(data)
        assert result.link == "https://example.com"
        assert result.snippet == "Content from text field"

    def test_from_dict_no_title(self):
        """测试无标题情况"""
        data = {
            "link": "https://example.com",
            "snippet": "Test snippet",
        }
        result = SearchResult.from_dict(data)
        assert result.title == " no Heading"

    def test_from_dict_with_date(self):
        """测试带日期的结果"""
        data = {
            "title": "News",
            "link": "https://news.example.com",
            "snippet": "Breaking news",
            "date": "2024-03-19",
        }
        result = SearchResult.from_dict(data)
        assert result.date == "2024-03-19"

    def test_from_dict_with_engines(self):
        """测试带引擎信息的结果"""
        data = {
            "title": "Multi-engine result",
            "link": "https://example.com",
            "snippet": "Found by multiple engines",
            "engines": ["google", "bing"],
        }
        result = SearchResult.from_dict(data)
        assert result.engines == ["google", "bing"]


class TestExtractKeyError:
    """测试 _extract_key_error 语义优先错误提取"""

    @pytest.fixture()
    def searcher(self):
        config = SearchServiceConfig(search_service="tavily", api_key="test")
        return WebSearcher(config)

    def test_quota_exceeded(self, searcher: WebSearcher):
        exc = _FakeAPIConnectionError(
            'TavilyException - {"detail":{"error":"This request exceeds your plan\'s set usage limit."}}'
        )
        msg = searcher._extract_key_error(exc)
        assert "quota exceeded" in msg.lower()

    def test_invalid_api_key(self, searcher: WebSearcher):
        exc = _FakeAPIConnectionError('TavilyException - {"detail":{"error":"Invalid API key"}}')
        msg = searcher._extract_key_error(exc)
        assert "invalid api key" in msg.lower()

    def test_real_connection_refused(self, searcher: WebSearcher):
        exc = ConnectionError("Connection refused")
        msg = searcher._extract_key_error(exc)
        assert msg == "Cannot connect to search service"

    def test_rate_limit(self, searcher: WebSearcher):
        exc = Exception("Rate limit exceeded")
        msg = searcher._extract_key_error(exc)
        assert "rate limit" in msg.lower()

    def test_http_401(self, searcher: WebSearcher):
        exc = Exception("401 Unauthorized")
        msg = searcher._extract_key_error(exc)
        assert "authentication failed" in msg.lower()

    def test_fallback_to_default(self, searcher: WebSearcher):
        exc = Exception("Some unknown error happened")
        msg = searcher._extract_key_error(exc)
        assert "Exception:" in msg

    def test_apiconnectionerror_not_matched_as_connection_error(self, searcher: WebSearcher):
        """APIConnectionError 包装的未知错误不应返回 'Cannot connect'"""
        exc = _FakeAPIConnectionError("Something went wrong")
        msg = searcher._extract_key_error(exc)
        assert msg != "Cannot connect to search service"


class TestWebSearcherCacheLogLevel:
    """测试缓存日志级别"""

    @pytest.mark.asyncio
    async def test_cache_hit_uses_info_level(self):
        """测试缓存命中使用 INFO 级别日志"""
        config = SearchServiceConfig(
            search_service="tavily",
            api_key="test_key",
        )
        searcher = WebSearcher(config)

        mock_service = AsyncMock()
        mock_service.search.return_value = [
            SearchResult(
                title="Test",
                link="https://example.com",
                snippet="Test snippet",
            )
        ]

        with patch.object(searcher, "_get_search_service", return_value=mock_service):
            await searcher.search("test query", 5)

        with patch("myrm_agent_harness.toolkits.web_search.web_searcher.logger") as mock_logger:
            result = await searcher.search("test query", 5)

            assert len(result) == 1
            mock_logger.info.assert_called_once()
            call_args = mock_logger.info.call_args[0][0]
            assert "cache hit" in call_args.lower()


class TestFallbackProvider:
    """测试 Fallback Provider 功能"""

    def setup_method(self):
        """清理缓存，避免测试之间的状态污染"""
        from myrm_agent_harness.toolkits.web_search.web_searcher import _search_cache

        _search_cache.clear()

    @pytest.mark.asyncio
    async def test_primary_quota_exceeded_fallback_succeeds(self):
        """主服务配额超限，fallback 成功"""
        from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics

        fallback_cfg = SearchServiceConfig(search_service="perplexity", api_key="pplx-key")
        primary_cfg = SearchServiceConfig(
            search_service="tavily",
            api_key="tvly-key",
            fallback_config=fallback_cfg,
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(primary_cfg, metrics=metrics)

        primary_service = AsyncMock()
        primary_service.search.side_effect = _FakeAPIConnectionError(
            'TavilyException - {"detail":{"error":"This request exceeds your plan\'s set usage limit."}}'
        )

        fallback_service = AsyncMock()
        fallback_service.search.return_value = [
            SearchResult(title="Fallback", link="https://fallback.com", snippet="Fallback result")
        ]

        async def mock_get_service(instance, bypass_gateway=False):
            if instance.config.search_service == "tavily":
                return primary_service
            elif instance.config.search_service == "perplexity":
                return fallback_service
            return AsyncMock()

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            results = await searcher.search("test", 5)

        assert len(results) == 1
        assert results[0].title == "Fallback"
        assert metrics.fallback_triggered_count == 1
        assert metrics.fallback_successes == 1
        assert metrics.fallback_failures == 0

    @pytest.mark.asyncio
    async def test_primary_invalid_key_fallback_succeeds(self):
        """主服务无效 API key，fallback 成功"""
        from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics

        fallback_cfg = SearchServiceConfig(search_service="searxng", api_base="http://localhost:8081")
        primary_cfg = SearchServiceConfig(
            search_service="tavily",
            api_key="invalid-key",
            fallback_config=fallback_cfg,
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(primary_cfg, metrics=metrics)

        primary_service = AsyncMock()
        primary_service.search.side_effect = _FakeAPIConnectionError(
            'TavilyException - {"detail":{"error":"Invalid API key"}}'
        )

        fallback_service = AsyncMock()
        fallback_service.search.return_value = [
            SearchResult(title="SearxNG", link="https://example.com", snippet="SearxNG result")
        ]

        async def mock_get_service(instance, bypass_gateway=False):
            if instance.config.search_service == "tavily":
                return primary_service
            elif instance.config.search_service == "searxng":
                return fallback_service
            return AsyncMock()

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            results = await searcher.search("test", 5)

        assert len(results) == 1
        assert results[0].title == "SearxNG"
        assert metrics.fallback_triggered_count == 1
        assert metrics.fallback_successes == 1

    @pytest.mark.asyncio
    async def test_no_fallback_config_raises_error(self):
        """主服务失败且无 fallback 配置，正常抛出异常"""
        primary_cfg = SearchServiceConfig(search_service="tavily", api_key="tvly-key", fallback_config=None)
        searcher = WebSearcher(primary_cfg)

        primary_service = AsyncMock()
        primary_service.search.side_effect = _FakeAPIConnectionError(
            'TavilyException - {"detail":{"error":"This request exceeds your plan\'s set usage limit."}}'
        )

        with patch.object(searcher, "_get_search_service", return_value=primary_service):
            with pytest.raises(SearchAPIError, match="quota exceeded"):
                await searcher.search("test", 5)

    @pytest.mark.asyncio
    async def test_fallback_also_fails_raises_original_error(self):
        """主服务和 fallback 都失败，抛出原始错误"""
        from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics

        fallback_cfg = SearchServiceConfig(search_service="perplexity", api_key="pplx-key")
        primary_cfg = SearchServiceConfig(
            search_service="tavily",
            api_key="tvly-key",
            fallback_config=fallback_cfg,
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(primary_cfg, metrics=metrics)

        quota_error = _FakeAPIConnectionError(
            'TavilyException - {"detail":{"error":"This request exceeds your plan\'s set usage limit."}}'
        )

        service_mock = AsyncMock()
        service_mock.search.side_effect = quota_error

        async def mock_get_service(instance, bypass_gateway=False):
            return service_mock

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            with pytest.raises(SearchAPIError, match="quota exceeded"):
                await searcher.search("test", 5)

        assert metrics.fallback_triggered_count == 1
        assert metrics.fallback_successes == 0
        assert metrics.fallback_failures == 1

    @pytest.mark.asyncio
    async def test_retryable_error_does_not_trigger_fallback(self):
        """可重试错误在主服务上重试，不触发 fallback"""
        from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics

        fallback_cfg = SearchServiceConfig(search_service="perplexity", api_key="pplx-key")
        primary_cfg = SearchServiceConfig(
            search_service="tavily",
            api_key="tvly-key",
            search_max_retries=2,
            fallback_config=fallback_cfg,
        )
        metrics = WebSearchMetrics()
        searcher = WebSearcher(primary_cfg, metrics=metrics)

        primary_service = AsyncMock()
        primary_service.search.side_effect = TimeoutError("Request timed out")

        with patch.object(searcher, "_get_search_service", return_value=primary_service):
            with pytest.raises(SearchAPIError, match="timeout"):
                await searcher.search("test", 5)

        assert metrics.fallback_triggered_count == 0

    @pytest.mark.asyncio
    async def test_fallback_config_recursion_prevented(self):
        """防止 fallback 配置无限递归"""
        fallback_cfg = SearchServiceConfig(
            search_service="perplexity",
            api_key="pplx-key",
            fallback_config=SearchServiceConfig(search_service="exa_ai", api_key="exa-key"),
        )
        primary_cfg = SearchServiceConfig(
            search_service="tavily",
            api_key="tvly-key",
            fallback_config=fallback_cfg,
        )
        searcher = WebSearcher(primary_cfg)

        primary_service = AsyncMock()
        primary_service.search.side_effect = _FakeAPIConnectionError(
            '{"detail":{"error":"This request exceeds your plan\'s set usage limit."}}'
        )

        fallback_service = AsyncMock()
        fallback_service.search.return_value = [
            SearchResult(title="Success", link="https://example.com", snippet="Test")
        ]

        call_count = {"perplexity": 0, "exa_ai": 0}

        async def mock_get_service(instance, bypass_gateway=False):
            if instance.config.search_service == "tavily":
                return primary_service
            elif instance.config.search_service == "perplexity":
                call_count["perplexity"] += 1
                return fallback_service
            elif instance.config.search_service == "exa_ai":
                call_count["exa_ai"] += 1
                return AsyncMock()
            return AsyncMock()

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            results = await searcher.search("test", 5)

        assert len(results) == 1
        assert call_count["perplexity"] == 1
        assert call_count["exa_ai"] == 0

    @pytest.mark.asyncio
    async def test_fallback_results_cached(self):
        """fallback 返回的结果也会被缓存"""
        fallback_cfg = SearchServiceConfig(search_service="perplexity", api_key="pplx-key")
        primary_cfg = SearchServiceConfig(
            search_service="tavily",
            api_key="tvly-key",
            fallback_config=fallback_cfg,
        )
        searcher = WebSearcher(primary_cfg)

        primary_service = AsyncMock()
        primary_service.search.side_effect = _FakeAPIConnectionError(
            '{"detail":{"error":"This request exceeds your plan\'s set usage limit."}}'
        )

        fallback_service = AsyncMock()
        fallback_service.search.return_value = [
            SearchResult(title="Cached", link="https://cached.com", snippet="Cached result")
        ]

        async def mock_get_service(instance, bypass_gateway=False):
            if instance.config.search_service == "tavily":
                return primary_service
            elif instance.config.search_service == "perplexity":
                return fallback_service
            return AsyncMock()

        with patch.object(WebSearcher, "_get_search_service", mock_get_service):
            result1 = await searcher.search("cache-test-unique", 5)
            result2 = await searcher.search("cache-test-unique", 5)

        assert result1 == result2
        assert fallback_service.search.call_count == 1

    @pytest.mark.asyncio
    async def test_metrics_snapshot_includes_fallback_counters(self):
        """metrics snapshot 包含 fallback 计数器"""
        from myrm_agent_harness.toolkits.web_search.metrics import WebSearchMetrics

        metrics = WebSearchMetrics()
        metrics.record_fallback_triggered()
        metrics.record_fallback_success()

        snapshot = metrics.snapshot()
        assert "fallback_triggered_count" in snapshot
        assert "fallback_successes" in snapshot
        assert "fallback_failures" in snapshot
        assert snapshot["fallback_triggered_count"] == 1
        assert snapshot["fallback_successes"] == 1
        assert snapshot["fallback_failures"] == 0
