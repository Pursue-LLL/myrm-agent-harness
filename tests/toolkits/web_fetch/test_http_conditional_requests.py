"""测试 HTTP 条件请求（ETag / Last-Modified）"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType, FetchResult


@pytest.mark.asyncio
async def test_cache_fresh_no_validation():
    """测试缓存未过期时直接返回，不发送验证请求"""
    engine = CrawlEngine(cache_ttl=10)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={"url": "https://example.com"})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (first_doc, first_result)

        # 第一次请求
        doc1 = await engine.crawl("https://example.com")
        assert doc1 is not None
        assert doc1.page_content == "content"
        assert mock_crawl.call_count == 1

        # 第二次请求（缓存未过期，直接返回，不发验证请求）
        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert doc2.page_content == "content"
        assert mock_crawl.call_count == 1  # 仍然只调用了 1 次

    await engine.shutdown()


@pytest.mark.asyncio
async def test_cache_expired_sends_conditional_request():
    """测试缓存过期时发送条件请求（304 复用缓存）"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=False)

    # 第一次请求：返回完整内容 + ETag
    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={"url": "https://example.com"})

    # 第二次请求：返回 304
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
        assert doc1.page_content == "content"
        assert mock_crawl.call_count == 1

        # 等待缓存过期
        await asyncio.sleep(1.1)

        # 第二次请求（缓存过期，发送条件请求）
        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert doc2.page_content == "content"  # 复用缓存（304）
        assert mock_crawl.call_count == 2  # 发送了验证请求

        # 验证第二次调用传递了 ETag
        call_kwargs = mock_crawl.call_args_list[1][1]
        assert call_kwargs.get("etag") == "abc123"

    await engine.shutdown()


@pytest.mark.asyncio
async def test_cache_expired_content_changed():
    """测试缓存过期且内容变更时更新缓存（200 响应）"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=False)

    # 第一次请求
    first_result = FetchResult(
        html="<html><body>old content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="old content", metadata={})

    # 第二次请求：内容更新
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

        # 等待缓存过期
        await asyncio.sleep(1.1)

        # 第二次请求（缓存过期，发送条件请求，内容变更返回新内容）
        doc2 = await engine.crawl("https://example.com")
        assert doc2.page_content == "new content"

        # 验证第二次调用传递了旧 ETag
        call_kwargs = mock_crawl.call_args_list[1][1]
        assert call_kwargs.get("etag") == "abc123"

    await engine.shutdown()


@pytest.mark.asyncio
async def test_last_modified_validation():
    """测试缓存过期时使用 Last-Modified 验证"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=False)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    second_result = FetchResult(
        html="",
        url="https://example.com",
        status_code=304,
        headers={},
        fetcher_type=FetcherType.HTTP,
    )

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.side_effect = [(first_doc, first_result), (None, second_result)]

        # 第一次请求
        doc1 = await engine.crawl("https://example.com")
        assert doc1 is not None

        # 等待缓存过期
        await asyncio.sleep(1.1)

        # 第二次请求（缓存过期，发送条件请求）
        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert doc2.page_content == "content"

        # 验证第二次调用传递了 Last-Modified
        call_kwargs = mock_crawl.call_args_list[1][1]
        assert call_kwargs.get("last_modified") == "Mon, 01 Jan 2024 00:00:00 GMT"

    await engine.shutdown()


@pytest.mark.asyncio
async def test_cache_expired_no_validation_headers():
    """测试缓存过期但无验证头时返回过期缓存"""
    engine = CrawlEngine(cache_ttl=1, stale_while_revalidate=False)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (first_doc, first_result)

        # 第一次请求
        doc1 = await engine.crawl("https://example.com")
        assert doc1 is not None

        # 等待缓存过期
        await asyncio.sleep(1.1)

        # 第二次请求（缓存过期但无验证头，返回过期缓存）
        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert mock_crawl.call_count == 1  # 仍然只调用了 1 次（返回过期缓存）

    await engine.shutdown()


@pytest.mark.asyncio
async def test_cache_fresh_with_validation_headers():
    """测试缓存未过期时，即使有验证头也不发送请求"""
    engine = CrawlEngine(cache_ttl=10)

    first_result = FetchResult(
        html="<html><body>content</body></html>",
        url="https://example.com",
        status_code=200,
        headers={"etag": "abc123", "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
        fetcher_type=FetcherType.HTTP,
    )
    first_doc = Document(page_content="content", metadata={})

    with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
        mock_crawl.return_value = (first_doc, first_result)

        # 第一次请求
        doc1 = await engine.crawl("https://example.com")
        assert doc1 is not None

        # 第二次请求（缓存未过期，直接返回）
        doc2 = await engine.crawl("https://example.com")
        assert doc2 is not None
        assert mock_crawl.call_count == 1  # 只调用了 1 次

    await engine.shutdown()
