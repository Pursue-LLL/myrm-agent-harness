"""Package facade for transcript enforcer.

[INPUT]
-
  agent.context_management.transcript_enforcer.transcript_append_only_enforcer::TranscriptAppendOnlyInvariantEnforcer
  (POS: Hard gate enforcing append-only invariant on conversation message transcripts.)
- agent.context_management.transcript_enforcer.transcript_enforcer_types::AppendOnlyEnforcementResult,
  DeltaCorrectionNote, MessageFingerprint, TurnTranscriptSnapshot, ViolationKind, ViolationRecord (POS: Types
  and models for transcript enforcer.)

[OUTPUT]
- Re-exports: AppendOnlyEnforcementResult, DeltaCorrectionNote, MessageFingerprint,
  TranscriptAppendOnlyInvariantEnforcer, TurnTranscriptSnapshot, ViolationKind, ViolationRecord

[POS]
Package facade for transcript enforcer.
"""

# ============================================================================
# Transcript Append-Only Invariant Enforcer Package (Item 169)
# ============================================================================

from .transcript_append_only_enforcer import TranscriptAppendOnlyInvariantEnforcer
from .transcript_enforcer_types import (
    AppendOnlyEnforcementResult,
    DeltaCorrectionNote,
    MessageFingerprint,
    TurnTranscriptSnapshot,
    ViolationKind,
    ViolationRecord,
)

__all__ = [
    "AppendOnlyEnforcementResult",
    "DeltaCorrectionNote",
    "MessageFingerprint",
    "TranscriptAppendOnlyInvariantEnforcer",
    "TurnTranscriptSnapshot",
    "ViolationKind",
    "ViolationRecord",
]
