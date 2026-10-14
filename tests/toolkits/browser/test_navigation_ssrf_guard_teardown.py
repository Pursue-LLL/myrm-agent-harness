"""A guarded navigation that fails, is cancelled or hits a wedged page always tears down its route."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from myrm_agent_harness.toolkits.browser.navigation.ssrf_guard import goto_with_ssrf_guard


def _guarded_page_whose_goto(behavior) -> AsyncMock:
    page = AsyncMock()
    page.goto.side_effect = behavior
    page.url = "https://example.com/"
    return page


async def test_goto_with_ssrf_guard_aborts_pending_navigation_on_failure() -> None:
    """A failed navigation is stopped at the protocol level before the error propagates."""
    page = _guarded_page_whose_goto(TimeoutError("Navigation timeout"))

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.abort_pending_navigation",
            new_callable=AsyncMock,
        ) as mock_abort,
        pytest.raises(TimeoutError),
    ):
        await goto_with_ssrf_guard(page, "https://example.com/", timeout_ms=1000)

    mock_abort.assert_awaited_once_with(page)
    page.unroute.assert_awaited_once()


async def test_goto_with_ssrf_guard_aborts_pending_navigation_on_cancellation() -> None:
    """Cancelling the caller (agent Stop) also stops the stalled navigation instead of orphaning it."""

    async def stalled(*args: object, **kwargs: object) -> None:
        await asyncio.Event().wait()

    page = _guarded_page_whose_goto(stalled)

    with patch(
        "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.abort_pending_navigation",
        new_callable=AsyncMock,
    ) as mock_abort:
        task = asyncio.create_task(goto_with_ssrf_guard(page, "https://example.com/", timeout_ms=1000))
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    mock_abort.assert_awaited_once_with(page)


async def test_goto_with_ssrf_guard_unroute_on_wedged_page_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """`unroute` never answers on a page stuck in a stalled navigation; the guard must not hang on it."""
    from myrm_agent_harness.toolkits.browser.navigation import ssrf_guard

    monkeypatch.setattr(ssrf_guard, "_UNROUTE_TIMEOUT_S", 0.05)

    async def never_answers(*args: object, **kwargs: object) -> None:
        await asyncio.Event().wait()

    page = _guarded_page_whose_goto(TimeoutError("Navigation timeout"))
    page.unroute.side_effect = never_answers

    with (
        patch(
            "myrm_agent_harness.toolkits.browser.navigation.ssrf_guard.abort_pending_navigation",
            new_callable=AsyncMock,
        ),
        pytest.raises(TimeoutError, match="Navigation timeout"),  # the original error, not the unroute one
    ):
        await asyncio.wait_for(
            goto_with_ssrf_guard(page, "https://example.com/", timeout_ms=1000),
            timeout=1.0,
        )
