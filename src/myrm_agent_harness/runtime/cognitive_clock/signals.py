"""Cooperative cancellation and pause probe signals for background cognitive tasks.

NOTE: canonical implementation lives in infra/cooperative_signals.py
(framework layer); re-exported here so existing runtime importers keep
working with a single shared singleton. New code should import from infra/.
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
