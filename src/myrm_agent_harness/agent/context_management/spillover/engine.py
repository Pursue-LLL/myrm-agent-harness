"""Context management spillover alias pointing to context_guard SSOT.

[INPUT]
- myrm_agent_harness.agent.context_guard

[OUTPUT]
- TransparentSpilloverEngine (alias for SpilloverEngine)
- SpilloverConfig (alias for ContextGuardConfig)
- SpilloverPayload
- SpilloverResult

[POS]
Compatibility layer redirecting legacy imports to context_guard.
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_guard.spillover_engine import SpilloverEngine as TransparentSpilloverEngine
from myrm_agent_harness.agent.context_guard.types import (
    ContextGuardConfig as SpilloverConfig,
    SpilloverPayload,
    SpilloverResult,
)

__all__ = [
    "SpilloverConfig",
    "SpilloverPayload",
    "SpilloverResult",
    "TransparentSpilloverEngine",
]
