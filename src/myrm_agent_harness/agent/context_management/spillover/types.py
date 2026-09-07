"""Deprecated compatibility alias redirecting to myrm_agent_harness.agent.context_guard.types.

[INPUT]
- myrm_agent_harness.agent.context_guard.types

[OUTPUT]
- SpilloverConfig, SpilloverPayload, SpilloverResult

[POS]
Harness compatibility bridge to context_guard.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_guard.types import (
    ContextGuardConfig as SpilloverConfig,
    SpilloverPayload,
    SpilloverResult,
)

__all__ = [
    "SpilloverConfig",
    "SpilloverPayload",
    "SpilloverResult",
]
