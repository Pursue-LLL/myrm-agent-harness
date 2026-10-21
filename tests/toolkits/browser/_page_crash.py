"""Crash a real page's renderer for browser integration tests.

[INPUT]
- patchright.async_api::Page (POS: the page whose renderer is killed)
- pool::GlobalBrowserPool (POS: its crash tasks are awaited so accounting has settled before the test asserts)

[OUTPUT]
- crash_page: kill the renderer and wait until the pool's crash handler has finished with the event

[POS]
`chrome://crash` kills the renderer exactly as a real out-of-memory or GPU failure does: the Page
object stays, `is_closed()` stays False and every call on it fails at once. No mock reproduces that.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patchright.async_api import Page

    from myrm_agent_harness.toolkits.browser.pool import GlobalBrowserPool

_CRASH_URL = "chrome://crash"
_CRASH_NAVIGATION_TIMEOUT_MS = 5_000
_CRASH_EVENT_TIMEOUT_S = 10.0


async def crash_page(pool: GlobalBrowserPool, page: Page) -> None:
    """Crash the page's renderer and wait until the pool's crash handler has finished with the event."""
    crashed = asyncio.Event()
    page.on("crash", lambda _page: crashed.set())  # registered after the pool's own listener
    with contextlib.suppress(Exception):
        await page.goto(_CRASH_URL, timeout=_CRASH_NAVIGATION_TIMEOUT_MS)
    await asyncio.wait_for(crashed.wait(), _CRASH_EVENT_TIMEOUT_S)
    await asyncio.gather(*pool._crash_tasks)
