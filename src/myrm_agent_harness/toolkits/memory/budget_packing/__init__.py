# [POS]: myrm_agent_harness.toolkits.memory.budget_packing
# [INPUT]: models, marginal_value_evaluator, greedy_packer, orchestrator, estimator
# [OUTPUT]: Public exports for budget greedy marginal value recall packing

"""Budget Greedy Marginal Value Recall Packing Suite (Item 122 P2).

Benchmarked against FrankHu-HK/mnemosyne brain.py _budget_recall knapsack algorithm:
Packs highest marginal-value density memory fragments within token budget,
suppresses semantic redundancy, and separates Billed Tokens from Storage Tokens.

[INPUT]
- Submodules: models, marginal_value_evaluator, greedy_packer, orchestrator, estimator.

[OUTPUT]
- Public package exports for budget-governed recall packing.

[POS]
Package facade for memory recall budget packing.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.budget_packing.estimator import (
    calculate_content_overlap,
    estimate_tokens,
)
from myrm_agent_harness.toolkits.memory.budget_packing.greedy_packer import (
    GreedyMarginalValuePacker,
)
from myrm_agent_harness.toolkits.memory.budget_packing.marginal_value_evaluator import (
    MarginalValueEvaluator,
    compute_text_similarity,
)
from myrm_agent_harness.toolkits.memory.budget_packing.models import (
    BilledTokenBudget,
    DroppedCandidateItem,
    MarginalValueMetrics,
    PackedCandidateItem,
    PackedRecallItem,
    PackedRecallResult,
    PackingDecisionReason,
    PackingItemTier,
    RecallCandidate,
    RecallCandidateItem,
    RecallPackingResult,
    TokenAccountingReport,
)
from myrm_agent_harness.toolkits.memory.budget_packing.orchestrator import (
    BudgetRecallPackingOrchestrator,
)

__all__ = [
    "BilledTokenBudget",
    "BudgetRecallPackingOrchestrator",
    "DroppedCandidateItem",
    "GreedyMarginalValuePacker",
    "MarginalValueEvaluator",
    "MarginalValueMetrics",
    "PackedCandidateItem",
    "PackedRecallItem",
    "PackedRecallResult",
    "PackingDecisionReason",
    "PackingItemTier",
    "RecallCandidate",
    "RecallCandidateItem",
    "RecallPackingResult",
    "TokenAccountingReport",
    "calculate_content_overlap",
    "compute_text_similarity",
    "estimate_tokens",
]
