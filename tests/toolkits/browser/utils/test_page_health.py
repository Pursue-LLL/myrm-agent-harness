"""Unit tests for bounded page health primitives (abort stalled navigation, liveness probe)."""

from __future__ import annotations

import asyncio
import time

import pytest

from myrm_agent_harness.toolkits.browser.exceptions import BrowserSessionError
from myrm_agent_harness.toolkits.browser.utils import page_health
from myrm_agent_harness.toolkits.browser.utils.page_health import (
    PageUnresponsiveError,
    abort_pending_navigation,
    probe_alive,
)
from tests.toolkits.browser._fake_pages import FakeCdp, FakePage

_FAST_S = 0.05
_HANG_BOUND_S = 1.0  # generous wall-clock ceiling for "returned within the (patched) bound"


@pytest.fixture(autouse=True)
def _short_bounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(page_health, "_ABORT_TIMEOUT_S", _FAST_S)
    monkeypatch.setattr(page_health, "_DETACH_TIMEOUT_S", _FAST_S)
    monkeypatch.setattr(page_health, "_PROBE_TIMEOUT_S", _FAST_S)


async def _elapsed(coro) -> float:
    started = time.monotonic()
    await coro
    return time.monotonic() - started


def test_page_unresponsive_error_is_a_session_error() -> None:
    assert issubclass(PageUnresponsiveError, BrowserSessionError)


class TestAbortPendingNavigation:
    async def test_stops_loading_over_cdp_and_detaches(self) -> None:
        cdp = FakeCdp()
        page = FakePage(cdp=cdp)

        await abort_pending_navigation(page)  # type: ignore[arg-type]

        assert cdp.sent == ["Page.stopLoading"]
        assert cdp.detach_called
        assert page.evaluated == []  # a healthy CDP path never touches the page itself

    async def test_falls_back_to_window_stop_when_cdp_is_unsupported(self) -> None:
        page = FakePage(cdp=None)

        await abort_pending_navigation(page)  # type: ignore[arg-type]

        assert page.evaluated == ["window.stop()"]

    async def test_stalled_cdp_answer_is_bounded_and_never_touches_the_wedged_page(self) -> None:
        cdp = FakeCdp(send="hang")
        page = FakePage(cdp=cdp, evaluate="hang")

        elapsed = await _elapsed(abort_pending_navigation(page))  # type: ignore[arg-type]

        assert elapsed < _HANG_BOUND_S
        assert cdp.detach_called  # the session is released even though the command never answered
        assert page.evaluated == []  # window.stop() on a wedged page would hang with no bound of its own

    async def test_hanging_detach_is_bounded(self) -> None:
        page = FakePage(cdp=FakeCdp(detach="hang"))

        elapsed = await _elapsed(abort_pending_navigation(page))  # type: ignore[arg-type]

        assert elapsed < _HANG_BOUND_S

    async def test_fallback_evaluate_is_bounded_and_errors_are_swallowed(self) -> None:
        hanging = FakePage(cdp=None, evaluate="hang")
        failing = FakePage(cdp=None, evaluate="raise")

        assert await _elapsed(abort_pending_navigation(hanging)) < _HANG_BOUND_S  # type: ignore[arg-type]
        await abort_pending_navigation(failing)  # type: ignore[arg-type]  # must not raise

    async def test_caller_cancellation_propagates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(page_health, "_ABORT_TIMEOUT_S", 10.0)
        page = FakePage(cdp=FakeCdp(send="hang"))
        task = asyncio.create_task(abort_pending_navigation(page))  # type: ignore[arg-type]
        await asyncio.sleep(_FAST_S)

        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


class TestProbeAlive:
    async def test_healthy_page(self) -> None:
        page = FakePage(cdp=None)

        assert await probe_alive(page)  # type: ignore[arg-type]
        assert page.evaluated == ["1"]

    async def test_closed_page_is_dead(self) -> None:
        page = FakePage(cdp=None, closed=True)

        assert not await probe_alive(page)  # type: ignore[arg-type]

    async def test_failing_evaluate_is_dead(self) -> None:
        page = FakePage(cdp=None, evaluate="raise")

        assert not await probe_alive(page)  # type: ignore[arg-type]

    async def test_hanging_evaluate_is_dead_within_the_bound(self) -> None:
        page = FakePage(cdp=None, evaluate="hang")

        started = time.monotonic()
        alive = await probe_alive(page)  # type: ignore[arg-type]

        assert not alive
        assert time.monotonic() - started < _HANG_BOUND_S
