"""Tests for FetchEngine fetch-mixin / escalation-mixin branch coverage.

Covers tier degradation paths, fetch result handling branches (304,
non-degradable 4xx, empty shell, binary, weixin, anti-bot, truncation
event), and L4 remote escalation (markdown / html / failure).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.documents import Document

from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import (
    FetcherType,
    FetchResult,
)


def _make_engine(tmpdir: str) -> FetchEngine:
    return FetchEngine(adaptive_router_rules_file=Path(tmpdir) / "rules.pkl")


def _http_result(html: str, status: int = 200) -> FetchResult:
    return FetchResult(html=html, url="http://example.com/page", status_code=status)


def _stub_fetchers(engine: FetchEngine) -> tuple[AsyncMock, AsyncMock, AsyncMock]:
    http = AsyncMock()
    browser = AsyncMock()
    stealth = AsyncMock()
    browser.set_launch_mode_preference = MagicMock()
    stealth.set_launch_mode_preference = MagicMock()
    engine._http_fetcher = http  # type: ignore[assignment]
    engine._browser_fetcher = browser  # type: ignore[assignment]
    engine._stealth_fetcher = stealth  # type: ignore[assignment]
    engine._pipeline = MagicMock()  # type: ignore[assignment]
    engine._router = SimpleNamespace(
        select=lambda url: SimpleNamespace(fetcher_type=FetcherType.HTTP),
        report_result=lambda *a, **k: None,
        shutdown=lambda: None,
    )
    return http, browser, stealth


def _doc(text: str = "content") -> Document:
    return Document(page_content=text, metadata={"title": "page"})


RICH_HTML = (
    "<html><body><article><p>"
    + ("lorem ipsum content " * 40)
    + "</p></article></body></html>"
)


# ===================================================================
# _try_fetch_and_process branch coverage
# ===================================================================


class TestTryFetchAndProcess:
    @pytest.mark.asyncio
    async def test_http_304_not_modified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result("", status=304)

            doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                "http://example.com/page", FetcherType.HTTP, etag="abc"
            )

            assert doc is None
            assert degradable is False
            assert result is not None and result.status_code == 304
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_http_4xx_non_degradable_aborts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result("", status=404)

            doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                "http://example.com/page", FetcherType.HTTP
            )

            assert doc is None
            assert degradable is False
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_http_empty_shell_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result("<html><head></head></html>")

            doc, degradable, _, _, _, _ = await engine._try_fetch_and_process(
                "http://example.com/page", FetcherType.HTTP
            )

            assert doc is None
            assert degradable is True
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_fetcher_none_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = None

            doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                "http://example.com/page", FetcherType.HTTP
            )

            assert doc is None
            assert degradable is True
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_binary_body_routed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = FetchResult(
                html=RICH_HTML,
                url="http://example.com/img.png",
                raw_body=b"\x89PNG\r\n",
                headers={"content-type": "image/png"},
            )
            with patch(
                "myrm_agent_harness.toolkits.web_fetch.binary_router.route_binary_content",
                new=AsyncMock(return_value=_doc("binary")),
            ):
                doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                    "http://example.com/img.png", FetcherType.HTTP
                )

                assert doc is not None
                assert doc.page_content == "binary"
                assert degradable is False
                assert result is not None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_weixin_url_parsed_fastpath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result(RICH_HTML)
            url = "https://mp.weixin.qq.com/s/abc123"
            with patch(
                "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.parse_weixin_article_html",
                new=lambda html, url=None: _doc("weixin"),
            ):
                doc, degradable, _, _, _, _ = await engine._try_fetch_and_process(
                    url, FetcherType.HTTP
                )

                assert doc is not None
                assert doc.page_content == "weixin"
                assert degradable is False
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_weixin_without_js_content_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result("<html>shell</html>")
            url = "https://mp.weixin.qq.com/s/abc123"
            with (
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.parse_weixin_article_html",
                    new=lambda html, url=None: None,
                ),
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.has_weixin_js_content",
                    new=lambda html: False,
                ),
            ):
                doc, degradable, _, _, _, _ = await engine._try_fetch_and_process(
                    url, FetcherType.HTTP
                )

                assert doc is None
                assert degradable is True
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_antibot_detected_degrades(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result(RICH_HTML, status=503)
            with patch(
                "myrm_agent_harness.toolkits.web_fetch.engine.fetch_mixin.detect_antibot",
                new=lambda status, html: (True, "challenge"),
            ):
                doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                    "http://example.com/page", FetcherType.HTTP
                )

                assert doc is None
                assert degradable is True
                assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_pipeline_doc_returns_with_truncation_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result(RICH_HTML)
            truncated = _doc("truncated content")
            truncated.metadata["was_truncated"] = True
            engine._pipeline.process.return_value = truncated
            with patch(
                "myrm_agent_harness.utils.event_utils.dispatch_custom_event",
                new=AsyncMock(return_value=None),
            ):
                doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                    "http://example.com/page", FetcherType.HTTP
                )

                assert doc is not None
                assert degradable is True
                assert result is not None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_browser_launch_mode_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            _, browser, _ = _stub_fetchers(engine)
            browser.set_launch_mode_preference = MagicMock()
            browser.fetch.return_value = _http_result(RICH_HTML)

            with patch(
                "myrm_agent_harness.toolkits.web_fetch.escalation.context.get_bound_browser_launch_mode",
                new=lambda: "EXTENSION",
            ):
                await engine._try_fetch_and_process(
                    "http://example.com/page", FetcherType.BROWSER
                )

                browser.set_launch_mode_preference.assert_called_once_with("EXTENSION")
            await engine.shutdown()


# ===================================================================
# _crawl_with_degradation tier ladder coverage
# ===================================================================


class TestCrawlWithDegradation:
    @pytest.mark.asyncio
    async def test_stealth_start_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.STEALTH),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            stealth.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc()

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert result is not None
            stealth.fetch.assert_awaited_once()
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_stealth_fail_then_browser_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.STEALTH),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            stealth.fetch.return_value = None
            browser.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc()

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_stealth_and_browser_fail_then_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.STEALTH),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            stealth.fetch.return_value = None
            browser.fetch.return_value = None
            provider = SimpleNamespace(
                provider_id="reader",
                fetch_url=AsyncMock(
                    return_value=SimpleNamespace(
                        content="# md",
                        is_markdown=True,
                        url="http://example.com/page",
                        title="t",
                    )
                ),
            )
            engine.set_escalation_providers([provider])

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert doc.metadata.get("escalation_provider") == "reader"
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_browser_start_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.BROWSER),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            browser.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc()

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_http_success_no_degradation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc()

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            http.fetch.assert_awaited_once()
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_http_4xx_not_degradable_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            http.fetch.return_value = _http_result("", status=404)

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is None
            browser.fetch.assert_not_awaited()
            stealth.fetch.assert_not_awaited()
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_full_ladder_failure_without_escalation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            http.fetch.return_value = None
            browser.fetch.return_value = None
            stealth.fetch.return_value = None

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page", allow_escalation=False
            )

            assert doc is None
            assert result is None
            await engine.shutdown()


# ===================================================================
# _try_escalation / _load_bilibili_cookies coverage
# ===================================================================


class TestEscalationMixin:
    @pytest.mark.asyncio
    async def test_escalation_no_providers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            engine._escalation_providers = None

            doc, result = await engine._try_escalation("http://example.com/page")

            assert doc is None
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_escalation_provider_failure_then_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            engine._pipeline = MagicMock()  # type: ignore[assignment]
            engine._pipeline.process.return_value = _doc()
            good = SimpleNamespace(
                provider_id="reader2",
                fetch_url=AsyncMock(
                    return_value=SimpleNamespace(
                        content="# final", is_markdown=True, url=None, title="t"
                    )
                ),
            )
            bad = SimpleNamespace(
                provider_id="broken",
                fetch_url=AsyncMock(side_effect=RuntimeError("boom")),
            )
            engine.set_escalation_providers([bad, good])

            doc, result = await engine._try_escalation("http://example.com/page")

            assert doc is not None
            assert doc.page_content == "# final"
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_escalation_markdown_truncated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            provider = SimpleNamespace(
                provider_id="reader3",
                fetch_url=AsyncMock(
                    return_value=SimpleNamespace(
                        content="x" * 100,
                        is_markdown=True,
                        url="http://example.com/page",
                        title="t",
                    )
                ),
            )
            engine.set_escalation_providers([provider])

            doc, result = await engine._try_escalation(
                "http://example.com/page", max_chars=10
            )

            assert doc is not None
            assert doc.page_content == "x" * 10
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_escalation_html_content_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            engine._pipeline = MagicMock()  # type: ignore[assignment]
            engine._pipeline.process.return_value = _doc("html doc")
            provider = SimpleNamespace(
                provider_id="reader4",
                fetch_url=AsyncMock(
                    return_value=SimpleNamespace(
                        content="<p>html</p>",
                        is_markdown=False,
                        url="http://example.com/page",
                        title="t",
                    )
                ),
            )
            engine.set_escalation_providers([provider])

            doc, result = await engine._try_escalation("http://example.com/page")

            assert doc is not None
            assert doc.metadata.get("escalation_provider") == "reader4"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_escalation_empty_content_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            provider = SimpleNamespace(
                provider_id="reader5",
                fetch_url=AsyncMock(
                    return_value=SimpleNamespace(
                        content="   ", is_markdown=True, url=None, title=""
                    )
                ),
            )
            engine.set_escalation_providers([provider])

            doc, result = await engine._try_escalation("http://example.com/page")

            assert doc is None
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_load_bilibili_cookies_no_vault(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            engine._http_fetcher._session_vault = None

            cookies = await engine._load_bilibili_cookies()

            assert cookies is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_load_bilibili_cookies_with_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            vault = AsyncMock()
            vault.load.return_value = SimpleNamespace(
                storage_state={
                    "cookies": [
                        {"name": "SESSDATA", "value": "v1"},
                        {"name": "buvid3", "value": "v2"},
                    ]
                }
            )
            engine._http_fetcher._session_vault = vault

            cookies = await engine._load_bilibili_cookies()

            assert cookies == {"SESSDATA": "v1", "buvid3": "v2"}
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_load_bilibili_cookies_missing_storage_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            vault = AsyncMock()
            vault.load.return_value = SimpleNamespace(storage_state=None)
            engine._http_fetcher._session_vault = vault

            cookies = await engine._load_bilibili_cookies()

            assert cookies is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_load_bilibili_cookies_vault_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            vault = AsyncMock()
            vault.load.side_effect = RuntimeError("vault error")
            engine._http_fetcher._session_vault = vault

            cookies = await engine._load_bilibili_cookies()

            assert cookies is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_escalation_html_pipeline_returns_none_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result("", status=404)
            engine._escalation_providers = [
                SimpleNamespace(
                    provider_id="p1",
                    fetch_url=AsyncMock(
                        return_value=SimpleNamespace(
                            content="<p>raw html</p>",
                            is_markdown=False,
                            url=None,
                            title=None,
                        )
                    ),
                )
            ]
            engine._pipeline = MagicMock()  # type: ignore[assignment]
            engine._pipeline.process.return_value = None

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is None
            assert result is None
            await engine.shutdown()


# ===================================================================
# fetch_mixin — remaining degradation ladder branches
# ===================================================================


class TestFetchMixinRemaining:
    @pytest.mark.asyncio
    async def test_weixin_with_js_content_continues_generic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc("generic")
            with (
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.parse_weixin_article_html",
                    new=lambda html, url=None: None,
                ),
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.has_weixin_js_content",
                    new=lambda html: True,
                ),
            ):
                doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                    "https://mp.weixin.qq.com/s/abc123", FetcherType.HTTP
                )

                assert doc is not None
                assert doc.page_content == "generic"
                assert degradable is True
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_psutil_unavailable_returns_none_metrics(self, monkeypatch) -> None:
        from myrm_agent_harness.toolkits.web_fetch.engine import fetch_mixin as fm

        monkeypatch.setattr(fm, "_PSUTIL_AVAILABLE", False)
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc()

            doc, _, _, cpu, mem, _ = await engine._try_fetch_and_process(
                "http://example.com/page", FetcherType.HTTP
            )

            assert doc is not None
            assert cpu is None
            assert mem is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_stealth_ladder_escalation_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.STEALTH),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            stealth.fetch.return_value = None
            browser.fetch.return_value = None
            engine._escalation_providers = None

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is None
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_browser_ladder_stealth_fallback_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.BROWSER),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            browser.fetch.return_value = None
            stealth.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc("stealth")

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert doc.page_content == "stealth"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_http_ladder_stealth_fallback_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            http.fetch.return_value = None
            browser.fetch.return_value = None
            stealth.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc("stealth final")

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert doc.page_content == "stealth final"
            await engine.shutdown()


# ===================================================================
# remaining ladder branches: browser/stealth escalation success,
# HTTP-ladder browser success, escalation html pipeline continue,
# psutil import-failure flag
# ===================================================================


class TestLadderRemainingBranches:
    @pytest.mark.asyncio
    async def test_weixin_no_js_content_returns_none_degrades(self) -> None:
        """Weixin URL with real content but no js_content div => skip generic."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, _, _ = _stub_fetchers(engine)
            http.fetch.return_value = _http_result(RICH_HTML)
            url = "https://mp.weixin.qq.com/s/abc123"
            with (
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.parse_weixin_article_html",
                    new=lambda html, url=None: None,
                ),
                patch(
                    "myrm_agent_harness.toolkits.web_fetch.extractors.weixin_extractor.has_weixin_js_content",
                    new=lambda html: False,
                ),
            ):
                doc, degradable, _, _, _, result = await engine._try_fetch_and_process(
                    url, FetcherType.HTTP
                )

                assert doc is None
                assert degradable is True
                assert result is not None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_browser_ladder_escalation_success(self) -> None:
        """BROWSER + STEALTH both fail, remote escalation returns markdown doc."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.BROWSER),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            browser.fetch.return_value = None
            stealth.fetch.return_value = None
            engine._escalation_providers = [
                SimpleNamespace(
                    provider_id="esc",
                    fetch_url=AsyncMock(
                        return_value=SimpleNamespace(
                            content="# Escaped body",
                            is_markdown=True,
                            url="http://escalated.example",
                            title="Esc",
                        )
                    ),
                )
            ]

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert doc.page_content == "# Escaped body"
            assert doc.metadata["escalation_provider"] == "esc"
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_http_ladder_browser_success(self) -> None:
        """HTTP degradable, then BROWSER tier succeeds."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            http.fetch.return_value = None
            browser.fetch.return_value = _http_result(RICH_HTML)
            engine._pipeline.process.return_value = _doc("browser final")

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert doc.page_content == "browser final"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_browser_ladder_escalation_returns_none(self) -> None:
        """BROWSER + STEALTH fail and escalation unavailable => return last result."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            engine._router = SimpleNamespace(
                select=lambda url: SimpleNamespace(fetcher_type=FetcherType.BROWSER),
                report_result=lambda *a, **k: None,
                shutdown=lambda: None,
            )
            browser.fetch.return_value = None
            stealth.fetch.return_value = None
            engine._escalation_providers = None

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is None
            assert result is None
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_http_ladder_escalation_success(self) -> None:
        """HTTP + BROWSER + STEALTH all fail, escalation succeeds."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            http.fetch.return_value = None
            browser.fetch.return_value = None
            stealth.fetch.return_value = None
            engine._escalation_providers = [
                SimpleNamespace(
                    provider_id="esc2",
                    fetch_url=AsyncMock(
                        return_value=SimpleNamespace(
                            content="# Last resort",
                            is_markdown=True,
                            url=None,
                            title=None,
                        )
                    ),
                )
            ]

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert doc.page_content == "# Last resort"
            await engine.shutdown()

    @pytest.mark.asyncio
    async def test_escalation_html_pipeline_none_then_next_provider(self) -> None:
        """First escalation provider yields HTML that the pipeline drops => continue to next."""
        with tempfile.TemporaryDirectory() as tmp:
            engine = _make_engine(tmp)
            http, browser, stealth = _stub_fetchers(engine)
            http.fetch.return_value = None
            browser.fetch.return_value = None
            stealth.fetch.return_value = None
            engine._pipeline.process.side_effect = [None, _doc("html escaped")]
            engine._escalation_providers = [
                SimpleNamespace(
                    provider_id="p1",
                    fetch_url=AsyncMock(
                        return_value=SimpleNamespace(
                            content="<p>raw one</p>",
                            is_markdown=False,
                            url=None,
                            title=None,
                        )
                    ),
                ),
                SimpleNamespace(
                    provider_id="p2",
                    fetch_url=AsyncMock(
                        return_value=SimpleNamespace(
                            content="<p>raw two</p>",
                            is_markdown=False,
                            url=None,
                            title=None,
                        )
                    ),
                ),
            ]

            doc, result = await engine._crawl_with_degradation(
                "http://example.com/page"
            )

            assert doc is not None
            assert doc.page_content == "html escaped"
            assert doc.metadata["escalation_provider"] == "p2"
            await engine.shutdown()

    def test_psutil_import_failure_sets_flag(self, monkeypatch) -> None:
        import importlib
        import sys

        from myrm_agent_harness.toolkits.web_fetch.engine import fetch_mixin as fm

        monkeypatch.setitem(sys.modules, "psutil", None)
        reloaded = importlib.reload(fm)
        assert reloaded._PSUTIL_AVAILABLE is False
