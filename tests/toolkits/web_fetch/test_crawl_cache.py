"""CrawlEngine 缓存功能测试"""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine

SSRF_BYPASS = patch(
    "myrm_agent_harness.utils.url_utils.validate_url_for_ssrf",
    return_value=(True, None),
)


@pytest.mark.asyncio
async def test_cache_hit_and_miss():
    """测试缓存命中和未命中"""
    engine = CrawlEngine()
    mock_doc = Document(page_content="test", metadata={"url": "https://example.com"})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        doc1 = await engine.crawl("https://example.com")
        assert doc1 is not None
        assert mock_crawl.call_count == 1

        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert mock_crawl.call_count == 1

        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1
        assert metrics["crawl_cache"]["size"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_force_refresh():
    """测试强制刷新"""
    engine = CrawlEngine()
    mock_doc = Document(page_content="test", metadata={"url": "https://example.com"})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        await engine.crawl("https://example.com")
        assert mock_crawl.call_count == 1

        await engine.crawl("https://example.com", force_refresh=True)
        assert mock_crawl.call_count == 2

    await engine.shutdown()


@pytest.mark.asyncio
async def test_fail_cache():
    """测试失败缓存"""
    engine = CrawlEngine()

    with SSRF_BYPASS, patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (None, None)

        doc1 = await engine.crawl("https://fail.example.com")
        assert doc1 is None
        assert mock_crawl.call_count == 1

        doc2 = await engine.crawl("https://fail.example.com")
        assert doc2 is None
        assert mock_crawl.call_count == 1

        metrics = engine.get_cache_metrics()
        assert metrics["fail_cache"]["size"] == 1

    await engine.shutdown()


@pytest.mark.asyncio
async def test_custom_cache_config():
    """测试自定义缓存配置"""
    engine = CrawlEngine(cache_ttl=7200, cache_maxsize=1000)

    assert engine._crawl_cache.ttl == 7200
    assert engine._crawl_cache.maxsize == 1000

    await engine.shutdown()


@pytest.mark.asyncio
async def test_crawl_many_with_cache():
    """测试批量爬取的缓存行为"""
    engine = CrawlEngine()
    mock_doc = Document(page_content="test", metadata={})

    with SSRF_BYPASS, patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        urls = ["https://example.com", "https://example.com", "https://test.com"]
        success, failed = await engine.crawl_many(urls)

        assert len(success) == 3
        assert len(failed) == 0
        assert mock_crawl.call_count == 2

        metrics = engine.get_cache_metrics()
        assert metrics["crawl_cache"]["hits"] == 1
        assert metrics["crawl_cache"]["size"] == 2

    await engine.shutdown()


@pytest.mark.asyncio
async def test_crawl_many_force_refresh():
    """测试批量爬取的强制刷新"""
    engine = CrawlEngine()
    mock_doc = Document(page_content="test", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (mock_doc, None)

        await engine.crawl("https://example.com")
        assert mock_crawl.call_count == 1

        urls = ["https://example.com"]
        await engine.crawl_many(urls, force_refresh=True)
        assert mock_crawl.call_count == 2

    await engine.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
