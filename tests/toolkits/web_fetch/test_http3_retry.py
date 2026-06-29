"""Tests for L1 HTTP/3 (QUIC) retry lane in HttpFetcher."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.toolkits.web_fetch.engine import CrawlEngine
from myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher import HttpFetcher
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType, FetchResult
from myrm_agent_harness.toolkits.web_fetch.http3_probe import get_http3_retry_metrics, reset_http3_state_for_tests
from myrm_agent_harness.toolkits.web_fetch.router.site_experience import SiteExperienceStore


def _blocked_result(*, status: int = 403) -> FetchResult:
    return FetchResult(
        html="<html><body>Access Denied</body></html>",
        url="https://blocked.example/article",
        status_code=status,
        fetcher_type=FetcherType.HTTP,
    )


def _success_result() -> FetchResult:
    body = (
        "<html><body><article>"
        "<p>Real article content here with enough text to pass has_content checks. "
        "Additional paragraph padding to exceed the two-hundred character minimum "
        "required by FetchResult.has_content for L1 success detection.</p>"
        "</article></body></html>"
    )
    return FetchResult(
        html=body,
        url="https://blocked.example/article",
        status_code=200,
        fetcher_type=FetcherType.HTTP,
    )


@pytest.fixture(autouse=True)
def _reset_http3_state(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_http3_state_for_tests()
    monkeypatch.setenv("MYRM_HTTP3_RETRY", "1")
    monkeypatch.setenv("MYRM_ENABLE_SSRF_SHIELD", "false")


@pytest.fixture
def site_store(tmp_path: Path) -> SiteExperienceStore:
    return SiteExperienceStore(storage_path=tmp_path / "site_experience.json")


def test_should_retry_with_http3_on_403_and_antibot_not_429() -> None:
    fetcher = HttpFetcher()
    assert fetcher._should_retry_with_http3(_blocked_result()) is True
    assert fetcher._should_retry_with_http3(_blocked_result(status=429)) is False
    assert fetcher._should_retry_with_http3(None) is True
    assert fetcher._should_retry_with_http3(_success_result()) is False
    assert fetcher._should_retry_with_http3(_blocked_result(status=404)) is False


@pytest.mark.asyncio
async def test_http2_blocked_then_http3_retry_success(site_store: SiteExperienceStore) -> None:
    fetcher = HttpFetcher()
    calls: list[bool] = []

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        calls.append(use_http3)
        if use_http3:
            return _success_result()
        return _blocked_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.get_global_site_experience_store",
            return_value=site_store,
        ),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert result.status_code == 200
    assert calls == [False, True]
    metrics = get_http3_retry_metrics()
    assert metrics["http3_retry_attempts"] == 1
    assert metrics["http3_retry_success"] == 1


@pytest.mark.asyncio
async def test_prefer_http3_skips_http2(site_store: SiteExperienceStore) -> None:
    site_store.set_prefer_http3("blocked.example")
    fetcher = HttpFetcher()
    calls: list[bool] = []

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        calls.append(use_http3)
        return _success_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.get_global_site_experience_store",
            return_value=site_store,
        ),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert calls == [True]


@pytest.mark.asyncio
async def test_prefer_http3_clears_on_quic_failure(site_store: SiteExperienceStore) -> None:
    site_store.set_prefer_http3("blocked.example")
    fetcher = HttpFetcher()

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        assert use_http3 is True
        return _blocked_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.get_global_site_experience_store",
            return_value=site_store,
        ),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert result.status_code == 403
    assert site_store.get_prefer_http3("blocked.example") is False


@pytest.mark.asyncio
async def test_proxy_pool_skips_http3_retry() -> None:
    proxy_pool = MagicMock()
    proxy_pool.get_next.return_value = MagicMock(to_url=lambda: "http://proxy.local:8080")
    fetcher = HttpFetcher(proxy_pool=proxy_pool)
    calls: list[bool] = []

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        calls.append(use_http3)
        return _blocked_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert result.status_code == 403
    assert calls == [False]


@pytest.mark.asyncio
async def test_http3_retry_disabled_only_http2() -> None:
    fetcher = HttpFetcher()
    calls: list[bool] = []

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        calls.append(use_http3)
        return _blocked_result()

    with (
        patch.dict("os.environ", {"MYRM_HTTP3_RETRY": "0"}),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert result.status_code == 403
    assert calls == [False]


@pytest.mark.asyncio
async def test_http3_success_marks_site_experience(site_store: SiteExperienceStore) -> None:
    fetcher = HttpFetcher()

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        if use_http3:
            return _success_result()
        return _blocked_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.get_global_site_experience_store",
            return_value=site_store,
        ),
    ):
        await fetcher.fetch("https://blocked.example/article")

    assert site_store.get_prefer_http3("blocked.example") is True


@pytest.mark.asyncio
async def test_engine_cache_metrics_exposes_http3_retry() -> None:
    engine = CrawlEngine()
    metrics = engine.get_cache_metrics()
    assert "http3_retry" in metrics
    assert "http3_retry_attempts" in metrics["http3_retry"]
    assert "http3_retry_success" in metrics["http3_retry"]
    await engine.shutdown()


@pytest.mark.asyncio
async def test_crawl_engine_skips_browser_when_l1_http_succeeds(tmp_path: Path) -> None:
    from langchain_core.documents import Document

    from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType

    engine = CrawlEngine(adaptive_router_rules_file=tmp_path / "router.pkl")
    browser_fetch = AsyncMock(return_value=None)

    async def mock_try_and_report(
        url: str,
        fetcher_type: FetcherType,
        **_kwargs: object,
    ) -> tuple[Document | None, bool, float, float | None, float | None, FetchResult | None]:
        if fetcher_type == FetcherType.HTTP:
            doc = Document(page_content="L1 success", metadata={"url": url})
            return doc, False, 1.0, None, None, _success_result()
        return None, True, 1.0, None, None, None

    with (
        patch.object(engine, "_try_and_report", side_effect=mock_try_and_report),
        patch.object(engine._browser_fetcher, "fetch", browser_fetch),
    ):
        doc, _fetch_result = await engine._crawl_with_degradation("https://blocked.example/article")

    assert doc is not None
    assert doc.page_content == "L1 success"
    browser_fetch.assert_not_called()
    await engine.shutdown()


@pytest.mark.asyncio
async def test_fetch_with_redirects_text_response(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.body = _success_result().html.encode()
    mock_response.encoding = "utf-8"
    mock_response.url = "https://blocked.example/article"
    mock_response.headers = {"content-type": "text/html"}
    install_fake_scrapling.return_value = mock_response

    with patch.dict("os.environ", {"MYRM_ENABLE_SSRF_SHIELD": "false"}):
        result = await fetcher._fetch_with_redirects(
            "https://blocked.example/article",
            headers={},
            cookie_jar=None,
            enable_ssrf_shield=False,
            allowed_hosts=[],
            use_http3=False,
        )

    assert result is not None
    assert result.status_code == 200
    assert "Real article content" in result.html


@pytest.mark.asyncio
async def test_fetch_with_redirects_304(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    mock_response = MagicMock()
    mock_response.status = 304
    mock_response.body = b""
    mock_response.encoding = "utf-8"
    mock_response.url = "https://blocked.example/article"
    mock_response.headers = {"etag": "abc"}
    install_fake_scrapling.return_value = mock_response

    result = await fetcher._fetch_with_redirects(
        "https://blocked.example/article",
        headers={"If-None-Match": "abc"},
        cookie_jar=None,
        enable_ssrf_shield=False,
        allowed_hosts=[],
        use_http3=False,
    )

    assert result is not None
    assert result.status_code == 304


@pytest.mark.asyncio
async def test_fetch_with_redirects_binary_body(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.body = b"%PDF-1.4"
    mock_response.encoding = "utf-8"
    mock_response.url = "https://blocked.example/doc.pdf"
    mock_response.headers = {"content-type": "application/pdf"}
    install_fake_scrapling.return_value = mock_response

    result = await fetcher._fetch_with_redirects(
        "https://blocked.example/doc.pdf",
        headers={},
        cookie_jar=None,
        enable_ssrf_shield=False,
        allowed_hosts=[],
        use_http3=False,
    )

    assert result is not None
    assert result.raw_body == b"%PDF-1.4"


@pytest.mark.asyncio
async def test_fetch_http3_passes_impersonate_none(install_fake_scrapling: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MYRM_HTTP3_RETRY", "1")
    fetcher = HttpFetcher()
    install_fake_scrapling.return_value = _blocked_result()

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
        new=AsyncMock(return_value=True),
    ):
        await fetcher.fetch("https://blocked.example/article")

    http3_calls = [call for call in install_fake_scrapling.call_args_list if call.kwargs.get("http3")]
    assert http3_calls
    assert http3_calls[0].kwargs.get("impersonate") is None


@pytest.mark.asyncio
async def test_http3_probe_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.toolkits.web_fetch.http3_probe import is_http3_retry_enabled, is_quic_egress_available

    monkeypatch.delenv("MYRM_HTTP3_RETRY", raising=False)
    assert is_http3_retry_enabled() is False
    assert await is_quic_egress_available() is False


@pytest.mark.asyncio
async def test_http3_probe_success_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.toolkits.web_fetch import http3_probe

    monkeypatch.setenv("MYRM_HTTP3_RETRY", "1")
    http3_probe.reset_http3_state_for_tests()

    with patch.object(http3_probe, "_probe_quic_egress", new=AsyncMock(return_value=True)):
        assert await http3_probe.is_quic_egress_available() is True

    http3_probe.reset_http3_state_for_tests()
    with patch.object(http3_probe, "_probe_quic_egress", new=AsyncMock(return_value=False)):
        assert await http3_probe.is_quic_egress_available() is False


def test_extract_domain_strips_www() -> None:
    assert HttpFetcher._extract_domain("https://www.blocked.example/path") == "blocked.example"


def test_should_retry_with_http3_branches() -> None:
    fetcher = HttpFetcher()
    not_modified = FetchResult(
        html="",
        url="https://blocked.example/article",
        status_code=304,
        fetcher_type=FetcherType.HTTP,
    )
    assert fetcher._should_retry_with_http3(not_modified) is False

    pdf_result = FetchResult(
        html="",
        url="https://blocked.example/doc.pdf",
        status_code=200,
        fetcher_type=FetcherType.HTTP,
        raw_body=b"%PDF-1.4",
    )
    assert fetcher._should_retry_with_http3(pdf_result) is False

    empty_shell = FetchResult(
        html="<html><body></body></html>",
        url="https://blocked.example/article",
        status_code=200,
        fetcher_type=FetcherType.HTTP,
    )
    assert fetcher._should_retry_with_http3(empty_shell) is True


@pytest.mark.asyncio
async def test_http2_success_skips_http3_retry() -> None:
    fetcher = HttpFetcher()
    calls: list[bool] = []

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        calls.append(use_http3)
        return _success_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert result.status_code == 200
    assert calls == [False]


@pytest.mark.asyncio
async def test_fetch_forwards_cache_headers() -> None:
    fetcher = HttpFetcher()
    captured_headers: list[dict[str, str]] = []

    async def fake_fetch_with_redirects(
        _url: str,
        *,
        headers: dict[str, str],
        use_http3: bool,
        **_kwargs: object,
    ) -> FetchResult | None:
        captured_headers.append(headers.copy())
        return _success_result() if not use_http3 else None

    with patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects):
        result = await fetcher.fetch(
            "https://blocked.example/article",
            etag='"abc123"',
            last_modified="Wed, 01 Jan 2025 00:00:00 GMT",
        )

    assert result is not None
    assert captured_headers[0]["If-None-Match"] == '"abc123"'
    assert captured_headers[0]["If-Modified-Since"] == "Wed, 01 Jan 2025 00:00:00 GMT"


@pytest.mark.asyncio
async def test_quic_unavailable_returns_http2_only() -> None:
    fetcher = HttpFetcher()
    calls: list[bool] = []

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        calls.append(use_http3)
        return _blocked_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=False),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert result.status_code == 403
    assert calls == [False]


@pytest.mark.asyncio
async def test_fetch_with_redirects_follows_location(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    redirect_response = MagicMock()
    redirect_response.status = 302
    redirect_response.body = b""
    redirect_response.encoding = "utf-8"
    redirect_response.url = "https://blocked.example/old"
    redirect_response.headers = {"Location": "/article"}

    final_response = MagicMock()
    final_response.status = 200
    final_response.body = _success_result().html.encode()
    final_response.encoding = "utf-8"
    final_response.url = "https://blocked.example/article"
    final_response.headers = {"content-type": "text/html"}

    install_fake_scrapling.side_effect = [redirect_response, final_response]

    result = await fetcher._fetch_with_redirects(
        "https://blocked.example/old",
        headers={},
        cookie_jar=None,
        enable_ssrf_shield=False,
        allowed_hosts=[],
        use_http3=False,
    )

    assert result is not None
    assert result.status_code == 200
    assert install_fake_scrapling.call_count == 2


@pytest.mark.asyncio
async def test_http3_retry_failure_records_metric(site_store: SiteExperienceStore) -> None:
    fetcher = HttpFetcher()

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        return _blocked_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.get_global_site_experience_store",
            return_value=site_store,
        ),
    ):
        await fetcher.fetch("https://blocked.example/article")

    metrics = get_http3_retry_metrics()
    assert metrics["http3_retry_attempts"] == 1
    assert metrics["http3_retry_success"] == 0


@pytest.mark.asyncio
async def test_prefer_http3_false_when_quic_unavailable(site_store: SiteExperienceStore) -> None:
    site_store.set_prefer_http3("blocked.example")
    fetcher = HttpFetcher()
    calls: list[bool] = []

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        calls.append(use_http3)
        return _success_result()

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=False),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.get_global_site_experience_store",
            return_value=site_store,
        ),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None
    assert calls == [False]


@pytest.mark.asyncio
async def test_http2_none_http3_returns_http3_result(site_store: SiteExperienceStore) -> None:
    fetcher = HttpFetcher()
    http3_only = _success_result()

    async def fake_fetch_with_redirects(*_args: object, use_http3: bool, **_kwargs: object) -> FetchResult | None:
        if use_http3:
            return http3_only
        return None

    with (
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.is_quic_egress_available",
            new=AsyncMock(return_value=True),
        ),
        patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects),
        patch(
            "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.get_global_site_experience_store",
            return_value=site_store,
        ),
    ):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is http3_only


@pytest.mark.asyncio
async def test_fetch_with_redirects_ssrf_blocked(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.async_pin_url",
        new=AsyncMock(side_effect=__import__(
            "myrm_agent_harness.core.security.guards.url_allowlist",
            fromlist=["SSRFSecurityError"],
        ).SSRFSecurityError("blocked")),
    ):
        result = await fetcher._fetch_with_redirects(
            "http://127.0.0.1/internal",
            headers={},
            cookie_jar=None,
            enable_ssrf_shield=True,
            allowed_hosts=[],
            use_http3=False,
        )

    assert result is None


@pytest.mark.asyncio
async def test_fetch_with_redirects_redirect_missing_location(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    redirect_response = MagicMock()
    redirect_response.status = 302
    redirect_response.body = b""
    redirect_response.encoding = "utf-8"
    redirect_response.url = "https://blocked.example/old"
    redirect_response.headers = {}
    install_fake_scrapling.return_value = redirect_response

    result = await fetcher._fetch_with_redirects(
        "https://blocked.example/old",
        headers={},
        cookie_jar=None,
        enable_ssrf_shield=False,
        allowed_hosts=[],
        use_http3=False,
    )

    assert result is None


@pytest.mark.asyncio
async def test_fetch_with_redirects_too_many_redirects(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    redirect_response = MagicMock()
    redirect_response.status = 302
    redirect_response.body = b""
    redirect_response.encoding = "utf-8"
    redirect_response.url = "https://blocked.example/loop"
    redirect_response.headers = {"Location": "/loop"}
    install_fake_scrapling.return_value = redirect_response

    result = await fetcher._fetch_with_redirects(
        "https://blocked.example/loop",
        headers={},
        cookie_jar=None,
        enable_ssrf_shield=False,
        allowed_hosts=[],
        use_http3=False,
    )

    assert result is None
    assert install_fake_scrapling.call_count == 6


@pytest.mark.asyncio
async def test_fetch_with_redirects_async_fetcher_exception(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    install_fake_scrapling.side_effect = RuntimeError("network down")

    result = await fetcher._fetch_with_redirects(
        "https://blocked.example/article",
        headers={},
        cookie_jar=None,
        enable_ssrf_shield=False,
        allowed_hosts=[],
        use_http3=False,
    )

    assert result is None


@pytest.mark.asyncio
async def test_proxy_pool_injects_proxy_kwarg(install_fake_scrapling: AsyncMock) -> None:
    proxy_pool = MagicMock()
    proxy_pool.get_next.return_value = MagicMock(to_url=lambda: "http://proxy.local:8080")
    fetcher = HttpFetcher(proxy_pool=proxy_pool)

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.body = _success_result().html.encode()
    mock_response.encoding = "utf-8"
    mock_response.url = "https://blocked.example/article"
    mock_response.headers = {"content-type": "text/html"}
    install_fake_scrapling.return_value = mock_response

    with patch.dict("os.environ", {"MYRM_ENABLE_SSRF_SHIELD": "false", "MYRM_HTTP3_RETRY": "0"}):
        await fetcher.fetch("https://blocked.example/article")

    assert install_fake_scrapling.call_args.kwargs["proxy"] == "http://proxy.local:8080"


@pytest.mark.asyncio
async def test_session_vault_load_failure_returns_none() -> None:
    mock_vault = MagicMock()
    mock_vault.load = AsyncMock(side_effect=RuntimeError("vault unavailable"))
    fetcher = HttpFetcher(session_vault=mock_vault)

    async def fake_fetch_with_redirects(*_args: object, **_kwargs: object) -> FetchResult | None:
        return _success_result()

    with patch.object(fetcher, "_fetch_with_redirects", side_effect=fake_fetch_with_redirects):
        result = await fetcher.fetch("https://blocked.example/article")

    assert result is not None


@pytest.mark.asyncio
async def test_session_vault_empty_entry_skips_cookies(install_fake_scrapling: AsyncMock) -> None:
    mock_vault = MagicMock()
    mock_vault.load = AsyncMock(return_value=None)
    fetcher = HttpFetcher(session_vault=mock_vault)

    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.body = _success_result().html.encode()
    mock_response.encoding = "utf-8"
    mock_response.url = "https://blocked.example/article"
    mock_response.headers = {"content-type": "text/html"}
    install_fake_scrapling.return_value = mock_response

    with patch.dict("os.environ", {"MYRM_ENABLE_SSRF_SHIELD": "false", "MYRM_HTTP3_RETRY": "0"}):
        await fetcher.fetch("https://blocked.example/article")

    assert "cookies" not in install_fake_scrapling.call_args.kwargs


@pytest.mark.asyncio
async def test_http3_probe_uses_cached_result(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.toolkits.web_fetch import http3_probe

    monkeypatch.setenv("MYRM_HTTP3_RETRY", "1")
    http3_probe.reset_http3_state_for_tests()
    probe = AsyncMock(return_value=True)

    with patch.object(http3_probe, "_probe_quic_egress", probe):
        assert await http3_probe.is_quic_egress_available() is True
        assert await http3_probe.is_quic_egress_available() is True

    probe.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_http3_probe_real_exception_path(install_fake_scrapling: AsyncMock) -> None:
    from myrm_agent_harness.toolkits.web_fetch import http3_probe

    install_fake_scrapling.side_effect = RuntimeError("quic blocked")
    assert await http3_probe._probe_quic_egress() is False


@pytest.mark.asyncio
async def test_crawl_engine_escalates_browser_when_l1_fails(tmp_path: Path) -> None:
    from langchain_core.documents import Document

    engine = CrawlEngine(adaptive_router_rules_file=tmp_path / "router.pkl")
    browser_doc = Document(page_content="Browser fallback", metadata={"url": "https://blocked.example/article"})
    fetcher_types: list[FetcherType] = []

    async def mock_try_and_report(
        url: str,
        fetcher_type: FetcherType,
        **_kwargs: object,
    ) -> tuple[Document | None, bool, float, float | None, float | None, FetchResult | None]:
        fetcher_types.append(fetcher_type)
        if fetcher_type == FetcherType.HTTP:
            return None, True, 1.0, None, None, _blocked_result()
        if fetcher_type == FetcherType.BROWSER:
            return browser_doc, False, 2.0, None, None, None
        return None, True, 1.0, None, None, None

    with patch.object(engine, "_try_and_report", side_effect=mock_try_and_report):
        doc, _fetch_result = await engine._crawl_with_degradation("https://blocked.example/article")

    assert doc is not None
    assert doc.page_content == "Browser fallback"
    assert fetcher_types == [FetcherType.HTTP, FetcherType.BROWSER]
    await engine.shutdown()


@pytest.mark.asyncio
async def test_fetch_with_redirects_ssrf_rewrites_url(install_fake_scrapling: AsyncMock) -> None:
    fetcher = HttpFetcher()
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.body = _success_result().html.encode()
    mock_response.encoding = "utf-8"
    mock_response.url = "https://blocked.example/article"
    mock_response.headers = {"content-type": "text/html"}
    install_fake_scrapling.return_value = mock_response

    with patch(
        "myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher.async_pin_url",
        new=AsyncMock(return_value=("https://10.0.0.1/safe", {"Host": "blocked.example"})),
    ):
        result = await fetcher._fetch_with_redirects(
            "https://blocked.example/article",
            headers={},
            cookie_jar=None,
            enable_ssrf_shield=True,
            allowed_hosts=["blocked.example"],
            use_http3=False,
        )

    assert result is not None
    assert install_fake_scrapling.call_args.args[0] == "https://10.0.0.1/safe"


def test_is_http3_retry_enabled_truthy_variants(monkeypatch: pytest.MonkeyPatch) -> None:
    from myrm_agent_harness.toolkits.web_fetch.http3_probe import is_http3_retry_enabled

    monkeypatch.setenv("MYRM_HTTP3_RETRY", "true")
    assert is_http3_retry_enabled() is True
    monkeypatch.setenv("MYRM_HTTP3_RETRY", "yes")
    assert is_http3_retry_enabled() is True

