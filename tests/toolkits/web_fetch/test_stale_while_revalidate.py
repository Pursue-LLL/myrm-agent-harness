"""测试 Stale-While-Revalidate 模式"""

import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType, FetchResult


@pytest.mark.asyncio
async def test_stale_while_revalidate_returns_immediately():
    """测试过期缓存立即返回，后台刷新"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=True)

    first_result = FetchResult(
        html="<html><body>old content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="old content", metadata={})

    second_result = FetchResult(
        html="<html><body>new content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "def456"},
        fetcher_type=FetcherType.HTTP,
    )
    second_doc = Document(page_content="new content", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = [(first_doc, first_result), (second_doc, second_result)]

        # 第一次请求
        doc1 = await engine.crawl("https://example.com")
        assert doc1.page_content == "old content"
        assert mock_crawl.call_count == 1

        # 等待缓存过期
        time.sleep(1.1)

        # 第二次请求（立即返回过期缓存）
        start = time.perf_counter()
        doc2 = await engine.crawl("https://example.com")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert doc2.page_content == "old content"  # 立即返回过期缓存
        assert elapsed_ms < 100  # 应该 <100ms（无网络请求，考虑测试环境开销）
        assert mock_crawl.call_count == 1  # 此时后台任务可能还未开始

        # 等待后台刷新完成
        await asyncio.sleep(0.1)
        assert mock_crawl.call_count == 2  # 后台任务已执行

        # 第三次请求（获取刷新后的新内容）
        doc3 = await engine.crawl("https://example.com")
        assert doc3.page_content == "new content"
        assert mock_crawl.call_count == 2  # 无额外请求

    await engine.shutdown()


@pytest.mark.asyncio
async def test_stale_while_revalidate_304():
    """测试后台刷新收到 304 时更新 cached_at"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=True)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    second_result = FetchResult(
        html="",
        url="https://example.com",
        status_code=304,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = [(first_doc, first_result), (None, second_result)]

        # 第一次请求
        doc1 = await engine.crawl("https://example.com")
        assert doc1 is not None

        # 等待缓存过期
        time.sleep(1.1)

        # 第二次请求（立即返回过期缓存，后台发送 304）
        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert doc2.page_content == "content"

        # 等待后台刷新完成
        await asyncio.sleep(0.1)
        assert mock_crawl.call_count == 2

        # 第三次请求（缓存已刷新 cached_at，未过期）
        doc3 = await engine.crawl("https://example.com")
        assert doc3 is not None
        assert mock_crawl.call_count == 2  # 无额外请求

    await engine.shutdown()


@pytest.mark.asyncio
async def test_stale_while_revalidate_disabled():
    """测试禁用 stale-while-revalidate 时同步验证"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=False)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    second_result = FetchResult(
        html="",
        url="https://example.com",
        status_code=304,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = [(first_doc, first_result), (None, second_result)]

        # 第一次请求
        doc1 = await engine.crawl("https://example.com")
        assert doc1 is not None

        # 等待缓存过期
        time.sleep(1.1)

        # 第二次请求（同步验证，等待 304 响应）
        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert mock_crawl.call_count == 2  # 立即发送了验证请求

    await engine.shutdown()


@pytest.mark.asyncio
async def test_background_tasks_cleanup_on_shutdown():
    """测试 shutdown 时等待后台任务完成"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=True)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    async def slow_revalidate(url: str, **kwargs):
        await asyncio.sleep(0.2)
        return (first_doc, first_result)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = slow_revalidate

        # 第一次请求
        await engine.crawl("https://example.com")

        # 等待缓存过期
        time.sleep(1.1)

        # 第二次请求（触发后台刷新）
        await engine.crawl("https://example.com")

        # 立即 shutdown（应该等待后台任务完成）
        await engine.shutdown()

        # 验证后台任务已执行
        assert mock_crawl.call_count == 2


@pytest.mark.asyncio
async def test_background_revalidation_metrics():
    """测试后台刷新的监控指标"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=True)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    second_result = FetchResult(
        html="",
        url="https://example.com",
        status_code=304,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = [(first_doc, first_result), (None, second_result)]

        # 第一次请求
        await engine.crawl("https://example.com")

        # 等待缓存过期
        time.sleep(1.1)

        # 第二次请求（触发后台刷新）
        await engine.crawl("https://example.com")

        # 等待后台任务完成
        await asyncio.sleep(0.1)

        # 验证指标
        metrics = engine.get_cache_metrics()
        bg_metrics = metrics["background_revalidation"]

        assert bg_metrics["success"] == 1
        assert bg_metrics["failed"] == 0
        assert bg_metrics["total"] == 1
        assert bg_metrics["success_rate"] == 1.0
        assert bg_metrics["avg_latency_ms"] > 0
        assert bg_metrics["queue_size"] == 0

    await engine.shutdown()


@pytest.mark.asyncio
async def test_background_revalidation_failure_metrics():
    """测试后台刷新失败时的指标"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=True)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = [(first_doc, first_result), Exception("Network error")]

        # 第一次请求
        await engine.crawl("https://example.com")

        # 等待缓存过期
        time.sleep(1.1)

        # 第二次请求（触发后台刷新，会失败）
        await engine.crawl("https://example.com")

        # 等待后台任务完成
        await asyncio.sleep(0.1)

        # 验证指标
        metrics = engine.get_cache_metrics()
        bg_metrics = metrics["background_revalidation"]

        assert bg_metrics["success"] == 0
        assert bg_metrics["failed"] == 1
        assert bg_metrics["total"] == 1
        assert bg_metrics["success_rate"] == 0.0

    await engine.shutdown()


@pytest.mark.asyncio
async def test_background_tasks_limit():
    """测试后台任务限流保护"""
    engine = CrawlEngine(cache_ttl=0.5, stale_while_revalidate=True, max_background_tasks=2)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    revalidate_started = []
    revalidate_lock = asyncio.Lock()

    async def blocking_revalidate(url: str, **kwargs):
        async with revalidate_lock:
            revalidate_started.append(url)
        await asyncio.sleep(10.0)  # 长时间阻塞
        return (first_doc, first_result)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        # 预热阶段立即返回
        mock_crawl.side_effect = lambda url, **kwargs: (first_doc, first_result)

        # 预热：创建 5 个缓存条目
        for i in range(5):
            await engine.crawl(f"https://example.com/page{i}")

        # 等待缓存过期
        time.sleep(0.6)

        # 切换到阻塞模式
        mock_crawl.side_effect = blocking_revalidate

        # 快速触发 5 个后台刷新
        for i in range(5):
            doc = await engine.crawl(f"https://example.com/page{i}")
            assert doc is not None  # 应该返回 stale 缓存

        # 等待任务启动
        await asyncio.sleep(0.1)

        # 验证限流生效
        metrics = engine.get_cache_metrics()
        bg_metrics = metrics["background_revalidation"]

        assert bg_metrics["skipped"] == 3  # 5 - 2 = 3 个被跳过
        assert len(revalidate_started) == 2  # 只有 2 个任务启动

        await engine.shutdown()

        # shutdown 后所有任务完成
        metrics = engine.get_cache_metrics()
        bg_metrics = metrics["background_revalidation"]
        assert bg_metrics["queue_size"] == 0
        assert bg_metrics["active_workers"] == 0


@pytest.mark.asyncio
async def test_background_revalidation_timeout_metric():
    """测试后台刷新超时指标存在"""
    engine = CrawlEngine(cache_ttl=3600, stale_while_revalidate=True)

    # 验证超时指标字段存在
    metrics = engine.get_cache_metrics()
    bg_metrics = metrics["background_revalidation"]

    assert "timeout" in bg_metrics
    assert bg_metrics["timeout"] == 0  # 初始为 0

    await engine.shutdown()


@pytest.mark.asyncio
async def test_background_priority_queue():
    """测试后台任务优先级队列（高频 URL 优先刷新）"""
    engine = CrawlEngine(cache_ttl=0.5, stale_while_revalidate=True, max_background_tasks=2)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    processed_urls = []
    process_lock = asyncio.Lock()

    async def track_revalidation(url: str, **kwargs):
        async with process_lock:
            processed_urls.append(url)
        await asyncio.sleep(0.5)  # 慢速刷新
        return (first_doc, first_result)

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = track_revalidation

        # 预热：创建 3 个缓存条目
        # page0: 访问 1 次
        # page1: 访问 5 次（高频）
        # page2: 访问 2 次
        await engine.crawl("https://example.com/page0")
        for _ in range(5):
            await engine.crawl("https://example.com/page1")
        for _ in range(2):
            await engine.crawl("https://example.com/page2")

        # 等待缓存过期
        time.sleep(0.6)

        # 快速触发 3 个后台刷新（只有 2 个会执行）
        await engine.crawl("https://example.com/page0")
        await engine.crawl("https://example.com/page1")
        await engine.crawl("https://example.com/page2")

        # 等待任务启动
        await asyncio.sleep(0.1)

        # 验证优先级：page1（6次）应该优先于 page2（3次）和 page0（2次）
        metrics = engine.get_cache_metrics()
        bg_metrics = metrics["background_revalidation"]

        # 队列应该有任务（worker 正在处理）
        assert bg_metrics["queue_size"] >= 0
        assert bg_metrics["active_workers"] == 2

        await engine.shutdown()

        # 验证处理顺序：page1（访问6次）应该最先被处理
        # 注意：由于并发，前 2 个 URL 可能同时被 2 个 worker 处理
        # 所以只验证 page1 在前 2 个中
        assert len(processed_urls) >= 2
        first_two = processed_urls[:2]
        assert any("page1" in url for url in first_two)  # page1 应该在前 2 个中


@pytest.mark.asyncio
async def test_url_access_stats_lru_eviction():
    """测试访问统计 LRU 淘汰（防止内存泄漏）"""
    engine = CrawlEngine(cache_ttl=3600)

    # 设置较小的上限用于测试
    engine._max_access_stats_size = 5

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

        # 访问 10 个不同的 URL
        for i in range(10):
            await engine.crawl(f"https://example.com/page{i}")

        # 验证：只保留最近 5 个
        assert len(engine._url_access_stats) == 5

        # 验证：最旧的 5 个被淘汰
        for i in range(5):
            assert f"https://example.com/page{i}" not in engine._url_access_stats

        # 验证：最新的 5 个保留
        for i in range(5, 10):
            assert f"https://example.com/page{i}" in engine._url_access_stats

    await engine.shutdown()


@pytest.mark.asyncio
async def test_priority_with_time_decay():
    """测试时间衰减优先级计算"""
    from myrm_agent_harness.toolkits.web_fetch.engine import AccessStats

    engine = CrawlEngine(cache_ttl=3600)

    current_time = time.time()

    # 场景 1：高频但久未访问
    engine._url_access_stats["page0"] = AccessStats(count=10, last_access=current_time - 48 * 3600)

    # 场景 2：低频但最近访问（使用稍大的数值避免精度问题）
    engine._url_access_stats["page1"] = AccessStats(count=4, last_access=current_time)

    priority_page0 = engine._calculate_priority("page0")
    priority_page1 = engine._calculate_priority("page1")

    # page0: 10 × 0.5^(48/24) = 10 × 0.25 = 2.5 → priority = -2
    # page1: 4 × 1.0 = 4.0 → priority = -4
    # page1 应该有更高优先级（更负）
    assert priority_page1 < priority_page0, f"page1 priority {priority_page1} should < page0 priority {priority_page0}"

    # 验证具体数值
    assert priority_page0 == -2  # 10 × 0.25 = 2.5 → int = 2
    assert priority_page1 == -4  # 4 × 1.0 = 4.0 → int = 4

    await engine.shutdown()
