"""测试缓存键规范化对命中率的提升"""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine


@pytest.mark.asyncio
async def test_cache_hit_with_tracking_params():
    """测试带追踪参数的 URL 能命中缓存"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 第一次请求
        await engine.crawl("https://example.com/page?id=123")
        assert mock_crawl.call_count == 1

        # 第二次请求带追踪参数，应该命中缓存
        await engine.crawl("https://example.com/page?id=123&utm_source=google")
        assert mock_crawl.call_count == 1  # 仍然是 1，命中缓存

        # 验证缓存指标
        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_cache_hit_with_case_difference():
    """测试大小写不同的 URL 能命中缓存"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 第一次请求
        await engine.crawl("https://example.com/page")
        assert mock_crawl.call_count == 1

        # 第二次请求大小写不同，应该命中缓存
        await engine.crawl("HTTPS://EXAMPLE.COM/page")
        assert mock_crawl.call_count == 1

        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_cache_hit_with_default_port():
    """测试带默认端口的 URL 能命中缓存"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 第一次请求
        await engine.crawl("https://example.com/page")
        assert mock_crawl.call_count == 1

        # 第二次请求带默认端口，应该命中缓存
        await engine.crawl("https://example.com:443/page")
        assert mock_crawl.call_count == 1

        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_cache_hit_with_query_param_order():
    """测试查询参数顺序不同的 URL 能命中缓存"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 第一次请求
        await engine.crawl("https://example.com/page?a=1&z=3")
        assert mock_crawl.call_count == 1

        # 第二次请求参数顺序不同，应该命中缓存
        await engine.crawl("https://example.com/page?z=3&a=1")
        assert mock_crawl.call_count == 1

        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1

    await engine.shutdown()
