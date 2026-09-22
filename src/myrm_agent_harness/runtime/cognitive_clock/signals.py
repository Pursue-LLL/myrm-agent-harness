"""Re-export shim exposing the canonical cooperative pause signals at their runtime path.

[INPUT]
- infra.cooperative_signals::CooperativePauseSignal (POS: Infrastructure layer. Provides transaction-boundary cooperative yielding so background consolidation immediately yields SQLite write locks when foreground users type.)
- infra.cooperative_signals::PauseRequestedError (POS: Infrastructure layer. Cooperative-pause exception raised when a cognitive task is halted at a transaction boundary.)
- infra.cooperative_signals::get_global_pause_signal (POS: Infrastructure layer. Process-wide pause signal accessor.)

[OUTPUT]
- CooperativePauseSignal: Re-exported pause probe token
- PauseRequestedError: Re-exported cooperative-pause exception
- get_global_pause_signal: Re-exported process-wide signal accessor

[POS]
Runtime-path alias for the cooperative pause signals. Keeps the ``runtime.cognitive_clock``
import path stable while ``infra/cooperative_signals.py`` remains the single implementation.
"""

from __future__ import annotations

from myrm_agent_harness.infra.cooperative_signals import (
    CooperativePauseSignal as CooperativePauseSignal,
)
from myrm_agent_harness.infra.cooperative_signals import (
    PauseRequestedError as PauseRequestedError,
)
from myrm_agent_harness.infra.cooperative_signals import (
    get_global_pause_signal as get_global_pause_signal,
)

__all__ = [
    "CooperativePauseSignal",
    "PauseRequestedError",
    "get_global_pause_signal",
]
