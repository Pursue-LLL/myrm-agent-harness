"""Public surface of the context guard subsystem.

[INPUT]
- None at import time; re-exports the engine, sweeper and config/payload types

[OUTPUT]
- SpilloverEngine: atomic extraction of oversized payloads into referenced files
- EphemeralTransientSweeper: TTL cleanup for ephemeral spillover files
- ContextGuardConfig, SpilloverPayload, SpilloverResult, estimate_token_pressure

[POS]
Package entry point for context safety. Import from here rather than from the individual
modules so the internal layout stays free to change. Framework-level: keeps the agent run
alive by converting context bombs into file references instead of dropping them.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine
from myrm_agent_harness.agent.context_guard.sweeper import EphemeralTransientSweeper
from myrm_agent_harness.agent.context_guard.types import (
    ContextGuardConfig,
    SpilloverPayload,
    SpilloverResult,
    estimate_token_pressure,
)

__all__ = [
    "ContextGuardConfig",
    "EphemeralTransientSweeper",
    "SpilloverEngine",
    "SpilloverPayload",
    "SpilloverResult",
    "estimate_token_pressure",
]
