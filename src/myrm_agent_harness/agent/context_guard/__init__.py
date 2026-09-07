"""Context guard subsystem for protecting LLM context windows against context bombs.

[INPUT]
- .types: ContextGuardConfig, SpilloverPayload, SpilloverResult
- .spillover_engine: SpilloverEngine
- .sweeper: EphemeralTransientSweeper

[OUTPUT]
- ContextGuardConfig
- SpilloverPayload
- SpilloverResult
- SpilloverEngine
- EphemeralTransientSweeper

[POS]
Harness-level context safety module providing automatic file spillover and cleanup.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine
from myrm_agent_harness.agent.context_guard.sweeper import EphemeralTransientSweeper
from myrm_agent_harness.agent.context_guard.types import (
    ContextGuardConfig,
    SpilloverPayload,
    SpilloverResult,
)

__all__ = [
    "ContextGuardConfig",
    "EphemeralTransientSweeper",
    "SpilloverEngine",
    "SpilloverPayload",
    "SpilloverResult",
]
