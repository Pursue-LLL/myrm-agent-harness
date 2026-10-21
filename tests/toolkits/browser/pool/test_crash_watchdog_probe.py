"""Decision logic of the browser liveness probe in `crash_watchdog.py`.

The browser process is probed over a browser-level CDP session first; pooled pages are only
a second opinion. A slow or wedged page therefore never evicts a live browser, while a browser
that answers on neither path is still declared dead.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool.browser_launcher import BrowserInstance
from myrm_agent_harness.toolkits.browser.pool.crash_watchdog import CrashWatchdogMixin
from myrm_agent_harness.toolkits.browser.utils import page_health

_check = CrashWatchdogMixin._check_browser_alive


def _browser(*, process_answers: bool) -> MagicMock:
    """Browser mock whose browser-level CDP session either answers or fails."""
    browser = MagicMock()
    cdp = MagicMock()
    cdp.send = AsyncMock(return_value={"product": "Chrome"})
    cdp.detach = AsyncMock()
    if process_answers:
        browser.new_browser_cdp_session = AsyncMock(return_value=cdp)
    else:
        browser.new_browser_cdp_session = AsyncMock(side_effect=RuntimeError("no browser session"))
    browser.cdp = cdp
    return browser


def _page(*, answers: bool) -> MagicMock:
    page = MagicMock()
    if answers:
        page.evaluate = AsyncMock(return_value=1)
    else:
        page.evaluate = AsyncMock(side_effect=RuntimeError("page does not answer"))
    return page


def _instance(browser: MagicMock, *pages: MagicMock) -> BrowserInstance:
    inst = BrowserInstance(browser=browser, is_managed=True)
    pool = MagicMock()
    pool._busy = set(pages)
    pool._idle = []
    inst.page_pools = {"agent": pool}
    return inst


async def test_process_answer_is_enough_even_when_every_page_is_wedged() -> None:
    """A page stuck in navigation must not read as a dead browser."""
    wedged = _page(answers=False)
    inst = _instance(_browser(process_answers=True), wedged)

    assert await _check(inst) is True
    wedged.evaluate.assert_not_awaited()  # the page-level probe is never needed


async def test_process_probe_releases_its_cdp_session() -> None:
    browser = _browser(process_answers=True)

    assert await _check(_instance(browser)) is True
    browser.cdp.send.assert_awaited_once_with("Browser.getVersion")
    browser.cdp.detach.assert_awaited_once()


async def test_page_answer_is_second_opinion_when_process_probe_fails() -> None:
    """Engines without a browser-level endpoint (Firefox) keep the page-level verdict."""
    inst = _instance(_browser(process_answers=False), _page(answers=False), _page(answers=True))

    assert await _check(inst) is True


async def test_dead_when_neither_process_nor_pages_answer() -> None:
    inst = _instance(_browser(process_answers=False), _page(answers=False))

    assert await _check(inst) is False


async def test_trusted_alive_without_pages_when_process_probe_fails() -> None:
    """With nothing to ask, only the synchronous L1 'disconnected' event may declare death."""
    assert await _check(_instance(_browser(process_answers=False))) is True


async def test_process_probe_timeout_falls_back_to_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_health, "_PROBE_TIMEOUT_S", 0.05)
    browser = MagicMock()

    async def hang() -> None:
        await asyncio.sleep(30)

    browser.new_browser_cdp_session = hang
    inst = _instance(browser, _page(answers=False))

    assert await asyncio.wait_for(_check(inst), timeout=5) is False


async def test_cancellation_during_process_probe_propagates() -> None:
    browser = MagicMock()
    browser.new_browser_cdp_session = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _check(_instance(browser, _page(answers=True)))
