"""In-Flight Turn State Truncation and Prefix Cache Stability Gate Suite (Item 205).

Provides in-flight transient trial-and-error pruning, atomic canonical turn commits,
and provider prompt cache / KV cache prefix stability diagnosis.

[INPUT]
- agent.context_management.turn_truncation.turn_truncation_engine::TurnStateTruncationEngine (POS: Core engine
  for In-Flight Turn State Truncation and Prefix Cache Stability Gate.)
- agent.context_management.turn_truncation.turn_truncation_types::CanonicalTurnCommit, IntermediateTrialKind,
  PrefixCacheStabilityReport, TrialStepRecord, TruncationPolicy, TurnExecutionState (POS: Strongly typed
  contracts for In-Flight Turn State Truncation and Prefix Cache Stability Gate.)

[OUTPUT]
- Re-exports: CanonicalTurnCommit, IntermediateTrialKind, PrefixCacheStabilityReport, TrialStepRecord,
  TruncationPolicy, TurnExecutionState, TurnStateTruncationEngine

[POS]
In-Flight Turn State Truncation and Prefix Cache Stability Gate Suite (Item 205).
"""

from __future__ import annotations

from myrm_agent_harness.agent.context_management.turn_truncation.turn_truncation_engine import (
    TurnStateTruncationEngine,
)
from myrm_agent_harness.agent.context_management.turn_truncation.turn_truncation_types import (
    CanonicalTurnCommit,
    IntermediateTrialKind,
    PrefixCacheStabilityReport,
    TrialStepRecord,
    TruncationPolicy,
    TurnExecutionState,
)

__all__ = [
    "CanonicalTurnCommit",
    "IntermediateTrialKind",
    "PrefixCacheStabilityReport",
    "TrialStepRecord",
    "TruncationPolicy",
    "TurnExecutionState",
    "TurnStateTruncationEngine",
]
