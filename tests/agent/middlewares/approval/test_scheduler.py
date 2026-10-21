"""Tests for ApprovalTimeoutScheduler."""

from __future__ import annotations

import asyncio

import pytest

from myrm_agent_harness.agent.middlewares.approval.scheduler import ApprovalTimeoutScheduler


@pytest.fixture(autouse=True)
def _reset_singleton() -> None:
    ApprovalTimeoutScheduler._instance = None


@pytest.mark.asyncio
async def test_get_returns_singleton() -> None:
    a = ApprovalTimeoutScheduler.get()
    b = ApprovalTimeoutScheduler.get()
    assert a is b


@pytest.mark.asyncio
async def test_schedule_respects_resume_value_override() -> None:
    scheduler = ApprovalTimeoutScheduler.get()
    received: list[dict[str, object]] = []

    async def callback(resume_value: dict[str, object]) -> None:
        received.append(resume_value)

    override = {"no_answer": True}
    scheduler.schedule(
        "override-key",
        timeout_seconds=0.05,
        behavior="deny",
        resume_callback=callback,
        resume_value_override=override,
    )
    await asyncio.sleep(0.15)
    assert received == [override]
    assert "decision" not in received[0]


@pytest.mark.asyncio
async def test_schedule_fires_deny_callback() -> None:
    scheduler = ApprovalTimeoutScheduler.get()
    received: list[dict[str, object]] = []

    async def callback(resume_value: dict[str, object]) -> None:
        received.append(resume_value)

    scheduler.schedule("key-1", timeout_seconds=0.05, behavior="deny", resume_callback=callback)
    assert scheduler.pending_count == 1
    await asyncio.sleep(0.15)
    assert len(received) == 1
    assert received[0]["decision"] == "reject"
    assert "feedback" in received[0]


@pytest.mark.asyncio
async def test_schedule_fires_allow_callback() -> None:
    scheduler = ApprovalTimeoutScheduler.get()
    received: list[dict[str, object]] = []

    async def callback(resume_value: dict[str, object]) -> None:
        received.append(resume_value)

    scheduler.schedule("key-2", timeout_seconds=0.05, behavior="allow", resume_callback=callback)
    await asyncio.sleep(0.15)
    assert len(received) == 1
    assert received[0]["decision"] == "approve"
    assert "feedback" in received[0]


@pytest.mark.asyncio
async def test_cancel_prevents_callback() -> None:
    scheduler = ApprovalTimeoutScheduler.get()
    fired = False

    async def callback(resume_value: dict[str, object]) -> None:
        nonlocal fired
        fired = True

    scheduler.schedule("key-3", timeout_seconds=0.5, behavior="deny", resume_callback=callback)
    assert scheduler.cancel("key-3") is True
    await asyncio.sleep(0.1)
    assert not fired
    assert scheduler.pending_count == 0


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false() -> None:
    scheduler = ApprovalTimeoutScheduler.get()
    assert scheduler.cancel("nonexistent") is False


@pytest.mark.asyncio
async def test_cancel_all() -> None:
    scheduler = ApprovalTimeoutScheduler.get()

    async def noop(rv: dict[str, object]) -> None:
        pass

    scheduler.schedule("a", timeout_seconds=10, behavior="deny", resume_callback=noop)
    scheduler.schedule("b", timeout_seconds=10, behavior="deny", resume_callback=noop)
    assert scheduler.pending_count == 2
    count = scheduler.cancel_all()
    assert count == 2
    assert scheduler.pending_count == 0


@pytest.mark.asyncio
async def test_schedule_replaces_existing_key() -> None:
    scheduler = ApprovalTimeoutScheduler.get()
    calls: list[str] = []

    async def cb1(rv: dict[str, object]) -> None:
        calls.append("first")

    async def cb2(rv: dict[str, object]) -> None:
        calls.append("second")

    scheduler.schedule("dup", timeout_seconds=10, behavior="deny", resume_callback=cb1)
    scheduler.schedule("dup", timeout_seconds=0.05, behavior="deny", resume_callback=cb2)
    await asyncio.sleep(0.15)
    assert calls == ["second"]


@pytest.mark.asyncio
async def test_global_decision_compatible_with_batch_approval() -> None:
    """Verify resume_value uses global decision format compatible with batch approval.

    The middleware expands a global decision to all pending tools,
    so the scheduler must NOT use ``{"decisions": [...]}``.
    """
    scheduler = ApprovalTimeoutScheduler.get()
    received: list[dict[str, object]] = []

    async def callback(resume_value: dict[str, object]) -> None:
        received.append(resume_value)

    scheduler.schedule("batch-test", timeout_seconds=0.05, behavior="deny", resume_callback=callback)
    await asyncio.sleep(0.15)
    assert len(received) == 1
    rv = received[0]
    assert "decision" in rv, "Must use global decision format, not decisions list"
    assert "decisions" not in rv, "Must NOT contain decisions list"
    assert rv["decision"] == "reject"
    assert isinstance(rv["feedback"], str)


@pytest.mark.asyncio
async def test_callback_exception_does_not_crash() -> None:
    scheduler = ApprovalTimeoutScheduler.get()

    async def bad_callback(rv: dict[str, object]) -> None:
        raise RuntimeError("boom")

    scheduler.schedule("err", timeout_seconds=0.05, behavior="deny", resume_callback=bad_callback)
    await asyncio.sleep(0.15)
    assert scheduler.pending_count == 0


# --- Race condition protection (resolve_if_first) ---


@pytest.mark.asyncio
async def test_resolve_if_first_returns_true_once() -> None:
    scheduler = ApprovalTimeoutScheduler.get()

    async def noop(rv: dict[str, object]) -> None:
        pass

    scheduler.schedule("race-1", timeout_seconds=10, behavior="deny", resume_callback=noop)
    assert scheduler.resolve_if_first("race-1") is True
    assert scheduler.resolve_if_first("race-1") is False


@pytest.mark.asyncio
async def test_resolve_if_first_prevents_timeout_callback() -> None:
    """Manual resume wins the race — timeout callback must not fire."""
    scheduler = ApprovalTimeoutScheduler.get()
    fired = False

    async def callback(rv: dict[str, object]) -> None:
        nonlocal fired
        fired = True

    scheduler.schedule("race-2", timeout_seconds=0.05, behavior="deny", resume_callback=callback)
    assert scheduler.resolve_if_first("race-2") is True
    await asyncio.sleep(0.15)
    assert not fired


@pytest.mark.asyncio
async def test_timeout_wins_race_blocks_manual_resume() -> None:
    """Timeout fires first — subsequent manual resolve_if_first returns False."""
    scheduler = ApprovalTimeoutScheduler.get()
    received: list[dict[str, object]] = []

    async def callback(rv: dict[str, object]) -> None:
        received.append(rv)

    scheduler.schedule("race-3", timeout_seconds=0.05, behavior="deny", resume_callback=callback)
    await asyncio.sleep(0.15)
    assert len(received) == 1
    assert scheduler.resolve_if_first("race-3") is False


@pytest.mark.asyncio
async def test_schedule_resets_resolved_state() -> None:
    """Re-scheduling the same key clears the resolved state."""
    scheduler = ApprovalTimeoutScheduler.get()
    received: list[str] = []

    async def cb1(rv: dict[str, object]) -> None:
        received.append("first")

    async def cb2(rv: dict[str, object]) -> None:
        received.append("second")

    scheduler.schedule("reset-1", timeout_seconds=10, behavior="deny", resume_callback=cb1)
    assert scheduler.resolve_if_first("reset-1") is True

    scheduler.schedule("reset-1", timeout_seconds=0.05, behavior="deny", resume_callback=cb2)
    await asyncio.sleep(0.15)
    assert received == ["second"]


@pytest.mark.asyncio
async def test_cancel_all_clears_resolved_keys() -> None:
    scheduler = ApprovalTimeoutScheduler.get()

    async def noop(rv: dict[str, object]) -> None:
        pass

    scheduler.schedule("all-1", timeout_seconds=10, behavior="deny", resume_callback=noop)
    scheduler.resolve_if_first("all-1")
    scheduler.cancel_all()
    assert scheduler.resolve_if_first("all-1") is True


# --- The timer path must survive its own claim ---


@pytest.mark.asyncio
async def test_timeout_callback_runs_to_completion_across_awaits() -> None:
    """A real resume callback awaits I/O; the timer must not cancel itself while claiming the key."""
    scheduler = ApprovalTimeoutScheduler.get()
    stages: list[str] = []

    async def callback(rv: dict[str, object]) -> None:
        stages.append("started")
        await asyncio.sleep(0.02)
        stages.append("finished")

    scheduler.schedule("run-1", timeout_seconds=0.02, behavior="deny", resume_callback=callback)
    await asyncio.sleep(0.2)
    assert stages == ["started", "finished"]
    assert scheduler.pending_count == 0


@pytest.mark.asyncio
async def test_callback_can_schedule_next_timeout_for_same_key() -> None:
    """The resumed run may stop at a new interrupt and arm the next timer for the same key."""
    scheduler = ApprovalTimeoutScheduler.get()
    stages: list[str] = []

    async def second(rv: dict[str, object]) -> None:
        stages.append("second")

    async def first(rv: dict[str, object]) -> None:
        stages.append("first-started")
        scheduler.schedule("chain-1", timeout_seconds=10, behavior="deny", resume_callback=second)
        await asyncio.sleep(0.02)
        stages.append("first-finished")

    scheduler.schedule("chain-1", timeout_seconds=0.02, behavior="deny", resume_callback=first)
    await asyncio.sleep(0.2)
    assert stages == ["first-started", "first-finished"]
    assert scheduler.pending_count == 1

    # The newly armed timer keeps its handle, so a manual resume still cancels it.
    assert scheduler.resolve_if_first("chain-1") is True
    assert scheduler.pending_count == 0


@pytest.mark.asyncio
async def test_manual_resolve_cancels_pending_timer_but_timer_claim_does_not_cancel_itself() -> None:
    scheduler = ApprovalTimeoutScheduler.get()
    fired: list[str] = []

    async def callback(rv: dict[str, object]) -> None:
        fired.append("timer")
        await asyncio.sleep(0.02)
        fired.append("timer-done")

    scheduler.schedule("mix-1", timeout_seconds=0.02, behavior="deny", resume_callback=callback)
    scheduler.schedule("mix-2", timeout_seconds=10, behavior="deny", resume_callback=callback)
    assert scheduler.resolve_if_first("mix-2") is True
    await asyncio.sleep(0.2)
    assert fired == ["timer", "timer-done"]
    assert scheduler.pending_count == 0


# --- reopen: a fresh interrupt without a timer must accept its own resolution ---


@pytest.mark.asyncio
async def test_reopen_accepts_the_next_resolution() -> None:
    scheduler = ApprovalTimeoutScheduler.get()

    async def noop(rv: dict[str, object]) -> None:
        pass

    scheduler.schedule("reopen-1", timeout_seconds=10, behavior="deny", resume_callback=noop)
    assert scheduler.resolve_if_first("reopen-1") is True
    assert scheduler.resolve_if_first("reopen-1") is False

    scheduler.reopen("reopen-1")
    assert scheduler.resolve_if_first("reopen-1") is True
    assert scheduler.resolve_if_first("reopen-1") is False


@pytest.mark.asyncio
async def test_reopen_leaves_a_pending_timer_untouched() -> None:
    scheduler = ApprovalTimeoutScheduler.get()

    async def noop(rv: dict[str, object]) -> None:
        pass

    scheduler.schedule("reopen-2", timeout_seconds=10, behavior="deny", resume_callback=noop)
    scheduler.reopen("reopen-2")
    assert scheduler.pending_count == 1
    scheduler.cancel_all()
