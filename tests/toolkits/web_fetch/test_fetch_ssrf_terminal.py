"""A web_fetch request the SSRF policy rejects must end there, and local mode must keep its own machine reachable.

Real loopback servers count every request that reaches them and real curl_cffi performs the HTTP tier,
so each scenario proves what was (or was never) contacted. The browser and stealth tiers are spies:
a rejected URL that reaches one of them would be fetched there without the HTTP tier's checks.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from myrm_agent_harness.core.security.guards.ssrf import SSRFResult, SSRFSecurityError
from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import BrowserNavigationBlockedError
from myrm_agent_harness.toolkits.web_fetch.engine import FetchEngine
from myrm_agent_harness.toolkits.web_fetch.fetchers.browser_fetcher import BrowserFetcher
from myrm_agent_harness.toolkits.web_fetch.fetchers.http_fetcher import HttpFetcher
from myrm_agent_harness.toolkits.web_fetch.fetchers.protocols import FetcherType
from myrm_agent_harness.toolkits.web_fetch.fetchers.stealth_fetcher import StealthFetcher
from myrm_agent_harness.toolkits.web_fetch.processing.url_normalizer import normalize_url
from myrm_agent_harness.toolkits.web_fetch.router.models import FetcherDecision
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._redirect_servers import page, redirect, serve

# Scrapling builds its lxml parser with an option lxml now warns about; the project turns warnings into errors.
pytestmark = pytest.mark.filterwarnings("ignore:The 'strip_cdata' option")

_ARTICLE = "<article><p>" + "reachable-body " * 40 + "</p></article>"  # enough markup to not read as an empty shell


@dataclass(slots=True)
class _Tiers:
    browser: AsyncMock
    stealth: AsyncMock

    def untouched(self) -> bool:
        return not self.browser.await_count and not self.stealth.await_count


def _engine(tmp_path: Path, *, allow_private_networks: bool) -> tuple[FetchEngine, _Tiers]:
    engine = FetchEngine(
        adaptive_router_rules_file=tmp_path / "rules.pkl", allow_private_networks=allow_private_networks
    )
    tiers = _Tiers(browser=AsyncMock(return_value=None), stealth=AsyncMock(return_value=None))
    engine._browser_fetcher.fetch = tiers.browser  # type: ignore[method-assign]
    engine._stealth_fetcher.fetch = tiers.stealth  # type: ignore[method-assign]
    return engine, tiers


@pytest.fixture(autouse=True)
def _offline_http3() -> Iterator[None]:
    with patch.object(HttpFetcher, "_can_use_http3_lane", AsyncMock(return_value=False)):
        yield


@pytest.mark.asyncio
class TestLocalMode:
    async def test_requested_private_page_is_fetched_by_the_http_tier(self, tmp_path: Path) -> None:
        engine, tiers = _engine(tmp_path, allow_private_networks=True)
        with serve({"/page": page(_ARTICLE)}) as site:
            doc = await engine.crawl(site.url("/page"), allow_escalation=False)

        assert doc is not None
        assert "reachable-body" in doc.page_content
        assert site.paths() == ["/page"]
        assert tiers.untouched()

    async def test_redirect_within_the_requested_origin_is_followed(self, tmp_path: Path) -> None:
        engine, _tiers = _engine(tmp_path, allow_private_networks=True)
        with serve({"/start": redirect("/page"), "/page": page(_ARTICLE)}) as site:
            doc = await engine.crawl(site.url("/start"), allow_escalation=False)

        assert doc is not None
        assert site.paths() == ["/start", "/page"]

    @pytest.mark.parametrize("host", ["127.0.0.1", "2130706433"], ids=["dotted", "decimal-integer"])
    async def test_redirect_to_another_private_origin_is_never_requested(self, tmp_path: Path, host: str) -> None:
        engine, tiers = _engine(tmp_path, allow_private_networks=True)
        with serve({"/secret": page(_ARTICLE)}) as internal:
            port = internal.base_url.rsplit(":", 1)[1]
            with serve({"/start": redirect(f"http://{host}:{port}/secret")}) as entry:
                doc = await engine.crawl(entry.url("/start"), allow_escalation=False)

        assert doc is None
        assert internal.hits == []
        assert entry.paths() == ["/start"]
        assert tiers.untouched()

    @pytest.mark.parametrize(
        "metadata_url",
        ["http://169.254.169.254/latest/meta-data/", "http://metadata.google.internal/computeMetadata/v1/"],
    )
    async def test_cloud_metadata_is_blocked_even_when_requested(self, tmp_path: Path, metadata_url: str) -> None:
        engine, tiers = _engine(tmp_path, allow_private_networks=True)

        assert await engine.crawl(metadata_url, allow_escalation=False) is None
        assert tiers.untouched()

    async def test_blocked_url_is_remembered_as_failed(self, tmp_path: Path) -> None:
        engine, _tiers = _engine(tmp_path, allow_private_networks=True)
        metadata_url = "http://169.254.169.254/latest/meta-data/"

        await engine.crawl(metadata_url, allow_escalation=False)

        assert engine._fail_cache.contains(normalize_url(metadata_url))


@pytest.mark.asyncio
class TestCloudMode:
    async def test_blocked_redirect_hop_does_not_degrade_to_other_tiers(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The entry gate is bypassed and the first hop allowlisted to model a public entry URL
        # whose redirect leads inside; loopback stands in for both ends of the chain.
        monkeypatch.setattr(
            "myrm_agent_harness.core.security.guards.ssrf.validate_url_for_ssrf", lambda _url: SSRFResult(safe=True)
        )
        monkeypatch.setenv("MYRM_ALLOWED_INTERNAL_HOSTS", "127.0.0.1")
        engine, tiers = _engine(tmp_path, allow_private_networks=False)
        with serve({"/secret": page(_ARTICLE)}) as internal:
            port = internal.base_url.rsplit(":", 1)[1]
            with serve({"/start": redirect(f"http://localhost:{port}/secret")}) as entry:
                doc = await engine.crawl(entry.url("/start"), allow_escalation=False)

        assert doc is None
        assert entry.paths() == ["/start"]
        assert internal.hits == []
        assert tiers.untouched()


@pytest.mark.asyncio
class TestHttpFetcherPropagation:
    async def test_shield_off_follows_private_redirect_hops(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MYRM_ENABLE_SSRF_SHIELD", "false")
        with serve({"/secret": page(_ARTICLE)}) as internal:
            port = internal.base_url.rsplit(":", 1)[1]
            with serve({"/start": redirect(f"http://127.0.0.1:{port}/secret")}) as entry:
                result = await HttpFetcher(allow_private_networks=True).fetch(entry.url("/start"))

        assert result is not None
        assert internal.paths() == ["/secret"]

    async def test_rejected_hop_raises_instead_of_returning_none(self) -> None:
        with serve({"/secret": page(_ARTICLE)}) as internal:
            port = internal.base_url.rsplit(":", 1)[1]
            with (
                serve({"/start": redirect(f"http://127.0.0.1:{port}/secret")}) as entry,
                pytest.raises(SSRFSecurityError),
            ):
                await HttpFetcher(allow_private_networks=True).fetch(entry.url("/start"))

        assert internal.hits == []


@pytest.mark.asyncio
class TestBrowserFetcherPolicy:
    @staticmethod
    def _pool() -> MagicMock:
        tab = MagicMock()
        tab.content = AsyncMock(return_value="<html></html>")
        pool = MagicMock()
        pool.acquire_page = AsyncMock(return_value=(tab, "crawl"))
        pool.release_page = AsyncMock()
        return pool

    async def test_blocked_navigation_raises_and_releases_the_page(self) -> None:
        pool = self._pool()
        blocked = BrowserNavigationBlockedError("Blocked: private address")

        with (
            patch("myrm_agent_harness.toolkits.browser.navigation.Navigator.goto", AsyncMock(side_effect=blocked)),
            pytest.raises(SSRFSecurityError, match="private address"),
        ):
            await BrowserFetcher(browser_pool=pool).fetch("http://127.0.0.1/")

        pool.release_page.assert_awaited_once()

    async def test_other_navigation_failures_still_degrade(self) -> None:
        pool = self._pool()

        with patch(
            "myrm_agent_harness.toolkits.browser.navigation.Navigator.goto", AsyncMock(side_effect=OSError("x"))
        ):
            assert await BrowserFetcher(browser_pool=pool).fetch("http://example.com/") is None

    async def test_each_fetch_gets_its_own_origin_grants(self) -> None:
        pool = self._pool()
        fetcher = BrowserFetcher(browser_pool=pool, allow_private_networks=True)
        seen: list[object] = []

        def _record(*_args: object, **kwargs: object) -> MagicMock:
            seen.append(kwargs["private_origins"])
            navigator = MagicMock()
            navigator.goto = AsyncMock(return_value=("t", "http://localhost/", 200))
            return navigator

        with patch("myrm_agent_harness.toolkits.browser.navigation.Navigator", side_effect=_record):
            await fetcher.fetch("http://localhost:3000/")
            await fetcher.fetch("http://localhost:3000/")

        assert len(seen) == 2
        assert seen[0] is not seen[1]


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.skipif(not chromium_available(), reason="Chromium not available")
class TestStealthTier:
    """Scrapling drives a real Chromium without a route hook: only the requested and the final URL can be judged."""

    async def test_requested_private_page_is_fetched(self) -> None:
        with serve({"/page": page(_ARTICLE)}) as site:
            result = await StealthFetcher(allow_private_networks=True).fetch(site.url("/page"))

        assert result is not None
        assert "reachable-body" in result.html

    async def test_page_the_browser_ended_on_is_judged_and_not_returned(self) -> None:
        with serve({"/secret": page(_ARTICLE)}) as internal:
            port = internal.base_url.rsplit(":", 1)[1]
            with (
                serve({"/start": redirect(f"http://127.0.0.1:{port}/secret")}) as entry,
                pytest.raises(SSRFSecurityError),
            ):
                await StealthFetcher(allow_private_networks=True).fetch(entry.url("/start"))

    async def test_private_url_is_rejected_before_any_browser_work_under_the_cloud_policy(self) -> None:
        with serve({"/page": page(_ARTICLE)}) as site, pytest.raises(SSRFSecurityError):
            await StealthFetcher().fetch(site.url("/page"))

        assert site.hits == []

    async def test_engine_stops_when_the_router_starts_at_the_stealth_tier(self, tmp_path: Path) -> None:
        engine, tiers = _engine(tmp_path, allow_private_networks=True)
        engine._stealth_fetcher = StealthFetcher(allow_private_networks=True)
        stealth_start = FetcherDecision(fetcher_type=FetcherType.STEALTH, reason="test")
        with (
            patch.object(engine._router, "select", return_value=stealth_start),
            serve({"/secret": page(_ARTICLE)}) as internal,
        ):
            port = internal.base_url.rsplit(":", 1)[1]
            with serve({"/start": redirect(f"http://127.0.0.1:{port}/secret")}) as entry:
                doc = await engine.crawl(entry.url("/start"), allow_escalation=False)

        assert doc is None
        assert not tiers.browser.await_count


@pytest.mark.asyncio
async def test_pinned_host_header_does_not_follow_the_request_to_the_next_hop(
    install_fake_scrapling: AsyncMock,
) -> None:
    """Hop one is pinned to an address (Host: its name); hop two is allowlisted and needs no pin."""

    def _response(status: int, location: str | None, url: str) -> MagicMock:
        response = MagicMock()
        response.status = status
        response.headers = {"Location": location} if location else {"content-type": "text/html"}
        response.body = ("<article><p>" + "x" * 300 + "</p></article>").encode()
        response.encoding = "utf-8"
        response.url = url
        return response

    install_fake_scrapling.side_effect = [
        _response(302, "http://127.0.0.1:9/next", "http://8.8.8.8/start"),
        _response(200, None, "http://127.0.0.1:9/next"),
    ]

    result = await HttpFetcher()._fetch_with_redirects(
        "http://8.8.8.8/start",
        headers={},
        cookie_jar=None,
        enable_ssrf_shield=True,
        allowed_hosts=["127.0.0.1"],
        use_http3=False,
    )

    assert result is not None
    first, second = (call.kwargs.get("headers", {}) for call in install_fake_scrapling.await_args_list)
    assert first == {"Host": "8.8.8.8"}
    assert "Host" not in second
