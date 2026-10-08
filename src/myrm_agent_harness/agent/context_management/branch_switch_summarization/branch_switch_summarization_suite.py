"""Main suite orchestrating cross-branch outcome condensation and context transfer.

[INPUT]
- agent.context_management.session_tree_dag::SessionTreeDagSuite, SessionTreeEntry (POS: Immutable session
  tree DAG and branching exploration suite.)
- agent.context_management.branch_switch_summarization.branch_outcome_condenser::BranchOutcomeCondenser (POS:
  Semantic condensation engine extracting trials, failures, and lessons from exploratory branches.)
- agent.context_management.branch_switch_summarization.branch_summary_types::BranchExplorationCard,
  BranchOutcomeVerdict, BranchSummaryEntry, BranchTransferReceipt (POS: Types and schemas for branch switch
  outcome condensation and context transfer.)

[OUTPUT]
- BranchSwitchSummarizationAndContextTransferSuite: Orchestrates semantic wisdom distillation across branches
  and prevents repetitive trial errors.

[POS]
Main suite orchestrating cross-branch outcome condensation and context transfer.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Dict, List, Optional, Tuple

from ..session_tree_dag import SessionTreeDagSuite, SessionTreeEntry
from .branch_outcome_condenser import BranchOutcomeCondenser
from .branch_summary_types import (
    BranchExplorationCard,
    BranchOutcomeVerdict,
    BranchSummaryEntry,
    BranchTransferReceipt,
)


class BranchSwitchSummarizationAndContextTransferSuite:
    """Orchestrates semantic wisdom distillation across branches and prevents repetitive trial errors."""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._transferred_cards: Dict[str, BranchExplorationCard] = {}
        self._transfer_receipts: List[BranchTransferReceipt] = []

    @property
    def session_id(self) -> str:
        """Return session ID."""
        return self._session_id

    def extract_branch_exclusive_entries(
        self,
        tree_suite: SessionTreeDagSuite,
        branch_name: str,
    ) -> List[SessionTreeEntry]:
        """Extract entries created exclusively on branch_name after its fork point."""
        branch_meta = tree_suite.get_branch(branch_name)
        if branch_meta is None:
            raise KeyError(f"Branch '{branch_name}' not found in session tree")

        if not branch_meta.head_entry_id:
            return []

        storage = tree_suite.get_storage()
        full_lineage = storage.get_lineage_path(branch_meta.head_entry_id)

        # Filter only entries belonging to branch_name
        return [e for e in full_lineage if e.branch_name == branch_name]

    def switch_branch_with_condensed_summary(
        self,
        tree_suite: SessionTreeDagSuite,
        source_branch: str,
        target_branch: str,
        verdict: BranchOutcomeVerdict = BranchOutcomeVerdict.ABANDONED_FAILURE,
        manual_takeaway: Optional[str] = None,
    ) -> Tuple[BranchSummaryEntry, BranchTransferReceipt]:
        """Distill source branch learnings, inject summary entry into target branch, and switch active head."""
        target_meta = tree_suite.get_branch(target_branch)
        if target_meta is None:
            raise KeyError(f"Target branch '{target_branch}' does not exist")

        # 1. Extract entries exclusive to source branch
        exclusive_entries = self.extract_branch_exclusive_entries(tree_suite, source_branch)

        # 2. Distill card and synthesize summary entry
        card = BranchOutcomeCondenser.condense_branch_entries(
            source_branch_name=source_branch,
            target_branch_name=target_branch,
            entries=exclusive_entries,
            verdict=verdict,
            manual_takeaway=manual_takeaway,
        )
        summary_entry = BranchOutcomeCondenser.synthesize_summary_entry(card)

        # 3. Switch active branch to target
        tree_suite.switch_active_branch(target_branch)

        # 4. Inject first-class lesson entry into target branch
        injected_node = tree_suite.append_message(
            role="system",
            content=summary_entry.formatted_prompt_payload,
        )

        # 5. Issue cryptographic transfer receipt
        transfer_hash = hashlib.sha256(
            f"{self._session_id}:{source_branch}:{target_branch}:{summary_entry.summary_entry_id}".encode("utf-8")
        ).hexdigest()[:16]

        receipt = BranchTransferReceipt(
            receipt_id=f"btr_{uuid.uuid4().hex[:8]}",
            session_id=self._session_id,
            source_branch=source_branch,
            target_branch=target_branch,
            source_turns_count=len(exclusive_entries),
            condensed_tokens_count=summary_entry.estimated_tokens,
            verdict=verdict,
            transfer_hash=transfer_hash,
        )

        self._transferred_cards[card.card_id] = card
        self._transfer_receipts.append(receipt)

        return summary_entry, receipt

    def get_all_distilled_cards(self) -> List[BranchExplorationCard]:
        """Retrieve all distilled exploration wisdom cards across sessions."""
        return list(self._transferred_cards.values())

    def get_transfer_receipts(self) -> List[BranchTransferReceipt]:
        """Retrieve all recorded transfer receipts."""
        return list(self._transfer_receipts)
