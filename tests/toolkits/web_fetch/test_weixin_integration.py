"""Integration tests for WeChat article fast-path in FetchEngine."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine

_ARTICLE_URL = "https://mp.weixin.qq.com/s/D6PTZsG3DgbEOB11vvQQMA"
_ARTICLE_SNIPPET = "ReAct Agent 到 Harness Agent"
_HOTPOST_URL = "https://mp.weixin.qq.com/s/HIvOG6H0qvOcnLBLKF6A_w"
_HOTPOST_SNIPPET = "Hermes Agent 24小时热帖速报"


@pytest.mark.asyncio
async def test_weixin_url_routes_to_extractor() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = FetchEngine(adaptive_router_rules_file=Path(tmpdir) / "rules.pkl")

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.engine.extract_weixin_article",
            new_callable=AsyncMock,
        ) as mock_extract:
            mock_extract.return_value = MagicMock(
                page_content=f"# {_ARTICLE_SNIPPET}",
                metadata={"source_type": "weixin_article"},
            )

            await engine.crawl(_ARTICLE_URL)

            mock_extract.assert_awaited_once()
            assert mock_extract.await_args.args[0] == _ARTICLE_URL

        await engine.shutdown()


@pytest.mark.asyncio
async def test_non_weixin_url_skips_extractor() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = FetchEngine(adaptive_router_rules_file=Path(tmpdir) / "rules.pkl")

        with patch(
            "myrm_agent_harness.toolkits.web_fetch.engine.extract_weixin_article",
            new_callable=AsyncMock,
        ) as mock_extract:
            with patch.object(engine, "_crawl_with_degradation", new_callable=AsyncMock) as mock_crawl:
                mock_crawl.return_value = (
                    MagicMock(page_content="Article content", metadata={}),
                    MagicMock(status_code=200, etag=None, last_modified=None),
                )

                await engine.crawl("https://example.com/article")

                mock_extract.assert_not_called()
                mock_crawl.assert_awaited_once()

        await engine.shutdown()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_weixin_invalid_article_returns_none_live() -> None:
    """Deleted/invalid article IDs should not produce fabricated content."""
    invalid_url = "https://mp.weixin.qq.com/s/INVALID_ID_DOES_NOT_EXIST_000"
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = FetchEngine(adaptive_router_rules_file=Path(tmpdir) / "rules.pkl")
        try:
            doc = await engine.crawl(invalid_url, force_refresh=True)
        finally:
            await engine.shutdown()

    assert doc is None


@pytest.mark.integration
@pytest.mark.asyncio
async def test_weixin_blocked_html_parse_returns_none() -> None:
    from myrm_agent_harness.toolkits.web_fetch.weixin_extractor import parse_weixin_article_html

    blocked_html = """
    <html><body><h2>环境异常</h2><p>完成验证后即可继续访问。</p></body></html>
    """
    assert parse_weixin_article_html(blocked_html, url=_ARTICLE_URL) is None


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("url", "snippet"),
    [
        (_ARTICLE_URL, _ARTICLE_SNIPPET),
        (_HOTPOST_URL, _HOTPOST_SNIPPET),
    ],
)
async def test_weixin_article_live_fetch(url: str, snippet: str) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        engine = FetchEngine(adaptive_router_rules_file=Path(tmpdir) / "rules.pkl")
        try:
            doc = await engine.crawl(url, force_refresh=True)
        finally:
            await engine.shutdown()

    assert doc is not None, f"Failed to fetch WeChat article: {url}"
    assert snippet in doc.page_content, doc.page_content[:400]
    assert doc.metadata.get("source_type") == "weixin_article"
    assert "环境异常" not in doc.page_content
