"""Nested Learning Multi-Frequency Cognitive Clock Framework Primitives.

[INPUT]
- .cadence::CognitiveCadence, CognitiveClockTaskSpec, CognitiveClockTickEvent
- .signals::CooperativePauseSignal, PauseRequestedError, get_global_pause_signal
- .bus::CognitiveClockBus, get_cognitive_clock_bus

[OUTPUT]
- Public exports for harness-level cognitive clock scheduling and backoff probes.

[POS]
Harness runtime tier. Provides HOPE 4-frequency clock specifications (T0-T3)
and non-blocking transaction-boundary cooperative pause probes.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.cognitive_clock.bus import (
    CognitiveClockBus,
    get_cognitive_clock_bus,
)
from myrm_agent_harness.runtime.cognitive_clock.cadence import (
    CognitiveCadence,
    CognitiveClockTaskSpec,
    CognitiveClockTickEvent,
)
from myrm_agent_harness.runtime.cognitive_clock.signals import (
    CooperativePauseSignal,
    PauseRequestedError,
    get_global_pause_signal,
)

__all__ = [
    "CognitiveCadence",
    "CognitiveClockTaskSpec",
    "CognitiveClockTickEvent",
    "CognitiveClockBus",
    "get_cognitive_clock_bus",
    "CooperativePauseSignal",
    "PauseRequestedError",
    "get_global_pause_signal",
]
