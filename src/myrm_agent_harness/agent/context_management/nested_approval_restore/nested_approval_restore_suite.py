# [INPUT]: ApprovalDecisionKind, ApprovalDecisionRecord, CompactionEntry, CompactionRollbackBudget, DecisionPrecedence, NestedRestoreReceipt
# [OUTPUT]: NestedApprovalRestoreSuite, make_approval_decision, make_compaction_entry
# [POS]: agent/context_management/nested_approval_restore/nested_approval_restore_suite.py

"""Comprehensive facade suite for nested approval restore and compaction rollback.

[INPUT]
- ApprovalDecisionKind: Outcome classification enum.
- ApprovalDecisionRecord: Model capturing an approval decision.
- CompactionEntry: History turn or message entry.
- CompactionRollbackBudget: Bounded allocation policy for rollback stash.
- DecisionPrecedence: Resolution strategy enum.
- NestedRestoreReceipt: Cryptographically verifiable audit receipt.

[OUTPUT]
- NestedApprovalRestoreSuite: Unified facade managing nested approvals, live priority, and compaction rollback.
- make_approval_decision: Convenience factory constructing ApprovalDecisionRecord.
- make_compaction_entry: Convenience factory constructing CompactionEntry.

[POS]
End-to-end facade suite for nested approval restore and bounded compaction rollback.
"""

from __future__ import annotations

import time
from typing import Mapping, Sequence
import uuid

from .approval_precedence_resolver import ApprovalPrecedenceResolver
from .compaction_rollback_buffer import CompactionRollbackBuffer
from .nested_approval_types import (
    ApprovalDecisionKind,
    ApprovalDecisionRecord,
    CompactionEntry,
    CompactionRollbackBudget,
    DecisionPrecedence,
    NestedRestoreReceipt,
)


def make_approval_decision(
    grant_id: str,
    tool_name: str,
    agent_owner: str,
    decision: ApprovalDecisionKind,
    *,
    is_permanent: bool = False,
    message: str | None = None,
    is_live: bool = False,
    timestamp: float | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> ApprovalDecisionRecord:
    """Convenience factory creating a strongly typed ApprovalDecisionRecord."""
    return ApprovalDecisionRecord(
        grant_id=grant_id,
        tool_name=tool_name,
        agent_owner=agent_owner,
        decision=decision,
        is_permanent=is_permanent,
        message=message,
        is_live=is_live,
        timestamp=timestamp if timestamp is not None else time.time(),
        metadata=dict(metadata) if metadata else {},
    )


def make_compaction_entry(
    entry_id: str,
    content: str,
    token_count: int,
    *,
    timestamp: float | None = None,
    metadata: Mapping[str, str | int | float | bool | None] | None = None,
) -> CompactionEntry:
    """Convenience factory creating a strongly typed CompactionEntry."""
    return CompactionEntry(
        entry_id=entry_id,
        content=content,
        token_count=token_count,
        timestamp=timestamp if timestamp is not None else time.time(),
        metadata=dict(metadata) if metadata else {},
    )


class NestedApprovalRestoreSuite:
    """Unified suite managing nested approval restoration and transactional compaction replacement."""

    def __init__(self) -> None:
        self._resolver = ApprovalPrecedenceResolver()
        self._buffer = CompactionRollbackBuffer()

    def restore_nested_run(
        self,
        snapshot_decisions: Sequence[ApprovalDecisionRecord],
        live_decisions: Sequence[ApprovalDecisionRecord],
        *,
        session_id: str,
        precedence: DecisionPrecedence = DecisionPrecedence.LIVE_PRIORITY,
    ) -> tuple[tuple[ApprovalDecisionRecord, ...], NestedRestoreReceipt]:
        """Restore nested run approvals, ensuring live rejections and grants take precedence over stale snapshots."""
        resolved, overrides, rejections = self._resolver.resolve(
            snapshot_decisions=snapshot_decisions,
            live_decisions=live_decisions,
            precedence=precedence,
        )

        receipt_id = f"rcpt_rest_{uuid.uuid4().hex[:10]}"
        receipt = NestedRestoreReceipt.create(
            receipt_id=receipt_id,
            session_id=session_id,
            restored_grants_count=len(resolved),
            live_overrides_applied=overrides,
            permanent_rejections_preserved=rejections,
            rollback_budget_available=50,
            compaction_validated=True,
        )
        return resolved, receipt

    def replace_with_compaction(
        self,
        existing_history: Sequence[CompactionEntry],
        candidate_summary: CompactionEntry,
        budget: CompactionRollbackBudget | None = None,
    ) -> tuple[bool, tuple[CompactionEntry, ...], str | None, str | None]:
        """Validate candidate summary first; only stash rollback and replace old history if valid."""
        effective_budget = budget if budget is not None else CompactionRollbackBudget()
        return self._buffer.validate_and_replace(
            existing_history=existing_history,
            candidate_summary=candidate_summary,
            budget=effective_budget,
        )

    def rollback_compaction(
        self,
        stash_id: str,
        current_history: Sequence[CompactionEntry],
    ) -> tuple[CompactionEntry, ...]:
        """Rollback compaction replacement and restore stashed historical entries."""
        return self._buffer.rollback(stash_id, current_history)

    def discard_compaction_stash(self, stash_id: str) -> bool:
        """Discard rollback stash once the compaction turn is safely committed."""
        return self._buffer.discard_stash(stash_id)
