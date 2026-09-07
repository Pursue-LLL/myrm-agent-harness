"""Deprecated compatibility alias redirecting to myrm_agent_harness.agent.context_guard.

[INPUT]
- myrm_agent_harness.agent.context_guard: SpilloverEngine, EphemeralTransientSweeper

[OUTPUT]
- TransparentSpilloverEngine: Alias to SpilloverEngine

[POS]
Harness compatibility bridge to context_guard.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine as TransparentSpilloverEngine
from myrm_agent_harness.agent.context_guard.sweeper import EphemeralTransientSweeper

__all__ = [
    "EphemeralTransientSweeper",
    "TransparentSpilloverEngine",
]
