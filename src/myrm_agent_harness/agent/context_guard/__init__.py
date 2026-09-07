"""Context guard subsystem for protecting LLM context window from message overflow and context bombs.

Exports SpilloverEngine, EphemeralTransientSweeper, and related schemas.
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
