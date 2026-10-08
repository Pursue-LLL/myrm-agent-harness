"""Handoff checkpoint then compact package.

[INPUT]
- agent.context_management.handoff_checkpoint.checkpoint_compiler::HandoffCheckpointCompiler (POS: Compiler
  and bidirectional markdown serializer for six-dimensional task checkpoints.)
- agent.context_management.handoff_checkpoint.checkpoint_types::CheckpointRenderFormat, HandoffCompactStage,
  HandoffThenCompactResult, TaskCheckpoint (POS: Strongly typed contracts for Handoff-then-Compact checkpoint
  pipeline.)
- agent.context_management.handoff_checkpoint.handoff_compact_suite::WorkBuddyHandoffThenCompactSuite (POS:
  End-to-end suite orchestrating one-click task handoff checkpoint before compaction.)

[OUTPUT]
- Re-exports: CheckpointRenderFormat, HandoffCheckpointCompiler, HandoffCompactStage,
  HandoffThenCompactResult, TaskCheckpoint, WorkBuddyHandoffThenCompactSuite

[POS]
Handoff checkpoint then compact package.
"""

from __future__ import annotations

from .checkpoint_compiler import HandoffCheckpointCompiler
from .checkpoint_types import (
    CheckpointRenderFormat,
    HandoffCompactStage,
    HandoffThenCompactResult,
    TaskCheckpoint,
)
from .handoff_compact_suite import WorkBuddyHandoffThenCompactSuite

__all__ = [
    "CheckpointRenderFormat",
    "HandoffCheckpointCompiler",
    "HandoffCompactStage",
    "HandoffThenCompactResult",
    "TaskCheckpoint",
    "WorkBuddyHandoffThenCompactSuite",
]
