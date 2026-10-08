"""Nested approval restoration and bounded compaction rollback subsystem.

[INPUT]
- None (Public package entry point).

[OUTPUT]
- ApprovalDecisionKind: Outcome classification enum (approve, reject, pending).
- ApprovalDecisionRecord: Model capturing an approval decision.
- ApprovalPrecedenceResolver: Resolver arbitrating live vs snapshot approvals.
- CompactionEntry: History turn or message entry.
- CompactionRollbackBudget: Bounded allocation policy for rollback stash.
- CompactionRollbackBuffer: Stash manager providing transactional compaction replacement.
- DecisionPrecedence: Resolution strategy enum.
- NestedApprovalRestoreSuite: Unified facade managing nested approvals and compaction rollback.
- NestedRestoreReceipt: Cryptographically verifiable audit receipt.
- make_approval_decision: Convenience factory constructing ApprovalDecisionRecord.
- make_compaction_entry: Convenience factory constructing CompactionEntry.
- validate_summary_candidate: Verifier inspecting replacement candidate before old history is touched.

[POS]
Package entry point for nested approval restore and compaction rollback subsystem.
"""

from __future__ import annotations

from .approval_precedence_resolver import ApprovalPrecedenceResolver
from .compaction_rollback_buffer import (
    CompactionRollbackBuffer,
    validate_summary_candidate,
)
from .nested_approval_restore_suite import (
    NestedApprovalRestoreSuite,
    make_approval_decision,
    make_compaction_entry,
)
from .nested_approval_types import (
    ApprovalDecisionKind,
    ApprovalDecisionRecord,
    CompactionEntry,
    CompactionRollbackBudget,
    DecisionPrecedence,
    NestedRestoreReceipt,
)

__all__ = [
    "ApprovalDecisionKind",
    "ApprovalDecisionRecord",
    "ApprovalPrecedenceResolver",
    "CompactionEntry",
    "CompactionRollbackBudget",
    "CompactionRollbackBuffer",
    "DecisionPrecedence",
    "NestedApprovalRestoreSuite",
    "NestedRestoreReceipt",
    "make_approval_decision",
    "make_compaction_entry",
    "validate_summary_candidate",
]
