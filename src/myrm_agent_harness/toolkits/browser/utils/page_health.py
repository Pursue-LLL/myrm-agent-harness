"""Bounded page health primitives: abort a stalled navigation, probe liveness.

[INPUT]
- patchright.async_api::Page, CDPSession (POS: page under inspection and its protocol session)
- exceptions::BrowserSessionError (POS: base of PageUnresponsiveError)

[OUTPUT]
- PageUnresponsiveError: a page stopped answering protocol commands and cannot be reused
- abort_pending_navigation: stop an in-flight navigation without blocking on a stalled page
- probe_alive: bounded liveness check of a page

[POS]
Shared by navigation (timeout settlement, SSRF route teardown), pool (idle page reuse) and
session recovery (tab healing). A main frame stuck in a stalled navigation or a spinning renderer
leaves page-level commands (`evaluate`, `unroute`, `close`) hanging with no timeout of their own,
so every call here carries its own bound. `Page.stopLoading` is the one command the browser keeps
answering in that state, which is why it is issued before anything else.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from ..exceptions import BrowserSessionError

if TYPE_CHECKING:
    from patchright.async_api import CDPSession, Page

_ABORT_TIMEOUT_S = 1.0
_DETACH_TIMEOUT_S = 1.0
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
            with contextlib.suppress(Exception):
                await asyncio.wait_for(cdp.detach(), timeout=_DETACH_TIMEOUT_S)


async def probe_alive(page: Page) -> bool:
    """True when the page is open and answers a trivial evaluation within the probe bound."""
    if page.is_closed():
        return False
    try:
        await asyncio.wait_for(page.evaluate("1"), timeout=_PROBE_TIMEOUT_S)
    except Exception:
        return False
    return True
