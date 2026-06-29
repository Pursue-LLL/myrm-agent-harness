"""SSRF protection tests for deep_crawl auxiliary HTTP fetches."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.web_fetch.deep_crawl import DeepCrawlPipeline
from myrm_agent_harness.toolkits.web_fetch.robots_parser import RobotsParser, RobotsRules


@pytest.mark.asyncio
async def test_robots_parser_uses_secure_get_and_returns_empty_on_ssrf_block() -> None:
    with patch(
        "myrm_agent_harness.toolkits.web_fetch.robots_parser.secure_get",
        new=AsyncMock(side_effect=SSRFSecurityError("Blocked IP")),
    ) as mock_get:
        parser = RobotsParser()
        rules = await parser._fetch_robots("http://169.254.169.254/robots.txt")

    mock_get.assert_awaited_once_with("http://169.254.169.254/robots.txt", timeout=10.0)
    assert rules.disallowed == []
    assert rules.allowed == []
    assert rules.crawl_delay is None
    assert rules.sitemaps == []


@pytest.mark.asyncio
async def test_deep_crawl_parse_sitemap_uses_secure_get_and_returns_empty_on_ssrf_block() -> None:
    pipeline = DeepCrawlPipeline(
        store=MagicMock(),
        executor=MagicMock(),
        engine=MagicMock(),
        robots_parser=RobotsParser(),
        rate_limiter=MagicMock(),
        data_dir=Path("/tmp/test_crawl"),
    )

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.deep_crawl.secure_get",
        new=AsyncMock(side_effect=SSRFSecurityError("Blocked IP")),
    ) as mock_get:
        urls = await pipeline._parse_sitemap(
            "http://169.254.169.254/sitemap.xml",
            "https://example.com",
            RobotsRules([], [], None, []),
            limit=10,
        )

    mock_get.assert_awaited_once_with("http://169.254.169.254/sitemap.xml", timeout=15.0)
    assert urls == []


@pytest.mark.asyncio
async def test_deep_crawl_parse_sitemap_parses_secure_response() -> None:
    pipeline = DeepCrawlPipeline(
        store=MagicMock(),
        executor=MagicMock(),
        engine=MagicMock(),
        robots_parser=RobotsParser(),
        rate_limiter=MagicMock(),
        data_dir=Path("/tmp/test_crawl"),
    )
    body = (
        '<?xml version="1.0"?><urlset>'
        "<loc>https://example.com/docs</loc>"
        "</urlset>"
    )
    mock_response = httpx.Response(200, text=body, request=httpx.Request("GET", "https://example.com/sitemap.xml"))

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.deep_crawl.secure_get",
        new=AsyncMock(return_value=mock_response),
    ):
        urls = await pipeline._parse_sitemap(
            "https://example.com/sitemap.xml",
            "https://example.com",
            RobotsRules([], [], None, []),
            limit=10,
        )

    assert urls == ["https://example.com/docs"]


class TestDeepCrawlValidation:
    def test_is_valid_crawl_url_same_origin(self) -> None:
        pipeline = DeepCrawlPipeline(
            store=MagicMock(),
            executor=MagicMock(),
            engine=MagicMock(),
            robots_parser=RobotsParser(),
            rate_limiter=MagicMock(),
            data_dir=Path("/tmp/test_crawl"),
        )
        rules = RobotsRules([], [], None, [])
        assert pipeline._is_valid_crawl_url("https://example.com/docs", "https://example.com", rules) is True

    def test_is_valid_crawl_url_rejects_other_origin(self) -> None:
        pipeline = DeepCrawlPipeline(
            store=MagicMock(),
            executor=MagicMock(),
            engine=MagicMock(),
            robots_parser=RobotsParser(),
            rate_limiter=MagicMock(),
            data_dir=Path("/tmp/test_crawl"),
        )
        rules = RobotsRules([], [], None, [])
        assert pipeline._is_valid_crawl_url("https://evil.com/docs", "https://example.com", rules) is False

    def test_is_valid_crawl_url_rejects_skip_extensions(self) -> None:
        pipeline = DeepCrawlPipeline(
            store=MagicMock(),
            executor=MagicMock(),
            engine=MagicMock(),
            robots_parser=RobotsParser(),
            rate_limiter=MagicMock(),
            data_dir=Path("/tmp/test_crawl"),
        )
        rules = RobotsRules([], [], None, [])
        assert pipeline._is_valid_crawl_url("https://example.com/a.pdf", "https://example.com", rules) is False


@pytest.mark.asyncio
async def test_discover_pages_from_sitemap(tmp_path: Path) -> None:
    pipeline = DeepCrawlPipeline(
        store=MagicMock(),
        executor=MagicMock(),
        engine=MagicMock(),
        robots_parser=RobotsParser(),
        rate_limiter=MagicMock(),
        data_dir=tmp_path,
    )
    rules = RobotsRules([], [], None, ["https://example.com/sitemap.xml"])
    body = '<?xml version="1.0"?><urlset><loc>https://example.com/a</loc></urlset>'
    mock_response = httpx.Response(200, text=body, request=httpx.Request("GET", "https://example.com/sitemap.xml"))

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.deep_crawl.secure_get",
        new=AsyncMock(return_value=mock_response),
    ):
        pages = await pipeline._discover_pages(
            "https://example.com",
            "https://example.com",
            rules,
            max_depth=1,
            max_pages=10,
        )

    assert pages == [("https://example.com/a", 1)]


@pytest.mark.asyncio
async def test_start_deep_crawl_enqueues_tasks(tmp_path: Path) -> None:
    store = MagicMock()
    store.create_group.return_value = "group-1"
    store.get_group_total_tasks.return_value = 1
    executor = MagicMock()
    executor.start_group = AsyncMock()
    robots = MagicMock()
    robots.fetch_and_parse = AsyncMock(
        return_value=RobotsRules([], [], 1.0, ["https://example.com/sitemap.xml"]),
    )
    rate_limiter = MagicMock()
    pipeline = DeepCrawlPipeline(
        store=store,
        executor=executor,
        engine=MagicMock(),
        robots_parser=robots,
        rate_limiter=rate_limiter,
        data_dir=tmp_path,
    )
    body = '<?xml version="1.0"?><urlset><loc>https://example.com/a</loc></urlset>'
    mock_response = httpx.Response(200, text=body, request=httpx.Request("GET", "https://example.com/sitemap.xml"))

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.deep_crawl.secure_get",
        new=AsyncMock(return_value=mock_response),
    ):
        result = await pipeline.start_deep_crawl("https://example.com", max_depth=1, max_pages=5)

    assert result["task_group_id"] == "group-1"
    assert result["status"] == "running"
    store.add_tasks_batch.assert_called_once()
    executor.start_group.assert_awaited_once_with("group-1")
    rate_limiter.set_domain_interval.assert_called_once_with("example.com", 1.0)


@pytest.mark.asyncio
async def test_discover_pages_fallback_extracts_links(tmp_path: Path) -> None:
    engine = MagicMock()
    doc = MagicMock()
    doc.metadata = {"_raw_html": '<a href="/docs">Docs</a>'}
    engine.crawl = AsyncMock(return_value=doc)
    pipeline = DeepCrawlPipeline(
        store=MagicMock(),
        executor=MagicMock(),
        engine=engine,
        robots_parser=RobotsParser(),
        rate_limiter=MagicMock(),
        data_dir=tmp_path,
    )
    rules = RobotsRules([], [], None, [])

    pages = await pipeline._discover_pages(
        "https://example.com",
        "https://example.com",
        rules,
        max_depth=1,
        max_pages=10,
    )

    assert pages[0] == ("https://example.com", 0)
    assert ("https://example.com/docs", 1) in pages
    engine.crawl.assert_awaited_once_with("https://example.com")


@pytest.mark.asyncio
async def test_extract_links_from_page_markdown_fallback(tmp_path: Path) -> None:
    engine = MagicMock()
    doc = MagicMock()
    doc.metadata = {}
    doc.page_content = "See [Docs](https://example.com/docs) here."
    engine.crawl = AsyncMock(return_value=doc)
    pipeline = DeepCrawlPipeline(
        store=MagicMock(),
        executor=MagicMock(),
        engine=engine,
        robots_parser=RobotsParser(),
        rate_limiter=MagicMock(),
        data_dir=tmp_path,
    )
    rules = RobotsRules([], [], None, [])

    links = await pipeline._extract_links_from_page("https://example.com", "https://example.com", rules)

    assert links == ["https://example.com/docs"]


def test_is_valid_crawl_url_rejects_fragment_and_disallowed_path(tmp_path: Path) -> None:
    pipeline = DeepCrawlPipeline(
        store=MagicMock(),
        executor=MagicMock(),
        engine=MagicMock(),
        robots_parser=RobotsParser(),
        rate_limiter=MagicMock(),
        data_dir=tmp_path,
    )
    rules = RobotsRules(disallowed=["/secret"], allowed=[], crawl_delay=None, sitemaps=[])

    assert pipeline._is_valid_crawl_url("https://example.com/page#frag", "https://example.com", rules) is False
    assert pipeline._is_valid_crawl_url("https://example.com/secret", "https://example.com", rules) is False


