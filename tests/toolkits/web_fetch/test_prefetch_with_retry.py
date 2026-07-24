"""测试 prefetch_with_retry 的重试逻辑"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType, FetchResult


@pytest.mark.asyncio
async def test_prefetch_with_retry_success_first_attempt():
    """测试第一次尝试就成功"""
    engine = FetchEngine(cache_ttl=3600)

    result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={},
        fetcher_type=FetcherType.HTTP,
    )
    doc = Document(page_content="content", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (doc, result)

        success, failed = await engine.prefetch_with_retry(["https://example.com"])

        assert len(success) == 1
        assert len(failed) == 0
        assert success[0][0] == "https://example.com"
        assert mock_crawl.call_count == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_with_retry_success_after_retries():
    """测试重试后成功"""
    engine = FetchEngine(cache_ttl=3600)

    result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={},
        fetcher_type=FetcherType.HTTP,
    )
    doc = Document(page_content="content", metadata={})

    call_count = 0

    async def flaky_crawl(url: str, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Temporary network error")
        return (doc, result)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = flaky_crawl

        success, failed = await engine.prefetch_with_retry(["https://example.com"], max_retries=3, initial_backoff=0.05)

        assert len(success) == 1
        assert len(failed) == 0
        assert call_count == 3

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_with_retry_exhausted():
    """测试重试耗尽后失败"""
    engine = FetchEngine(cache_ttl=3600)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = ConnectionError("Persistent network error")

        success, failed = await engine.prefetch_with_retry(["https://example.com"], max_retries=2, initial_backoff=0.05)

        assert len(success) == 0
        assert len(failed) == 1
        assert failed[0][0] == "https://example.com"
        assert mock_crawl.call_count == 3  # 1 initial + 2 retries

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_with_retry_exponential_backoff():
    """测试指数退避策略"""
    engine = FetchEngine(cache_ttl=3600)

    call_times = []

    async def track_time_crawl(url: str, **kwargs):
        call_times.append(asyncio.get_event_loop().time())
        raise ConnectionError("Network error")

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = track_time_crawl

        await engine.prefetch_with_retry(["https://example.com"], max_retries=2, initial_backoff=0.1)

        assert len(call_times) == 3
        # 验证退避时间：第1次和第2次间隔 ~0.1s，第2次和第3次间隔 ~0.2s
        interval_1 = call_times[1] - call_times[0]
        interval_2 = call_times[2] - call_times[1]

        assert 0.08 < interval_1 < 0.20  # 允许一定误差
        assert 0.18 < interval_2 < 0.35

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_with_retry_multiple_urls():
    """测试批量预热（部分成功，部分失败）"""
    engine = FetchEngine(cache_ttl=3600)

    result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={},
        fetcher_type=FetcherType.HTTP,
    )
    doc = Document(page_content="content", metadata={})

    async def selective_crawl(url: str, **kwargs):
        if "success" in url:
            return (doc, result)
        raise ConnectionError("Network error")

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = selective_crawl

        success, failed = await engine.prefetch_with_retry(
            [
                "https://example.com/success1",
                "https://example.com/fail1",
                "https://example.com/success2",
            ],
            max_retries=1,
            initial_backoff=0.05,
        )

        assert len(success) == 2
        assert len(failed) == 1
        assert success[0][0] == "https://example.com/success1"
        assert success[1][0] == "https://example.com/success2"
        assert failed[0][0] == "https://example.com/fail1"

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_with_retry_concurrency():
    """测试并发预热"""
    engine = FetchEngine(cache_ttl=3600)

    result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={},
        fetcher_type=FetcherType.HTTP,
    )
    doc = Document(page_content="content", metadata={})

    call_times = []
    call_lock = asyncio.Lock()

    async def track_concurrent_crawl(url: str, **kwargs):
        async with call_lock:
            call_times.append(asyncio.get_event_loop().time())
        await asyncio.sleep(0.1)  # 模拟网络延迟
        return (doc, result)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = track_concurrent_crawl

        start = asyncio.get_event_loop().time()
        success, failed = await engine.prefetch_with_retry(
            [f"https://example.com/page{i}" for i in range(10)],
            max_retries=0,
            max_concurrency=10,
        )
        elapsed = asyncio.get_event_loop().time() - start

        assert len(success) == 10
        assert len(failed) == 0

        # 验证并发：10 个请求应该在 ~0.1s 内完成（而非 1s）
        assert elapsed < 0.3  # 允许一定误差

        # 验证所有请求几乎同时开始（时间差 < 150ms）
        if len(call_times) > 1:
            time_spread = max(call_times) - min(call_times)
            assert time_spread < 0.15

    await engine.shutdown()


@pytest.mark.asyncio
async def test_prefetch_with_retry_concurrency_limit():
    """测试并发限制"""
    engine = FetchEngine(cache_ttl=3600)

    result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={},
        fetcher_type=FetcherType.HTTP,
    )
    doc = Document(page_content="content", metadata={})

    active_count = 0
    max_active = 0
    lock = asyncio.Lock()

    async def track_concurrency(url: str, **kwargs):
        nonlocal active_count, max_active
        async with lock:
            active_count += 1
            max_active = max(max_active, active_count)

        await asyncio.sleep(0.05)

        async with lock:
            active_count -= 1

        return (doc, result)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = track_concurrency

        success, _failed = await engine.prefetch_with_retry(
            [f"https://example.com/page{i}" for i in range(20)],
            max_retries=0,
            max_concurrency=5,
        )

        assert len(success) == 20
        assert max_active <= 5  # 不超过并发限制

    await engine.shutdown()
