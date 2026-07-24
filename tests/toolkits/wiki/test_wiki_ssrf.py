"""SSRF and URL fetching tests for wiki URL ingestion."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFSecurityError
from myrm_agent_harness.toolkits.wiki.wiki_agent_tools import _fetch_url_as_markdown


@pytest.mark.asyncio
async def test_fetch_url_blocks_ssrf() -> None:
    """FetchEngine validates SSRF; if it returns None, fallback secure_get also raises."""
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
async def test_fetch_url_uses_fetch_engine() -> None:
    """Primary path: FetchEngine returns Document with page_content."""
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
async def test_fetch_url_falls_back_on_fetch_engine_failure() -> None:
    """Fallback: FetchEngine raises → secure_get + MarkdownGenerator."""
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
    """Fallback: FetchEngine returns Document but page_content is empty."""
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
    """Fallback: FetchEngine returns None (e.g. SSRF blocked)."""
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


@pytest.mark.asyncio
async def test_fetch_url_fallback_http_error() -> None:
    """Fallback path: secure_get returns non-200 → ValueError."""
    mock_response = type("R", (), {"status_code": 404, "text": "Not Found"})()

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
        mock_engine.crawl = AsyncMock(side_effect=RuntimeError("down"))
        with pytest.raises(ValueError, match="HTTP 404"):
            await _fetch_url_as_markdown("https://example.com/missing")


@pytest.mark.asyncio
async def test_fetch_url_fallback_empty_markdown() -> None:
    """Fallback path: MarkdownGenerator returns None raw_markdown → placeholder."""
    mock_response = type("R", (), {"status_code": 200, "text": ""})()
    mock_md_result = MagicMock()
    mock_md_result.raw_markdown = None

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools",
        ) as mock_engine,
        patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            return_value=mock_response,
        ),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.markdown_generator.MarkdownGenerator",
        ) as mock_gen_cls,
    ):
        mock_gen_cls.return_value.generate_markdown.return_value = mock_md_result
        mock_engine.crawl = AsyncMock(return_value=None)
        result = await _fetch_url_as_markdown("https://example.com/blank")

    assert result == "# https://example.com/blank\n\n(empty page)"


@pytest.mark.asyncio
async def test_fetch_url_fallback_network_error() -> None:
    """Fallback path: secure_get raises network error → exception propagates."""
    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.web_fetch_tools",
        ) as mock_engine,
        patch(
            "myrm_agent_harness.core.security.http.secure_fetch.secure_get",
            new_callable=AsyncMock,
            side_effect=ConnectionError("DNS resolution failed"),
        ),
    ):
        mock_engine.crawl = AsyncMock(side_effect=RuntimeError("engine down"))
        with pytest.raises(ConnectionError, match="DNS resolution"):
            await _fetch_url_as_markdown("https://nonexistent.invalid/page")


@pytest.mark.asyncio
async def test_fetch_url_fetch_engine_import_failure() -> None:
    """FetchEngine import fails (ModuleNotFoundError) → fallback to secure_get."""
    mock_response = type("R", (), {"status_code": 200, "text": "<html><body><p>imported ok</p></body></html>"})()

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
        mock_engine.crawl = AsyncMock(
            side_effect=ModuleNotFoundError("No module named 'scrapling'")
        )
        result = await _fetch_url_as_markdown("https://example.com/no-scrapling")

    mock_secure_get.assert_awaited_once()
    assert "imported ok" in result


@pytest.mark.asyncio
async def test_fetch_url_doc_with_none_page_content() -> None:
    """FetchEngine returns Document with page_content=None → fallback."""
    mock_doc = MagicMock()
    mock_doc.page_content = None

    mock_response = type("R", (), {"status_code": 200, "text": "<html><body><p>none content</p></body></html>"})()

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
        result = await _fetch_url_as_markdown("https://example.com/none-content")

    assert "none content" in result
