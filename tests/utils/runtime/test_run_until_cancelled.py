"""run_until_cancelled: an operation blocked in a driver call is aborted once the request token fires."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import pytest

from myrm_agent_harness.utils.runtime import cancellation
from myrm_agent_harness.utils.runtime.cancellation import (
    CancellationToken,
    CancelReason,
    OperationCancelledError,
    run_until_cancelled,
    set_cancel_token,
)

_POLL_S = 0.02
_BOUND_S = 2.0  # wall-clock ceiling for "returned within the (patched) bounds"


@pytest.fixture(autouse=True)
def _fast_bounds(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(cancellation, "_POLL_INTERVAL_S", _POLL_S)
    monkeypatch.setattr(cancellation, "_ABORT_GRACE_S", 0.2)
    yield
    set_cancel_token(None)


async def _hang() -> None:
    await asyncio.Event().wait()


async def test_without_a_token_the_work_is_simply_awaited() -> None:
    set_cancel_token(None)

    async def work() -> str:
        return "done"

    assert await run_until_cancelled(work()) == "done"


async def test_result_is_returned_without_waiting_for_a_poll_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cancellation, "_POLL_INTERVAL_S", 30.0)
    set_cancel_token(CancellationToken("req"))

    async def work() -> str:
        return "done"

    started = time.monotonic()
    assert await run_until_cancelled(work()) == "done"
    assert time.monotonic() - started < _BOUND_S


async def test_work_exception_propagates_unchanged() -> None:
    set_cancel_token(CancellationToken("req"))

    async def work() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await run_until_cancelled(work())


async def test_token_fired_mid_run_aborts_work_that_never_returns() -> None:
    token = CancellationToken("req")
    set_cancel_token(token)
    cancelled_inside = asyncio.Event()

    async def work() -> None:
        try:
            await _hang()
        except asyncio.CancelledError:
            cancelled_inside.set()
            raise

    task = asyncio.create_task(run_until_cancelled(work()))
    await asyncio.sleep(_POLL_S * 3)
    assert not task.done()

    token.cancel(CancelReason.USER_CANCELLED)

    with pytest.raises(OperationCancelledError, match="user_cancelled"):
        await asyncio.wait_for(task, timeout=_BOUND_S)
    assert cancelled_inside.is_set(), "the work itself must be cancelled, not abandoned"


async def test_already_cancelled_token_never_starts_the_work() -> None:
    token = CancellationToken("req")
    token.cancel()
    set_cancel_token(token)
    started = False

    async def work() -> None:
        nonlocal started
        started = True

    with pytest.raises(OperationCancelledError):
        await run_until_cancelled(work())

    assert not started


async def test_work_that_ignores_cancellation_cannot_hold_the_caller_past_the_grace_period() -> None:
    token = CancellationToken("req")
    set_cancel_token(token)
    release = asyncio.Event()

    async def stubborn() -> None:
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                continue  # swallows the cancel, as a misbehaving driver call might

    task = asyncio.create_task(run_until_cancelled(stubborn()))
    await asyncio.sleep(_POLL_S * 2)
    token.cancel()

    started = time.monotonic()
    with pytest.raises(OperationCancelledError):
        await asyncio.wait_for(task, timeout=_BOUND_S)
    assert time.monotonic() - started < _BOUND_S
    release.set()


async def test_caller_cancellation_cancels_the_work_and_propagates() -> None:
    set_cancel_token(CancellationToken("req"))
    cancelled_inside = asyncio.Event()

    async def work() -> None:
        try:
            await _hang()
        except asyncio.CancelledError:
            cancelled_inside.set()
            raise

    task = asyncio.create_task(run_until_cancelled(work()))
    await asyncio.sleep(_POLL_S * 3)

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.wait_for(cancelled_inside.wait(), timeout=_BOUND_S)


async def test_work_inherits_the_callers_context() -> None:
    token = CancellationToken("req")
    set_cancel_token(token)

    async def work() -> CancellationToken | None:
        return cancellation.get_cancel_token()

    assert await run_until_cancelled(work()) is token
