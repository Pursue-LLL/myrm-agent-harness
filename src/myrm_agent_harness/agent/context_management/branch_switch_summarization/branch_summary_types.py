"""Types and schemas for branch switch outcome condensation and context transfer.

[INPUT]
- None (self-contained; standard library only)

[OUTPUT]
- BranchOutcomeVerdict: Categorization of exploration branch outcome.
- BranchExplorationCard: Structured summary card condensing trials, outcomes, and lessons from a branch.
- BranchSummaryEntry: First-class DAG-compatible entry representing condensed wisdom transferred across
  branches.
- BranchTransferReceipt: Audit receipt certifying lossless transfer of distilled branch experience.

[POS]
Types and schemas for branch switch outcome condensation and context transfer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional


class BranchOutcomeVerdict(str, Enum):
    """Categorization of exploration branch outcome."""

    ABANDONED_FAILURE = "abandoned_failure"
    PARTIALLY_VALIDATED = "partially_validated"
    SUCCESSFUL_DISCOVERY = "successful_discovery"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class BranchExplorationCard:
    """Structured summary card condensing trials, outcomes, and lessons from a branch."""

    card_id: str
    source_branch: str
    target_branch: str
    verdict: BranchOutcomeVerdict
    attempted_approach: str
    failure_root_cause: Optional[str]
    unviable_options: List[str] = field(default_factory=list)
    validated_findings: List[str] = field(default_factory=list)
    key_lesson: str = ""


@dataclass(frozen=True)
class BranchSummaryEntry:
    """First-class DAG-compatible entry representing condensed wisdom transferred across branches."""

    summary_entry_id: str
    source_branch_name: str
    target_branch_name: str
    formatted_prompt_payload: str
    estimated_tokens: int
    created_at_iso: str
    metadata: Dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BranchTransferReceipt:
    """Audit receipt certifying lossless transfer of distilled branch experience."""

    receipt_id: str
    session_id: str
    source_branch: str
    target_branch: str
    source_turns_count: int
    condensed_tokens_count: int
    verdict: BranchOutcomeVerdict
    transfer_hash: str
