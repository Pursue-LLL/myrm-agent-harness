"""Real-Chromium proof that closing or restarting one session leaves a shared context alone.

A custom agent's chats share one browser context (`agent_<id>`), so one chat's session teardown
(idle eviction, chat deletion) or restart (engine switch) runs while another chat still has tabs open
in it. Every scenario has a control group (a session that owns its context alone) so a pass cannot be
an artifact of the setup. Run with:
`pytest -m integration tests/toolkits/browser/session/test_shared_context_close.py`.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator

import pytest
from patchright.async_api import Page

from myrm_agent_harness.toolkits.browser.pool import ContextType, GlobalBrowserPool
from myrm_agent_harness.toolkits.browser.session import BrowserSession
from tests.toolkits.browser._browser_available import chromium_available

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.asyncio,
    pytest.mark.skipif(not chromium_available(), reason="Chromium not available"),
]

_SHARED_KEY = "agent_shared"
_LOGIN_COOKIE = {"name": "login", "value": "1", "url": "https://example.com"}
_PAGE_STATE = 7
_TEARDOWN_BOUND_S = 20.0


@pytest.fixture
async def pool() -> AsyncIterator[GlobalBrowserPool]:
    browser_pool = GlobalBrowserPool(max_browsers=1)
    yield browser_pool
    with contextlib.suppress(Exception):
        await asyncio.wait_for(browser_pool.shutdown(), timeout=_TEARDOWN_BOUND_S)


async def _open(pool: GlobalBrowserPool, *, context_key: str = _SHARED_KEY) -> BrowserSession:
    session = BrowserSession(pool, ContextType.AGENT, context_key=context_key, allow_private_networks=True)
    await session.new_tab()
    return session


def _page(session: BrowserSession) -> Page:
    return session._tab_controller.get_active_page()


def _context_alive(pool: GlobalBrowserPool, context_key: str) -> bool:
    return any(context_key in inst.contexts for inst in pool._browsers)


async def _log_in(session: BrowserSession) -> None:
    """Leave a login cookie and in-page state in the session's context."""
    page = _page(session)
    await page.context.add_cookies([_LOGIN_COOKIE])
    await page.evaluate(f"window.__state = {_PAGE_STATE}")


async def _survives(page: Page) -> bool:
    """True when the page is open, answers, kept its in-page state and its context kept the login cookie."""
    if page.is_closed():
        return False
    state = await page.evaluate("window.__state")
    cookies = await page.context.cookies()
    return state == _PAGE_STATE and any(cookie["name"] == "login" for cookie in cookies)


class TestClose:
    async def test_closing_one_chat_keeps_the_pages_and_cookies_of_the_other(self, pool: GlobalBrowserPool) -> None:
        first, second = await _open(pool), await _open(pool)
        await _log_in(second)

        await first.close()

        assert await _survives(_page(second))
        assert _context_alive(pool, _SHARED_KEY)

    async def test_the_last_chat_out_destroys_the_shared_context(self, pool: GlobalBrowserPool) -> None:
        first, second = await _open(pool), await _open(pool)

        await first.close()
        assert _context_alive(pool, _SHARED_KEY)
        await second.close()

        assert not _context_alive(pool, _SHARED_KEY)

    async def test_a_chat_that_owns_its_context_alone_destroys_it(self, pool: GlobalBrowserPool) -> None:
        """Control: the cleanup still happens when nobody else holds the context."""
        session = await _open(pool)

        await session.close()

        assert not _context_alive(pool, _SHARED_KEY)


class TestRestart:
    async def test_restarting_one_chat_keeps_the_other_chat_and_stays_in_the_shared_context(
        self, pool: GlobalBrowserPool
    ) -> None:
        first, second = await _open(pool), await _open(pool)
        await _log_in(first)
        first_page = _page(first)

        await second.restart(restore_url=False)

        assert await _survives(first_page)
        assert _page(second).context is first_page.context

    async def test_restarting_a_chat_that_owns_its_context_alone_rebuilds_it(self, pool: GlobalBrowserPool) -> None:
        """Control: the engine restart still starts from a fresh context, under the same key."""
        session = await _open(pool)
        await _log_in(session)
        old_context = _page(session).context

        await session.restart(restore_url=False)

        assert _page(session).context is not old_context
        assert _context_alive(pool, _SHARED_KEY)
        await session.close()
        assert not _context_alive(pool, _SHARED_KEY)
