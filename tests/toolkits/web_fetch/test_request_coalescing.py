"""测试请求合并（Request Coalescing）功能"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine


@pytest.mark.asyncio
async def test_concurrent_requests_coalescing():
    """测试并发请求合并：10 个协程同时 crawl 同一 URL，只发起 1 次网络调用"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test content", metadata={"url": "https://example.com"})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 10 个协程并发请求同一 URL
        results = await asyncio.gather(*[engine.crawl("https://example.com") for _ in range(10)])

        # 验证：只调用了 1 次网络请求
        assert mock_crawl.call_count == 1, f"Expected 1 call, got {mock_crawl.call_count}"

        # 验证：所有协程都得到了结果
        assert len(results) == 10
        assert all(r is not None for r in results)
        assert all(r.page_content == "test content" for r in results)

    await engine.shutdown()


@pytest.mark.asyncio
async def test_coalescing_with_different_urls():
    """测试不同 URL 不会被合并"""
    engine = FetchEngine()
    mock_doc1 = Document(page_content="content1", metadata={})
    mock_doc2 = Document(page_content="content2", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = [(mock_doc1, None), (mock_doc2, None)]

        # 2 个不同 URL 并发请求
        results = await asyncio.gather(
            engine.crawl("https://example1.com"),
            engine.crawl("https://example2.com"),
        )

        # 验证：调用了 2 次网络请求
        assert mock_crawl.call_count == 2
        assert results[0].page_content == "content1"
        assert results[1].page_content == "content2"

    await engine.shutdown()


@pytest.mark.asyncio
async def test_coalescing_exception_propagation():
    """测试请求合并时异常正确传播到所有等待者"""
    engine = FetchEngine()

    async def mock_crawl_with_delay(url, **kwargs):
        """模拟真实网络延迟，确保所有协程都能注册到 future"""
        await asyncio.sleep(0.05)
        raise RuntimeError("Network error")

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = mock_crawl_with_delay

        # 10 个协程并发请求同一 URL
        tasks = [engine.crawl("https://example.com") for _ in range(10)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 验证：只调用了 1 次网络请求
        assert mock_crawl.call_count == 1

        # 验证：所有协程都收到了异常
        assert len(results) == 10
        exceptions = [r for r in results if isinstance(r, Exception)]
        assert len(exceptions) == 10, f"Expected 10 exceptions, got {len(exceptions)}"

        # 所有异常都是 RuntimeError 且消息相同
        assert all(isinstance(e, RuntimeError) for e in exceptions)
        assert all(str(e) == "Network error" for e in exceptions)

    await engine.shutdown()


@pytest.mark.asyncio
async def test_coalescing_with_force_refresh():
    """测试 force_refresh 不触发请求合并"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 第一个请求正常
        await engine.crawl("https://example.com")
        assert mock_crawl.call_count == 1

        # 第二个请求 force_refresh，不等待缓存，直接发起新请求
        await engine.crawl("https://example.com", force_refresh=True)
        assert mock_crawl.call_count == 2

    await engine.shutdown()


@pytest.mark.asyncio
async def test_coalescing_sequential_requests():
    """测试顺序请求不触发合并（第二个请求应该命中缓存）"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 第一个请求
        await engine.crawl("https://example.com")
        assert mock_crawl.call_count == 1

        # 第二个请求应该命中缓存，不触发网络调用
        await engine.crawl("https://example.com")
        assert mock_crawl.call_count == 1  # 仍然是 1

        # 验证缓存指标
        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_coalescing_high_concurrency():
    """测试高并发场景（100 个协程）"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # 100 个协程并发请求同一 URL
        results = await asyncio.gather(*[engine.crawl("https://example.com") for _ in range(100)])

        # 验证：只调用了 1 次网络请求
        assert mock_crawl.call_count == 1, f"Expected 1 call, got {mock_crawl.call_count}"

        # 验证：所有协程都得到了结果
        assert len(results) == 100
        assert all(r is not None for r in results)

    await engine.shutdown()
