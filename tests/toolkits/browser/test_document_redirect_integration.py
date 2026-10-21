"""Real-Chromium proof that document navigations keep browser semantics through the script-injection route.

Every pooled context rewrites HTML documents to deliver the DOM enhancer, so the injection
route performs the document request itself. If it followed redirects inside the driver, the
page would keep the pre-redirect URL and origin, the redirect chain would be invisible to the
SSRF checks, and any response it could not rewrite would be requested a second time (a form
POST would be submitted twice). Each scenario counts what reached the server. Run with:
`pytest -m integration tests/toolkits/browser/test_document_redirect_integration.py`.
"""

from __future__ import annotations

import asyncio
import gzip
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from patchright.async_api import Error as BrowserDriverError
from patchright.async_api import Page
from patchright.async_api import TimeoutError as BrowserTimeoutError

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.utils.private_origins import private_origin_grants
from tests.toolkits.browser._browser_available import chromium_available
from tests.toolkits.browser._redirect_servers import HTML, Reply, Site, page, redirect, serve

pytestmark = [
    pytest.mark.integration,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_ENHANCER_PRESENT = "window.__myrm_enhancer_initialized === true"
_MAIN_WORLD = {"isolated_context": False}


@asynccontextmanager
async def _tab(*sites: Site) -> AsyncIterator[Page]:
    """A tab in a pooled context (script injection installed) whose session navigated to ``sites`` on purpose.

    The tests drive ``tab.goto`` directly, so they record the explicit navigation the way
    ``goto_with_ssrf_guard`` does; the redirect and injection behaviour under test is unaffected.
    """
    pool = GlobalBrowserPool(max_browsers=1)
    tab, context_key = await pool.acquire_page(ContextType.CRAWL, context_kwargs={"allow_private_networks": True})
    for site in sites:
        private_origin_grants(tab.context).grant(site.base_url)
    try:
        yield tab
    finally:
        await pool.release_page(tab, context_key)
        await pool.shutdown()


async def test_same_origin_redirect_updates_the_page_url_and_exposes_the_chain() -> None:
    with serve({"/start": redirect("/final"), "/final": page("arrived")}) as site:
        async with _tab(site) as tab:
            response = await tab.goto(site.url("/start"))
            assert response is not None
            assert tab.url == site.url("/final")
            assert response.request.redirected_from is not None
            assert response.request.redirected_from.url == site.url("/start")
            assert await tab.inner_text("body") == "arrived"
        assert site.hits == [("GET", "/start"), ("GET", "/final")]


async def test_cross_origin_redirect_moves_the_document_to_the_new_origin() -> None:
    with serve({"/landing": page("remote")}) as remote, serve({"/go": redirect(remote.url("/landing"))}) as origin:
        async with _tab(origin, remote) as tab:
            await tab.goto(origin.url("/go"))
            assert tab.url == remote.url("/landing")
            assert await tab.evaluate("location.origin") == remote.base_url
        assert remote.paths() == ["/landing"]


async def test_every_redirect_hop_reaches_the_server_exactly_once() -> None:
    routes = {"/a": redirect("/b", status=301), "/b": redirect("/c", status=307), "/c": page("end")}
    with serve(routes) as site:
        async with _tab(site) as tab:
            await tab.goto(site.url("/a"))
            assert tab.url == site.url("/c")
        assert site.hits == [("GET", "/a"), ("GET", "/b"), ("GET", "/c")]


async def test_redirect_loop_is_ended_by_the_browser_not_retried_by_the_route() -> None:
    with serve({"/loop": redirect("/loop")}) as site:
        async with _tab(site) as tab:
            with pytest.raises(BrowserDriverError, match="ERR_TOO_MANY_REDIRECTS"):
                await tab.goto(site.url("/loop"))
        assert len(site.hits) <= 21


async def test_cookie_set_on_a_redirect_reaches_the_landing_page() -> None:
    routes = {"/login": redirect("/home", headers=(("Set-Cookie", "sid=abc; Path=/"),)), "/home": page("home")}
    with serve(routes) as site:
        async with _tab(site) as tab:
            await tab.goto(site.url("/login"))
            assert "sid=abc" in await tab.evaluate("document.cookie")


async def test_non_html_document_is_requested_once() -> None:
    json_reply = Reply(body=b'{"ok": true}', content_type="application/json")
    with serve({"/data": json_reply}) as site:
        async with _tab(site) as tab:
            await tab.goto(site.url("/data"))
            assert "ok" in await tab.inner_text("body")
        assert site.hits == [("GET", "/data")]


async def test_form_post_with_a_non_html_answer_is_submitted_once() -> None:
    form = '<form method="post" action="/export"><button id="go">go</button></form>'
    routes = {
        "/form": Reply(body=f"<!DOCTYPE html><html><body>{form}</body></html>".encode()),
        "/export": Reply(body=b'{"exported": 1}', content_type="application/json"),
    }
    with serve(routes) as site:
        async with _tab(site) as tab:
            await tab.goto(site.url("/form"))
            async with tab.expect_navigation():
                await tab.click("#go")
        assert site.paths("POST") == ["/export"]


async def test_form_post_redirected_to_a_page_is_submitted_once() -> None:
    form = '<form method="post" action="/order"><button id="go">go</button></form>'
    routes = {
        "/form": Reply(body=f"<!DOCTYPE html><html><body>{form}</body></html>".encode()),
        "/order": redirect("/receipt", status=303),
        "/receipt": page("receipt"),
    }
    with serve(routes) as site:
        async with _tab(site) as tab:
            await tab.goto(site.url("/form"))
            async with tab.expect_navigation():
                await tab.click("#go")
            assert tab.url == site.url("/receipt")
        assert site.paths("POST") == ["/order"]
        assert site.paths("GET") == ["/form", "/receipt"]


async def test_attachment_download_still_works_with_a_single_request() -> None:
    attachment = Reply(
        body=b"payload",
        content_type="text/plain",
        headers=(("Content-Disposition", 'attachment; filename="a.txt"'),),
    )
    with serve({"/file": attachment}) as site:
        async with _tab(site) as tab:
            async with tab.expect_download() as download_info:
                with pytest.raises(BrowserDriverError, match="Download is starting"):
                    await tab.goto(site.url("/file"))
            download = await download_info.value
            assert download.suggested_filename == "a.txt"
        assert site.hits == [("GET", "/file")]


async def test_html_documents_still_receive_the_dom_enhancer() -> None:
    plain_html = Reply(
        body=b"<!DOCTYPE html><html><head><title>t</title></head><body>x</body></html>", content_type=HTML
    )
    with serve({"/start": redirect("/page"), "/page": plain_html}) as site:
        async with _tab(site) as tab:
            await tab.goto(site.url("/start"))
            assert await tab.evaluate(_ENHANCER_PRESENT, **_MAIN_WORLD) is True


async def test_compressed_responses_are_delivered_intact() -> None:
    gzip_header = (("Content-Encoding", "gzip"),)
    routes = {
        "/text": Reply(body=gzip.compress(b"plain words"), content_type="text/plain", headers=gzip_header),
        "/html": Reply(body=gzip.compress(b"<html><head></head><body>zipped page</body></html>"), headers=gzip_header),
    }
    with serve(routes) as site:
        async with _tab(site) as tab:
            await tab.goto(site.url("/text"))
            assert await tab.inner_text("body") == "plain words"
            await tab.goto(site.url("/html"))
            assert await tab.inner_text("body") == "zipped page"
            assert await tab.evaluate(_ENHANCER_PRESENT, **_MAIN_WORLD) is True


_ORDER_FORM = '<form method="post" action="/order"><button id="go">go</button></form>'
_DRIVER_FETCH_TIMEOUT_MS = 1500
_NAVIGATION_TIMEOUT_MS = 15_000


def _order_routes(order: Reply) -> dict[str, Reply]:
    return {"/form": Reply(body=f"<!DOCTYPE html><html><body>{_ORDER_FORM}</body></html>".encode()), "/order": order}


async def test_slow_form_post_is_submitted_once_when_the_answer_outlasts_the_driver_timeout() -> None:
    receipt = Reply(body=b"<!DOCTYPE html><html><body>receipt</body></html>", delay_s=4.0)
    with serve(_order_routes(receipt)) as site:
        async with _tab(site) as tab:
            # The injection route's own request inherits the context default; shrink it so a
            # "slow business endpoint" outlasts it within test time instead of 30 seconds.
            tab.context.set_default_timeout(_DRIVER_FETCH_TIMEOUT_MS)
            await tab.goto(site.url("/form"), timeout=_NAVIGATION_TIMEOUT_MS)
            async with tab.expect_navigation(timeout=_NAVIGATION_TIMEOUT_MS):
                await tab.click("#go", timeout=_NAVIGATION_TIMEOUT_MS)
            assert await tab.inner_text("body") == "receipt"
        assert site.paths("POST") == ["/order"]


async def test_unanswered_form_post_is_not_resent_and_does_not_wedge_teardown() -> None:
    unanswered = Reply(body=b"<!DOCTYPE html><html><body>late</body></html>", delay_s=30.0)
    with serve(_order_routes(unanswered)) as site:
        async with asyncio.timeout(20):
            async with _tab(site) as tab:
                tab.context.set_default_timeout(_DRIVER_FETCH_TIMEOUT_MS)
                await tab.goto(site.url("/form"), timeout=_NAVIGATION_TIMEOUT_MS)
                with pytest.raises(BrowserTimeoutError):
                    async with tab.expect_navigation(timeout=4000):
                        await tab.click("#go", timeout=_NAVIGATION_TIMEOUT_MS)
                assert site.paths("POST") == ["/order"]
        assert site.paths("POST") == ["/order"]
