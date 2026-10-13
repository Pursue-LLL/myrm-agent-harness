"""Cooperative pause signals for the harness runtime tier.

[INPUT]
- .signals::CooperativePauseSignal, PauseRequestedError, get_global_pause_signal

[OUTPUT]
- Public exports for the non-blocking, transaction-boundary cooperative pause probes.

[POS]
Harness runtime tier. Provides non-blocking transaction-boundary cooperative pause probes.
"""

from __future__ import annotations

from myrm_agent_harness.runtime.cognitive_clock.signals import (
    CooperativePauseSignal,
    PauseRequestedError,
    get_global_pause_signal,
)

__all__ = [
    "CooperativePauseSignal",
    "PauseRequestedError",
    "get_global_pause_signal",
]
