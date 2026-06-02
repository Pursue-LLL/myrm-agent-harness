"""Tests for the async-context-bound failover emitter and ContextVar wiring."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from myrm_agent_harness.toolkits.llms.errors import FailoverReason
from myrm_agent_harness.toolkits.llms.fallback import (
    FailoverEmitter,
    FailoverEvent,
    ManagedLLM,
    RecoveryEvent,
    failover_emitter_ctx,
    get_active_failover_emitter,
    with_failover_emitter,
)


class _RecordingEmitter:
    """Minimal FailoverEmitter implementation used by tests."""

    def __init__(self, *, fail_on_emit: bool = False) -> None:
        self.failovers: list[FailoverEvent] = []
        self.recoveries: list[RecoveryEvent] = []
        self._fail_on_emit = fail_on_emit

    async def emit_failover(self, event: FailoverEvent) -> None:
        if self._fail_on_emit:
            raise RuntimeError("simulated emitter failure")
        self.failovers.append(event)

    async def emit_recovery(self, event: RecoveryEvent) -> None:
        if self._fail_on_emit:
            raise RuntimeError("simulated emitter failure")
        self.recoveries.append(event)


def test_recording_emitter_satisfies_protocol():
    """The helper must satisfy the public Protocol (runtime check)."""
    emitter = _RecordingEmitter()
    assert isinstance(emitter, FailoverEmitter)


@pytest.mark.asyncio
async def test_context_var_default_is_none():
    """No emitter is bound by default outside any with-block."""
    # Use a fresh task to avoid leakage from siblings.
    async def _probe() -> FailoverEmitter | None:
        return get_active_failover_emitter()

    result = await asyncio.create_task(_probe())
    assert result is None


@pytest.mark.asyncio
async def test_with_failover_emitter_binds_and_restores():
    """`with_failover_emitter` must bind on enter and restore on exit (even on error)."""
    emitter_a = _RecordingEmitter()
    emitter_b = _RecordingEmitter()

    assert get_active_failover_emitter() is None

    async with with_failover_emitter(emitter_a):
        assert get_active_failover_emitter() is emitter_a

        # Nested binding should stack and unwind correctly.
        async with with_failover_emitter(emitter_b):
            assert get_active_failover_emitter() is emitter_b
        assert get_active_failover_emitter() is emitter_a

    assert get_active_failover_emitter() is None

    # Exception path must still restore.
    with pytest.raises(RuntimeError):
        async with with_failover_emitter(emitter_a):
            assert get_active_failover_emitter() is emitter_a
            raise RuntimeError("boom")
    assert get_active_failover_emitter() is None


@pytest.mark.asyncio
async def test_concurrent_tasks_are_isolated():
    """Two concurrent tasks must each see only their own emitter."""
    emitter_a = _RecordingEmitter()
    emitter_b = _RecordingEmitter()

    seen_a: list[FailoverEmitter | None] = []
    seen_b: list[FailoverEmitter | None] = []

    async def _task(emitter: _RecordingEmitter, observed: list[FailoverEmitter | None]):
        async with with_failover_emitter(emitter):
            await asyncio.sleep(0.01)
            observed.append(get_active_failover_emitter())

    await asyncio.gather(_task(emitter_a, seen_a), _task(emitter_b, seen_b))

    assert seen_a == [emitter_a]
    assert seen_b == [emitter_b]
    assert get_active_failover_emitter() is None


def _build_failover_event() -> FailoverEvent:
    return FailoverEvent(
        from_model="gpt-4",
        to_model="claude-3-opus",
        reason=FailoverReason.RATE_LIMIT,
        error_message="rate limited",
        cooldown_ms=10_000,
        attempt_count=1,
        available_candidates=["gpt-4", "claude-3-opus"],
        scenario="balanced",
    )


def _build_recovery_event() -> RecoveryEvent:
    return RecoveryEvent(
        model="gpt-4",
        downtime_ms=15_000,
        probe_count=2,
        was_in_cooldown=True,
    )


@pytest.mark.asyncio
async def test_emitter_receives_failover_during_managed_llm_failover():
    """ManagedLLM real failover path must invoke the context-bound emitter."""
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    async def _fail(*args, **kwargs):
        raise Exception("rate limit reached")

    async def _ok(*args, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=HumanMessage(content="ok"))]
        )

    mock_main.agenerate = AsyncMock(side_effect=_fail)
    mock_fallback.agenerate = AsyncMock(side_effect=_ok)

    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
    )

    emitter = _RecordingEmitter()

    async with with_failover_emitter(emitter):
        result = await managed_llm.ainvoke([HumanMessage(content="hi")])

    assert result is not None
    assert len(emitter.failovers) == 1
    event = emitter.failovers[0]
    assert event.from_model == "gpt-4"
    assert event.to_model == "claude-3-opus"


@pytest.mark.asyncio
async def test_emitter_and_callback_both_fire():
    """A wired callback and an active emitter must both receive the event."""
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    async def _fail(*args, **kwargs):
        raise Exception("transient failure")

    async def _ok(*args, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=HumanMessage(content="ok"))]
        )

    mock_main.agenerate = AsyncMock(side_effect=_fail)
    mock_fallback.agenerate = AsyncMock(side_effect=_ok)

    callback_events: list[FailoverEvent] = []

    async def _callback(event: FailoverEvent) -> None:
        callback_events.append(event)

    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
        on_failover=_callback,
    )

    emitter = _RecordingEmitter()
    async with with_failover_emitter(emitter):
        await managed_llm.ainvoke([HumanMessage(content="hi")])

    assert len(callback_events) == 1
    assert len(emitter.failovers) == 1
    assert callback_events[0].from_model == emitter.failovers[0].from_model


@pytest.mark.asyncio
async def test_emitter_exception_does_not_break_request():
    """A misbehaving emitter must not crash the ManagedLLM call path."""
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    async def _fail(*args, **kwargs):
        raise Exception("transient failure")

    async def _ok(*args, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=HumanMessage(content="ok"))]
        )

    mock_main.agenerate = AsyncMock(side_effect=_fail)
    mock_fallback.agenerate = AsyncMock(side_effect=_ok)

    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
    )

    emitter = _RecordingEmitter(fail_on_emit=True)
    async with with_failover_emitter(emitter):
        result = await managed_llm.ainvoke([HumanMessage(content="hi")])

    # The transport-layer call still succeeds despite the emitter raising.
    assert result is not None


@pytest.mark.asyncio
async def test_emit_failover_invoked_directly():
    """Direct unit test: emit_failover must record the event."""
    emitter = _RecordingEmitter()
    event = _build_failover_event()
    await emitter.emit_failover(event)
    assert emitter.failovers == [event]


@pytest.mark.asyncio
async def test_emit_recovery_invoked_directly():
    """Direct unit test: emit_recovery must record the event."""
    emitter = _RecordingEmitter()
    event = _build_recovery_event()
    await emitter.emit_recovery(event)
    assert emitter.recoveries == [event]


@pytest.mark.asyncio
async def test_no_emitter_means_silent_path():
    """Without an emitter bound, the manager must not raise or crash."""
    mock_main = MagicMock()
    mock_fallback = MagicMock()

    async def _fail(*args, **kwargs):
        raise Exception("transient failure")

    async def _ok(*args, **kwargs):
        return ChatResult(
            generations=[ChatGeneration(message=HumanMessage(content="ok"))]
        )

    mock_main.agenerate = AsyncMock(side_effect=_fail)
    mock_fallback.agenerate = AsyncMock(side_effect=_ok)

    managed_llm = ManagedLLM(
        main_llm=mock_main,
        fallback_llm=mock_fallback,
        main_model_name="gpt-4",
        fallback_model_name="claude-3-opus",
    )

    # No ContextVar bound → no emitter side effects, request still succeeds.
    assert failover_emitter_ctx.get() is None
    result = await managed_llm.ainvoke([HumanMessage(content="hi")])
    assert result is not None
