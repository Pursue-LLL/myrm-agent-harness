"""Main suite orchestrating session tree dead branch prune and physical storage GC.

[INPUT]
- tree_suite: SessionTreeDagSuite session exploration DAG
- require_summary_anchor: bool whether to mandate cross-branch summary preservation

[OUTPUT]
- SessionTreeBranchPruneAndStorageGCSuite: Main orchestrator for branch pruning and storage compaction.

[POS]
Main suite orchestrating session tree dead branch prune and physical storage GC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from ..session_tree_dag import SessionTreeDagSuite
from .gc_types import GcSafetyRule, PrunedBranchReport, StorageGcReceipt
from .session_tree_gc_engine import SessionTreeGcEngine


class SessionTreeBranchPruneAndStorageGCSuite:
    """Orchestrates dead branch pruning and physical storage compaction for long-running sessions."""

    def __init__(
        self,
        tree_suite: SessionTreeDagSuite,
        require_summary_anchor: bool = False,
    ) -> None:
        self._tree_suite = tree_suite
        self._require_summary_anchor = require_summary_anchor
        self._gc_receipts: List[StorageGcReceipt] = []

    @property
    def session_id(self) -> str:
        """Return target session ID."""
        return self._tree_suite.session_id

    def identify_prunable_branches(self) -> List[str]:
        """Discover eligible orphan and dead exploration branches."""
        return SessionTreeGcEngine.get_prunable_branches(self._tree_suite)

    def prune_branch(
        self,
        branch_name: str,
        force: bool = False,
    ) -> Tuple[PrunedBranchReport, StorageGcReceipt]:
        """Prune an individual exploration branch and squash physical storage."""
        had_anchor = SessionTreeGcEngine.check_has_summary_anchor(self._tree_suite, branch_name)

        receipt = SessionTreeGcEngine.execute_prune_and_squash(
            tree_suite=self._tree_suite,
            branches_to_prune=[branch_name],
            require_summary_anchor=self._require_summary_anchor,
            force=force,
        )
        self._gc_receipts.append(receipt)

        report = PrunedBranchReport(
            branch_name=branch_name,
            purged_entries_count=receipt.purged_entries_count,
            freed_bytes_estimate=receipt.freed_storage_bytes,
            had_summary_anchor=had_anchor,
            pruned_at_iso=datetime.now(timezone.utc).isoformat(),
        )
        return report, receipt

    def prune_all_dead_branches(
        self,
        force: bool = False,
    ) -> StorageGcReceipt:
        """Prune all eligible non-active, non-root exploration branches in batch."""
        prunable = self.identify_prunable_branches()
        if not prunable:
            # Nothing to prune, return zero-delta receipt
            storage = self._tree_suite.get_storage()
            cnt = len(storage.get_all_entries())
            receipt = StorageGcReceipt(
                receipt_id="sgc_noop",
                session_id=self._tree_suite.session_id,
                before_entries_count=cnt,
                after_entries_count=cnt,
                purged_entries_count=0,
                pruned_branches=[],
                retained_branches=[b.branch_name for b in self._tree_suite.list_branches()],
                before_storage_bytes=0,
                after_storage_bytes=0,
                freed_storage_bytes=0,
                compaction_hash="",
                completed_at_iso=datetime.now(timezone.utc).isoformat(),
            )
            return receipt

        receipt = SessionTreeGcEngine.execute_prune_and_squash(
            tree_suite=self._tree_suite,
            branches_to_prune=prunable,
            require_summary_anchor=self._require_summary_anchor,
            force=force,
        )
        self._gc_receipts.append(receipt)
        return receipt

    def get_gc_receipts(self) -> List[StorageGcReceipt]:
        """Return history of all GC compaction receipts."""
        return list(self._gc_receipts)
