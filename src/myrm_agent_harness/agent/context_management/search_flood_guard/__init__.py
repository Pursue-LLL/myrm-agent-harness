# [INPUT]: None
# [OUTPUT]: FloodActionKind, FloodGuardConfig, FloodGuardDecision, FloodGuardStatus, MultiAgentSearchFloodGuardSuite, PerAgentSlidingWindowTracker, ProgressiveSoftCapGate, SlidingWindowBucket
# [POS]: agent/context_management/search_flood_guard/__init__.py

"""Multi-agent search flood guard and progressive soft-cap package.

[INPUT]
- None (Package root exports).

[OUTPUT]
- FloodActionKind: Enumeration of flow control dispositions.
- FloodGuardConfig: Configuration parameters for sliding windows and thresholds.
- FloodGuardDecision: Evaluation verdict on incoming search requests.
- FloodGuardStatus: Current rate status snapshot for an agent context.
- SlidingWindowBucket: State container tracking timestamped invocation events.
- PerAgentSlidingWindowTracker: Sliding window tracking engine isolating subagent contexts.
- ProgressiveSoftCapGate: Progressive result tapering and hard cooldown evaluation gate.
- MultiAgentSearchFloodGuardSuite: Unified facade coordinating search rate governance.

[POS]
Package entry point for search flood guard in context management.
"""

from __future__ import annotations

from .flood_guard_types import (
    FloodActionKind,
    FloodGuardConfig,
    FloodGuardDecision,
    FloodGuardStatus,
    SlidingWindowBucket,
)
from .multi_agent_search_flood_guard_suite import MultiAgentSearchFloodGuardSuite
from .per_agent_sliding_window_tracker import PerAgentSlidingWindowTracker
from .progressive_soft_cap_gate import ProgressiveSoftCapGate

__all__ = [
    "FloodActionKind",
    "FloodGuardConfig",
    "FloodGuardDecision",
    "FloodGuardStatus",
    "MultiAgentSearchFloodGuardSuite",
    "PerAgentSlidingWindowTracker",
    "ProgressiveSoftCapGate",
    "SlidingWindowBucket",
]
