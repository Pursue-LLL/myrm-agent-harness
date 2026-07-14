"""SSRF and URL fetching tests for wiki URL ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown


@pytest.mark.asyncio
async def test_fetch_url_blocks_ssrf() -> None:
    """CrawlEngine validates SSRF; if it returns None, fallback secure_get also raises."""
    with (
        patch(
            "myrm_agent_harness.toolkits.wiki.wiki_agent_tools.web_fetch_tools",
            create=True,
        ) as mock_engine,
        patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            side_effect=SSRFSecurityError("private IP"),
        ),
    ):
        mock_engine.crawl = AsyncMock(return_value=None)
        with pytest.raises(SSRFSecurityError, match="private IP"):
            await _fetch_url_as_markdown("http://169.254.169.254/latest/meta-data/")


@pytest.mark.asyncio
async def test_fetch_url_uses_crawl_engine() -> None:
    """Primary path: CrawlEngine returns Document with page_content."""
    mock_doc = MagicMock()
    mock_doc.page_content = "# YouTube Video\n\nTranscript content here"

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools",
    ) as mock_engine:
        mock_engine.crawl = AsyncMock(return_value=mock_doc)
        result = await _fetch_url_as_markdown("https://www.youtube.com/watch?v=abc123")

    mock_engine.crawl.assert_awaited_once_with("https://www.youtube.com/watch?v=abc123")
    assert result == "# YouTube Video\n\nTranscript content here"


@pytest.mark.asyncio
async def test_fetch_url_falls_back_on_crawl_engine_failure() -> None:
    """Fallback: CrawlEngine raises → secure_get + MarkdownGenerator."""
    mock_response = type("R", (), {"status_code": 200, "text": "<html><body><p>ok</p></body></html>"})()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools",
        ) as mock_engine,
        patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ) as mock_secure_get,
    ):
        mock_engine.crawl = AsyncMock(side_effect=RuntimeError("engine unavailable"))
        result = await _fetch_url_as_markdown("https://example.com/article")

    mock_secure_get.assert_awaited_once()
    assert "ok" in result


@pytest.mark.asyncio
async def test_fetch_url_falls_back_on_empty_content() -> None:
    """Fallback: CrawlEngine returns Document but page_content is empty."""
    mock_doc = MagicMock()
    mock_doc.page_content = ""

    mock_response = type("R", (), {"status_code": 200, "text": "<html><body><p>fallback</p></body></html>"})()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools",
        ) as mock_engine,
        patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
    ):
        mock_engine.crawl = AsyncMock(return_value=mock_doc)
        result = await _fetch_url_as_markdown("https://example.com/empty")

    assert "fallback" in result


@pytest.mark.asyncio
async def test_fetch_url_falls_back_on_none_doc() -> None:
    """Fallback: CrawlEngine returns None (e.g. SSRF blocked)."""
    mock_response = type("R", (), {"status_code": 200, "text": "<html><body><p>recovered</p></body></html>"})()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools",
        ) as mock_engine,
        patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
    ):
        mock_engine.crawl = AsyncMock(return_value=None)
        result = await _fetch_url_as_markdown("https://example.com/blocked")

    assert "recovered" in result
