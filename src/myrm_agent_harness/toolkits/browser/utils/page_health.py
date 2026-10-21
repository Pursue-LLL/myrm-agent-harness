"""Bounded browser and page health primitives: abort, probe, close, detach.

[INPUT]
- patchright.async_api::Browser, Page, CDPSession (POS: browser, page and protocol session under inspection)
- exceptions::BrowserSessionError (POS: base of PageUnresponsiveError)

[OUTPUT]
- PageUnresponsiveError: a page stopped answering protocol commands and cannot be reused
- abort_pending_navigation: stop an in-flight navigation without blocking on a stalled page
- probe_alive: bounded liveness check of a page
- probe_browser_alive: bounded liveness check of the browser process, independent of any page
- close_page_bounded / detach_cdp_bounded: best-effort teardown that never blocks on a wedged target

[POS]
Bounded browser and page health primitives, shared by navigation (timeout settlement, SSRF route
teardown), pool (idle page reuse, crash watchdog), network intelligence and session recovery (tab
healing). A main frame stuck in a stalled navigation or a spinning renderer leaves page-level
commands (`evaluate`, `unroute`, `close`, CDP `detach`) hanging with no timeout of their own, so
every call here carries its own bound. `Page.stopLoading` and the browser-level
`Browser.getVersion` are the commands the browser keeps answering in that state, which is why
abort and the browser probe use them.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ..exceptions import BrowserSessionError

if TYPE_CHECKING:
    from patchright.async_api import Browser, CDPSession, Page

_ABORT_TIMEOUT_S = 1.0
_DETACH_TIMEOUT_S = 1.0
_CLOSE_TIMEOUT_S = 2.0
_PROBE_TIMEOUT_S = 2.0


class PageUnresponsiveError(BrowserSessionError):
    """A page stopped answering protocol commands and cannot be reused."""


async def abort_pending_navigation(page: Page) -> None:
    """Cancel an in-flight navigation and stop loading, best effort and always bounded.

    Chromium answers `Page.stopLoading` even while the page's main frame is stalled, so it is
    sent over a dedicated CDP session. Engines without CDP (Firefox) fall back to
    `window.stop()`, which only works while the page still answers.
    """
    try:
        await _stop_loading_via_cdp(page)
    except TimeoutError:
        # A page that cannot answer even a protocol command is judged by `probe_alive`.
        return
    except Exception:
        with contextlib.suppress(Exception):
            await asyncio.wait_for(page.evaluate("window.stop()"), timeout=_ABORT_TIMEOUT_S)


async def _stop_loading_via_cdp(page: Page) -> None:
    cdp: CDPSession | None = None
    try:
        async with asyncio.timeout(_ABORT_TIMEOUT_S):
            cdp = await page.context.new_cdp_session(page)
            await cdp.send("Page.stopLoading")
    finally:
        if cdp is not None:
            await detach_cdp_bounded(cdp)


async def detach_cdp_bounded(cdp: CDPSession) -> None:
    """Detach a CDP session, giving up quietly when its target never answers."""
    with contextlib.suppress(Exception):
        await asyncio.wait_for(cdp.detach(), timeout=_DETACH_TIMEOUT_S)


async def close_page_bounded(page: Page) -> None:
    """Close a page, giving up quietly when it never answers, so one wedged page cannot block a caller."""
    with contextlib.suppress(Exception):
        await asyncio.wait_for(page.close(), timeout=_CLOSE_TIMEOUT_S)


async def probe_alive(page: Page) -> bool:
    """True when the page answers a trivial evaluation within the probe bound (a closed page raises at once)."""
    try:
        await asyncio.wait_for(page.evaluate("1"), timeout=_PROBE_TIMEOUT_S)
    except Exception:
        return False
    return True


async def probe_browser_alive(browser: Browser) -> bool:
    """True when the browser process answers ``Browser.getVersion`` over a browser-level CDP session.

    The browser serves this command whatever its pages are doing, so a slow page never reads as
    a dead browser. Non-Chromium browsers have no browser-level CDP session and report False.
    """
    cdp: CDPSession | None = None
    try:
        cdp = await asyncio.wait_for(browser.new_browser_cdp_session(), timeout=_PROBE_TIMEOUT_S)
        await asyncio.wait_for(cdp.send("Browser.getVersion"), timeout=_PROBE_TIMEOUT_S)
    except Exception:
        return False
    finally:
        if cdp is not None:
            await detach_cdp_bounded(cdp)
    return True
