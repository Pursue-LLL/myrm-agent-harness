"""Parallel Work Conflict Reconciliation Gate package.

[INPUT]
- detector.ParallelWorkConflictDetector
- types.*

[OUTPUT]
- ParallelWorkConflictDetector
- WriteMutationType, WriteFingerprint, ConflictStatus, ResolutionStrategy
- WorkConflictItem, ConflictGateVerdict

[POS]
myrm_agent_harness/agent/sub_agents/conflict_gate/__init__.py
"""

from myrm_agent_harness.agent.sub_agents.conflict_gate.detector import (
    ParallelWorkConflictDetector,
)
from myrm_agent_harness.agent.sub_agents.conflict_gate.types import (
    ConflictGateVerdict,
    ConflictStatus,
    ResolutionStrategy,
    WorkConflictItem,
    WriteFingerprint,
    WriteMutationType,
)

__all__ = [
    "ConflictGateVerdict",
    "ConflictStatus",
    "ParallelWorkConflictDetector",
    "ResolutionStrategy",
    "WorkConflictItem",
    "WriteFingerprint",
    "WriteMutationType",
]
