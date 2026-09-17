"""Tests for pure harness cognitive clock runtime primitives."""

from __future__ import annotations

import pytest

from myrm_agent_harness.runtime.cognitive_clock.bus import (
    CognitiveClockBus,
)
from myrm_agent_harness.runtime.cognitive_clock.cadence import (
    CognitiveCadence,
    CognitiveClockTaskSpec,
    CognitiveClockTickEvent,
)
from myrm_agent_harness.runtime.cognitive_clock.signals import (
    CooperativePauseSignal,
    get_global_pause_signal,
)


@pytest.mark.asyncio
async def test_cognitive_clock_bus_dispatch() -> None:
    bus = CognitiveClockBus()
    invoked: list[str] = []

    async def sample_handler(event: CognitiveClockTickEvent, pause_signal: CooperativePauseSignal) -> None:
        invoked.append(event.cadence.value)

    spec = CognitiveClockTaskSpec(
        task_id="t2_test_task",
        cadence=CognitiveCadence.T2_MACRO_IDLE,
        name="T2 Idle Test",
        description="Test task for T2 idle tick",
        interval_seconds=3600.0,
    )
    bus.register_task(spec, sample_handler)

    # Dispatch T2
    await bus.emit_tick(CognitiveCadence.T2_MACRO_IDLE)
    assert invoked == ["t2_macro_idle"]

    # Dispatch T1 should not trigger T2 task
    await bus.emit_tick(CognitiveCadence.T1_MESO_SESSION)
    assert invoked == ["t2_macro_idle"]


@pytest.mark.asyncio
async def test_cognitive_clock_bus_pauses_on_signal() -> None:
    bus = CognitiveClockBus()
    executed = False

    async def dummy_handler(event: CognitiveClockTickEvent, pause_signal: CooperativePauseSignal) -> None:
        nonlocal executed
        executed = True

    spec = CognitiveClockTaskSpec(
        task_id="t3_task",
        cadence=CognitiveCadence.T3_EPOCH_MACRO,
        name="T3 Weekly Discovery",
        description="Weekly task",
        interval_seconds=604800.0,
    )
    bus.register_task(spec, dummy_handler)

    signal = get_global_pause_signal()
    signal.request_pause("heavy load")
    try:
        await bus.emit_tick(CognitiveCadence.T3_EPOCH_MACRO)
        # Handler should be skipped because of pause signal
        assert executed is False
    finally:
        signal.clear()
