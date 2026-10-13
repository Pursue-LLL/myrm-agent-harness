"""Active-tab recovery: a page that stopped answering is replaced, never handed to the next tool call.

Uses the real TabController and BrowserSession tab APIs over page doubles whose protocol commands
hang like a wedged page; the real-browser counterpart lives in the integration tests.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain.tools import tool
from langchain_core.tools import StructuredTool

from myrm_agent_harness.toolkits.browser.pool.browser_pool import ContextType
from myrm_agent_harness.toolkits.browser.pool.config import BrowserEngine
from myrm_agent_harness.toolkits.browser.session import browser_session_tab_mixin
from myrm_agent_harness.toolkits.browser.session.browser_session import BrowserSession
from myrm_agent_harness.toolkits.browser.tools.cancel_boundary import CANCELLED_RESULT, apply_cancel_boundary
from myrm_agent_harness.toolkits.browser.utils import page_health
from myrm_agent_harness.toolkits.browser.utils.page_health import PageUnresponsiveError
from myrm_agent_harness.toolkits.browser.utils.proxy_error import is_proxy_error
from myrm_agent_harness.utils.runtime import cancellation
from myrm_agent_harness.utils.runtime.cancellation import CancellationToken, set_cancel_token
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
        self.crashed: set[FakePage] = set()

    async def acquire_page(self, *_args: object, **_kwargs: object) -> tuple[FakePage, str]:
        if self.acquire_hangs:
            await asyncio.Event().wait()
        if self.acquire_error is not None:
            raise self.acquire_error
        return (self._queue.pop(0) if self._queue else FakePage(cdp=FakeCdp())), "ctx"

    async def release_page(self, page: FakePage, _context_key: str) -> None:
        self.released.append(page)

    def is_page_crashed(self, page: FakePage) -> bool:
        return page in self.crashed


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


async def test_replacement_leaves_a_one_time_notice_for_the_model() -> None:
    session, _ = await _session(FakePool(FakePage(cdp=FakeCdp(), evaluate="hang")))

    await session.recover_active_tab()

    notice = session.take_tab_reset_notice()
    assert notice is not None
    assert "reset to a blank page (tab1)" in notice
    assert session.take_tab_reset_notice() is None, "the model is told once, not on every later call"


async def test_no_notice_when_nothing_was_replaced() -> None:
    session, _ = await _session(FakePool(FakePage(cdp=FakeCdp())))

    await session.recover_active_tab()

    assert session.take_tab_reset_notice() is None


async def test_failed_recovery_leaves_no_notice() -> None:
    pool = FakePool(FakePage(cdp=FakeCdp(), evaluate="hang"))
    session, _ = await _session(pool)
    pool.acquire_error = RuntimeError("browser unavailable")

    await session.recover_active_tab()

    assert session.take_tab_reset_notice() is None


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
        session._ensure_components = AsyncMock()  # type: ignore[method-assign]
        TestNavigateHealsUnresponsivePage._bind_navigator(session, AsyncMock(side_effect=error))
        return session

    @staticmethod
    def _bind_navigator(session: BrowserSession, goto: AsyncMock) -> None:
        """Rebind the navigation components; a tab swap unbinds them and `_ensure_components` is stubbed here."""
        session._navigator = MagicMock(goto=goto)
        session._snapshot_manager = MagicMock()

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
        assert message.count("reset to a blank page") == 1
        assert session.take_tab_reset_notice() is None, "the error already said it; the next tool must not repeat it"
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

    async def test_loaded_page_makes_the_pending_notice_obsolete(self) -> None:
        session = await self._navigating_session(RuntimeError("unused"))
        assert await session.recover_active_tab() == "tab1"
        self._bind_navigator(session, AsyncMock(return_value=("Example", "https://x.test/", 200)))

        assert (await session.navigate("https://x.test/")).startswith("Navigated to https://x.test/")

        assert session.take_tab_reset_notice() is None

    async def test_failed_navigation_keeps_the_pending_notice(self) -> None:
        session = await self._navigating_session(RuntimeError("boom"))
        assert await session.recover_active_tab() == "tab1"
        self._bind_navigator(session, AsyncMock(side_effect=RuntimeError("boom")))

        with pytest.raises(RuntimeError, match="boom"):
            await session.navigate("https://x.test/")

        assert session.take_tab_reset_notice() is not None


def _hanging_tool(name: str, started: asyncio.Event) -> StructuredTool:
    @tool(name)
    async def hang_tool(value: str) -> str:
        """Blocks like a driver call that never returns."""
        started.set()
        await asyncio.Event().wait()
        return value

    return hang_tool


def _echo_tool() -> StructuredTool:
    @tool("echo_tool")
    async def echo_tool(value: str) -> str:
        """Echo."""
        return f"echo:{value}"

    return echo_tool


class TestCancelBoundaryOnARealSession:
    """The boundary heals and informs through the real session, not through a double."""

    @pytest.fixture(autouse=True)
    def _fast_cancellation(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        monkeypatch.setattr(cancellation, "_POLL_INTERVAL_S", 0.02)
        monkeypatch.setattr(cancellation, "_ABORT_GRACE_S", 0.2)
        yield
        set_cancel_token(None)

    async def test_stopped_run_heals_the_tab_and_the_next_result_says_so_once(self) -> None:
        started = asyncio.Event()
        session, _ = await _session(FakePool(FakePage(cdp=FakeCdp(), evaluate="hang")))
        stuck, echo = apply_cancel_boundary([_hanging_tool("stuck_tool", started), _echo_tool()], session)
        token = CancellationToken("req")
        set_cancel_token(token)

        running = asyncio.create_task(stuck.ainvoke({"value": "x"}))
        await asyncio.wait_for(started.wait(), timeout=_BOUND_S)
        token.cancel()
        assert await asyncio.wait_for(running, timeout=_BOUND_S) == CANCELLED_RESULT
        set_cancel_token(None)

        first = await echo.ainvoke({"value": "a"})
        second = await echo.ainvoke({"value": "a"})
        assert first.startswith("The tab was reset to a blank page (tab1)")
        assert first.endswith("echo:a")
        assert second == "echo:a"

    async def test_timeout_without_a_stop_heals_the_wedged_tab(self) -> None:
        started = asyncio.Event()
        wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
        session, _ = await _session(FakePool(wedged))
        (stuck,) = apply_cancel_boundary([_hanging_tool("stuck_tool", started)], session)
        set_cancel_token(CancellationToken("req"))

        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.2):
                await stuck.ainvoke({"value": "x"})

        assert wedged.closed
        assert session.list_tabs() == ["tab1"]

    async def test_heal_that_runs_out_of_budget_cannot_swallow_the_cancellation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        started = asyncio.Event()
        pool = FakePool(FakePage(cdp=FakeCdp(), evaluate="hang"))
        session, _ = await _session(pool)
        monkeypatch.setattr(browser_session_tab_mixin, "_RECOVERY_BUDGET_S", 0.2)
        pool.acquire_hangs = True  # the replacement never arrives, so the heal hits its own budget
        (stuck,) = apply_cancel_boundary([_hanging_tool("stuck_tool", started)], session)
        set_cancel_token(CancellationToken("req"))

        running = asyncio.create_task(stuck.ainvoke({"value": "x"}))
        await asyncio.wait_for(started.wait(), timeout=_BOUND_S)
        running.cancel()

        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(running, timeout=_BOUND_S)

    async def test_two_tools_cancelled_together_replace_the_tab_once(self) -> None:
        both_started = [asyncio.Event(), asyncio.Event()]
        wedged = FakePage(cdp=FakeCdp(), evaluate="hang")
        pool = FakePool(wedged)
        session, _ = await _session(pool)
        first, second = apply_cancel_boundary(
            [_hanging_tool("stuck_a", both_started[0]), _hanging_tool("stuck_b", both_started[1])], session
        )
        set_cancel_token(CancellationToken("req"))

        running = [asyncio.create_task(t.ainvoke({"value": "x"})) for t in (first, second)]
        await asyncio.wait_for(asyncio.gather(*(e.wait() for e in both_started)), timeout=_BOUND_S)
        for task in running:
            task.cancel()
        results = await asyncio.wait_for(asyncio.gather(*running, return_exceptions=True), timeout=_BOUND_S)

        assert all(isinstance(r, asyncio.CancelledError) for r in results)
        assert wedged.close_calls == 1
        assert pool.released == [wedged]
        assert session.list_tabs() == ["tab1"], "one replacement tab, not one per cancelled tool"

    async def test_a_crashed_active_tab_is_replaced_before_the_tool_runs_and_the_result_says_so(self) -> None:
        crashed = FakePage(cdp=FakeCdp(), evaluate="raise")
        pool = FakePool(crashed)
        pool.crashed.add(crashed)
        session, _ = await _session(pool)
        (echo,) = apply_cancel_boundary([_echo_tool()], session)

        first = await echo.ainvoke({"value": "a"})
        second = await echo.ainvoke({"value": "a"})

        assert first.startswith("The tab was reset to a blank page (tab1)")
        assert first.endswith("echo:a")
        assert second == "echo:a"
        assert crashed.closed
        assert session.list_tabs() == ["tab1"]

    async def test_control_a_page_the_browser_did_not_report_as_crashed_is_not_probed_at_entry(self) -> None:
        flaky = FakePage(cdp=FakeCdp(), evaluate="raise")
        session, _ = await _session(FakePool(flaky))
        (echo,) = apply_cancel_boundary([_echo_tool()], session)

        assert await echo.ainvoke({"value": "a"}) == "echo:a"

        assert not flaky.closed
        assert flaky.evaluated == []
        assert session.list_tabs() == ["tab0"]

    async def test_a_crashed_tab_the_user_is_driving_is_left_alone(self) -> None:
        crashed = FakePage(cdp=FakeCdp(), evaluate="raise")
        pool = FakePool(crashed)
        pool.crashed.add(crashed)
        session, _ = await _session(pool)
        session._user_takeover_active = True
        (echo,) = apply_cancel_boundary([_echo_tool()], session)

        assert await echo.ainvoke({"value": "a"}) == "echo:a"

        assert not crashed.closed
        assert session.list_tabs() == ["tab0"]
