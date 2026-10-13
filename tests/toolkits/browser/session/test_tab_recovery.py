"""Active-tab recovery: a page that stopped answering is replaced, never handed to the next tool call.

Uses the real TabController and BrowserSession tab APIs over page doubles whose protocol commands
hang like a wedged page; the real-browser counterpart lives in the integration tests.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
from myrm_agent_harness.toolkits.browser.session import browser_session_tab_mixin
from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession
from myrm_agent_harness.toolkits.browser.utils import page_health
from myrm_agent_harness.toolkits.browser.utils.page_health import PageUnresponsiveError
from myrm_agent_harness.toolkits.browser.utils.proxy_error import is_proxy_error
from tests.toolkits.browser._fake_pages import FakeCdp, FakePage

_FAST_S = 0.1
_BOUND_S = 2.0  # wall-clock ceiling for "returned within the (patched) bound"


class FakePool:
    """Browser pool double handing out queued pages (then healthy ones)."""

    def __init__(self, *pages: FakePage) -> None:
        self._queue = list(pages)
        self.released: list[FakePage] = []
        self.acquire_error: Exception | None = None
        self.acquire_hangs = False

    async def acquire_page(self, *_args: object, **_kwargs: object) -> tuple[FakePage, str]:
        if self.acquire_hangs:
            await asyncio.Event().wait()
        if self.acquire_error is not None:
            raise self.acquire_error
        return (self._queue.pop(0) if self._queue else FakePage(cdp=FakeCdp())), "ctx"

    async def release_page(self, page: FakePage, _context_key: str) -> None:
        self.released.append(page)


@pytest.fixture(autouse=True)
def _short_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_health, "_ABORT_TIMEOUT_S", _FAST_S)
    monkeypatch.setattr(page_health, "_DETACH_TIMEOUT_S", _FAST_S)
    monkeypatch.setattr(page_health, "_PROBE_TIMEOUT_S", _FAST_S)
    monkeypatch.setattr(page_health, "_CLOSE_TIMEOUT_S", _FAST_S)
    monkeypatch.setattr(browser_session_tab_mixin, "_RECOVERY_BUDGET_S", 1.0)


async def _session(pool: FakePool) -> tuple[BrowserSession, list[FakePage]]:
    """Session with one open tab; returns it with the list of pages bound by `_initialize_components`."""
    session = BrowserSession(browser_pool=pool, context_type=ContextType.AGENT)  # type: ignore[arg-type]
    bound: list[FakePage] = []

    async def record_binding() -> None:
        bound.append(session._tab_controller.get_active_page())

    session._initialize_components = AsyncMock(side_effect=record_binding)  # type: ignore[method-assign]
    await session.new_tab()
    bound.clear()
    return session, bound


async def test_responsive_page_is_left_alone() -> None:
    page = FakePage(cdp=FakeCdp())
    session, bound = await _session(FakePool(page))

    assert await session.recover_active_tab() is None

    assert page.close_calls == 0
    assert session.list_tabs() == ["tab0"]
    assert bound == []


async def test_stalled_navigation_alone_is_stopped_without_replacing_the_tab() -> None:
    cdp = FakeCdp()
    page = FakePage(cdp=cdp)
    session, _ = await _session(FakePool(page))

    assert await session.recover_active_tab() is None

    assert cdp.sent == ["Page.stopLoading"]
    assert page.close_calls == 0


async def test_wedged_page_is_closed_and_the_tab_replaced() -> None:
    wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
    replacement = FakePage(cdp=FakeCdp())
    pool = FakePool(wedged, replacement)
    session, bound = await _session(pool)

    new_tab_id = await session.recover_active_tab()

    assert new_tab_id == "tab1"
    assert wedged.closed
    assert pool.released == [wedged]
    assert session.list_tabs() == ["tab1"]
    assert session.get_active_tab_id() == "tab1"
    assert session._tab_controller.get_active_page() is replacement
    assert bound == [replacement], "components must be rebound to the replacement page"


async def test_wedged_page_that_never_closes_is_still_replaced_within_the_bound() -> None:
    wedged = FakePage(cdp=FakeCdp(), evaluate="hang", close="hang")
    pool = FakePool(wedged)
    session, _ = await _session(pool)

    started = time.monotonic()
    new_tab_id = await session.recover_active_tab()

    assert time.monotonic() - started < _BOUND_S
    assert new_tab_id == "tab1"
    assert session.list_tabs() == ["tab1"]
    assert pool.released == [wedged]  # the pool probes and replaces it on the next acquire


async def test_other_tabs_survive_the_replacement() -> None:
    first = FakePage(cdp=FakeCdp())
    wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
    session, _ = await _session(FakePool(first, wedged))
    await session.new_tab()  # tab1, now active

    new_tab_id = await session.recover_active_tab()

    assert new_tab_id == "tab2"
    assert session.list_tabs() == ["tab0", "tab2"]
    assert first.close_calls == 0


async def test_user_takeover_blocks_recovery_without_touching_the_page() -> None:
    page = FakePage(cdp=FakeCdp(), evaluate="hang")
    session, _ = await _session(FakePool(page))
    await session.pause_for_takeover()

    assert await session.recover_active_tab() is None

    assert page.evaluated == []
    assert page.close_calls == 0
    assert session.list_tabs() == ["tab0"]


async def test_session_without_tabs_has_nothing_to_recover() -> None:
    session, _ = await _session(FakePool(FakePage(cdp=FakeCdp())))
    await session.close_tab("tab0")

    assert await session.recover_active_tab() is None


async def test_concurrent_callers_replace_the_tab_exactly_once() -> None:
    wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
    pool = FakePool(wedged)
    session, _ = await _session(pool)

    results = await asyncio.gather(session.recover_active_tab(), session.recover_active_tab())

    assert sorted(results, key=lambda r: r is not None) == [None, "tab1"]
    assert wedged.close_calls == 1
    assert pool.released == [wedged]
    assert session.list_tabs() == ["tab1"]


async def test_failed_replacement_is_swallowed_and_leaves_a_recoverable_session() -> None:
    wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
    pool = FakePool(wedged)
    session, _ = await _session(pool)
    pool.acquire_error = RuntimeError("browser unavailable")

    assert await session.recover_active_tab() is None

    # No tab left: `navigate` opens one on demand instead of failing on a missing tab.
    assert session.list_tabs() == []
    assert wedged.closed


async def test_recovery_is_bounded_when_the_pool_never_answers() -> None:
    wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
    pool = FakePool(wedged)
    session, _ = await _session(pool)
    pool.acquire_hangs = True

    started = time.monotonic()
    assert await session.recover_active_tab() is None

    assert time.monotonic() - started < _BOUND_S


async def test_cancellation_propagates_and_does_not_leave_the_lock_held() -> None:
    wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
    pool = FakePool(wedged)
    session, _ = await _session(pool)
    pool.acquire_hangs = True

    task = asyncio.create_task(session.recover_active_tab())
    await asyncio.sleep(0.3)  # inside create_tab, after the wedged tab was closed
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    pool.acquire_hangs = False
    assert await asyncio.wait_for(session.recover_active_tab(), timeout=_BOUND_S) is None
    assert session.list_tabs() == []


class TestNavigateHealsUnresponsivePage:
    @staticmethod
    async def _navigating_session(error: Exception) -> BrowserSession:
        session, _ = await _session(FakePool(FakePage(cdp=FakeCdp(), evaluate="hang"), FakePage(cdp=FakeCdp())))
        session._engine_preference = BrowserEngine.CHROMIUM_PATCHRIGHT  # skip the global engine-affinity lookup
        session._navigator = MagicMock()
        session._navigator.goto = AsyncMock(side_effect=error)
        session._snapshot_manager = MagicMock()
        session._ensure_components = AsyncMock()  # type: ignore[method-assign]
        return session

    async def test_wedged_page_is_replaced_and_the_error_says_so(self) -> None:
        original = PageUnresponsiveError("The page stopped responding while loading https://x.test/.")
        session = await self._navigating_session(original)
        navigator = session._navigator

        with pytest.raises(PageUnresponsiveError) as exc_info:
            await session.navigate("https://x.test/")

        message = str(exc_info.value)
        assert message.startswith(str(original))
        assert "reset to a blank page (tab1)" in message
        assert exc_info.value.__cause__ is original
        assert session.list_tabs() == ["tab1"]
        assert not is_proxy_error(exc_info.value), "wording must not trigger the proxy restart loop"
        navigator.goto.assert_awaited_once()  # fail fast: no retry against the same dead page

    async def test_failed_recovery_re_raises_the_original_error(self) -> None:
        original = PageUnresponsiveError("The page stopped responding while loading https://x.test/.")
        session = await self._navigating_session(original)
        session.recover_active_tab = AsyncMock(return_value=None)  # type: ignore[method-assign]

        with pytest.raises(PageUnresponsiveError) as exc_info:
            await session.navigate("https://x.test/")

        assert exc_info.value is original

    async def test_other_errors_do_not_trigger_recovery(self) -> None:
        session = await self._navigating_session(RuntimeError("boom"))
        session.recover_active_tab = AsyncMock(return_value="tab9")  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="boom"):
            await session.navigate("https://x.test/")

        session.recover_active_tab.assert_not_awaited()
