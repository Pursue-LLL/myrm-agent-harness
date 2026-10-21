"""测试请求合并超时保护"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine


@pytest.mark.asyncio
async def test_coalescing_timeout_protection():
    """测试请求合并超时后重试"""
    engine = FetchEngine(coalescing_timeout=0.5)

    mock_doc = Document(page_content="test", metadata={})
    call_count = 0

    async def slow_crawl(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(2.0)
        return (mock_doc, None)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = slow_crawl

        # 启动两个并发请求
        task1 = asyncio.create_task(engine.crawl("https://example.com"))
        await asyncio.sleep(0.05)
        task2 = asyncio.create_task(engine.crawl("https://example.com"))

        results = await asyncio.gather(task1, task2, return_exceptions=True)

        # task1 应该超时并重试成功
        # task2 应该等待 task1 超时，然后重试成功
        assert results[0] is not None or results[1] is not None

        # 至少有一个成功
        successful = [r for r in results if isinstance(r, Document)]
        assert len(successful) >= 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_coalescing_no_timeout_when_fast():
    """测试快速请求不触发超时"""
    engine = FetchEngine(coalescing_timeout=2.0)

    mock_doc = Document(page_content="test", metadata={})

    async def fast_crawl(url: str, **kwargs):
        await asyncio.sleep(0.01)
        return (mock_doc, None)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = fast_crawl

        # 100 个并发请求
        results = await asyncio.gather(*[engine.crawl("https://example.com") for _ in range(100)])

        # 所有请求都应该成功
        assert all(r is not None for r in results)
        assert len(results) == 100

        # 只调用了 1 次（请求合并生效）
        assert mock_crawl.call_count == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_coalescing_timeout_removes_future():
    """测试超时后 future 被正确移除"""
    engine = FetchEngine(coalescing_timeout=0.2)

    call_count = 0

    async def hang_then_succeed(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            await asyncio.sleep(1.0)
        return (Document(page_content=f"call_{call_count}", metadata={}), None)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = hang_then_succeed

        # 第一个请求会超时
        task1 = asyncio.create_task(engine.crawl("https://example.com"))
        await asyncio.sleep(0.05)

        # 第二个请求等待第一个
        task2 = asyncio.create_task(engine.crawl("https://example.com"))

        results = await asyncio.gather(task1, task2, return_exceptions=True)

        # 至少有一个成功
        successful = [r for r in results if isinstance(r, Document)]
        assert len(successful) >= 1

        # 验证 pending_requests 已清空
        assert len(engine._pending_requests) == 0

    await engine.shutdown()
