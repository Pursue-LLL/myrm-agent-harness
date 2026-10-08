"""Branch switch summarization and context transfer suite.

[INPUT]
- agent.context_management.branch_switch_summarization.branch_outcome_condenser::BranchOutcomeCondenser (POS:
  Semantic condensation engine extracting trials, failures, and lessons from exploratory branches.)
- agent.context_management.branch_switch_summarization.branch_summary_types::BranchExplorationCard,
  BranchOutcomeVerdict, BranchSummaryEntry, BranchTransferReceipt (POS: Types and schemas for branch switch
  outcome condensation and context transfer.)
-
  agent.context_management.branch_switch_summarization.branch_switch_summarization_suite::BranchSwitchSummarizationAndContextTransferSuite
  (POS: Main suite orchestrating cross-branch outcome condensation and context transfer.)

[OUTPUT]
- Re-exports: BranchExplorationCard, BranchOutcomeCondenser, BranchOutcomeVerdict, BranchSummaryEntry,
  BranchSwitchSummarizationAndContextTransferSuite, BranchTransferReceipt

[POS]
Branch switch summarization and context transfer suite.
"""

from __future__ import annotations

from .branch_outcome_condenser import BranchOutcomeCondenser
from .branch_summary_types import (
    BranchExplorationCard,
    BranchOutcomeVerdict,
    BranchSummaryEntry,
    BranchTransferReceipt,
)
from .branch_switch_summarization_suite import (
    BranchSwitchSummarizationAndContextTransferSuite,
)

__all__ = [
    "BranchExplorationCard",
    "BranchOutcomeCondenser",
    "BranchOutcomeVerdict",
    "BranchSummaryEntry",
    "BranchSwitchSummarizationAndContextTransferSuite",
    "BranchTransferReceipt",
]
