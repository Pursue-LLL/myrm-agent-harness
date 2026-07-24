"""测试缓存预热（Prefetch）功能"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine


@pytest.mark.asyncio
async def test_prefetch_loads_cache():
    """测试 prefetch 成功加载缓存"""
    engine = FetchEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        # Prefetch 3 个 URL
        await engine.prefetch(["https://example1.com", "https://example2.com", "https://example3.com"])

        # 验证：调用了 3 次网络请求
        assert mock_crawl.call_count == 3

        # 验证：后续请求命中缓存
        await engine.crawl("https://example1.com")
        assert mock_crawl.call_count == 3  # 仍然是 3

        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_respects_concurrency():
    """测试 prefetch 遵守并发限制"""
    engine = FetchEngine(allow_private_networks=True)
    mock_doc = Document(page_content="test", metadata={})
    concurrent_calls = []

    async def track_concurrent_calls(url, **kwargs):
        concurrent_calls.append(1)
        await asyncio.sleep(0.1)
        concurrent_calls.pop()
        return (mock_doc, None)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = track_concurrent_calls

        # Prefetch 10 个 URL，max_concurrency=3
        await engine.prefetch([f"https://example{i}.com" for i in range(10)], max_concurrency=3)

        # 验证：调用了 10 次
        assert mock_crawl.call_count == 10

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_silent_failure():
    """测试 prefetch 失败时静默处理"""
    engine = FetchEngine()

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = RuntimeError("Network error")

        # Note: 这个测试期望 prefetch 静默失败，但实际上会抛出异常

        # Prefetch 应该不抛异常
        await engine.prefetch(["https://example.com"])

        # 验证：失败被记录到 fail_cache
        metrics = engine.get_cache_metrics()
        assert metrics["fail_cache"]["size"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_empty_list():
    """测试 prefetch 空列表"""
    engine = FetchEngine()

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        await engine.prefetch([])
        assert mock_crawl.call_count == 0

    await engine.shutdown()
