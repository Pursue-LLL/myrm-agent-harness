# [POS]: myrm_agent_harness.toolkits.memory.budget_packing.orchestrator
# [INPUT]: RecallCandidate, BilledTokenBudget, PackedRecallResult, GreedyMarginalValuePacker, MarginalValueEvaluator
# [OUTPUT]: BudgetRecallPackingOrchestrator

"""Orchestration facade for Budget Greedy Marginal Value Recall Packing Suite.

Provides unified entry points for knapsack packing, legacy limit mode fallback,
and diagnostic inspection of candidate marginal values.

[INPUT]
- models::RecallCandidate, BilledTokenBudget, PackedRecallResult, PackedCandidateItem,
  DroppedCandidateItem, TokenAccountingReport, PackingDecisionReason
- greedy_packer::GreedyMarginalValuePacker
- marginal_value_evaluator::MarginalValueEvaluator

[OUTPUT]
- BudgetRecallPackingOrchestrator: High-level engine coordinator.

[POS]
Orchestrator facade for Item 122.
"""

from __future__ import annotations

from myrm_agent_harness.toolkits.memory.budget_packing.greedy_packer import (
    GreedyMarginalValuePacker,
    _format_recalled_prompt_block,
)
from myrm_agent_harness.toolkits.memory.budget_packing.marginal_value_evaluator import (
    MarginalValueEvaluator,
)
from myrm_agent_harness.toolkits.memory.budget_packing.models import (
    BilledTokenBudget,
    DroppedCandidateItem,
    MarginalValueMetrics,
    PackedCandidateItem,
    PackedRecallResult,
    PackingDecisionReason,
    RecallCandidate,
    TokenAccountingReport,
)


class BudgetRecallPackingOrchestrator:
    """Orchestrates budget-governed recall packing with inspection capabilities."""

    def __init__(
        self,
        packer: GreedyMarginalValuePacker | None = None,
        evaluator: MarginalValueEvaluator | None = None,
    ) -> None:
        self._evaluator = evaluator or MarginalValueEvaluator()
        self._packer = packer or GreedyMarginalValuePacker(self._evaluator)

    def pack_candidates(
        self,
        candidates: tuple[RecallCandidate, ...] | list[RecallCandidate],
        budget: BilledTokenBudget | None = None,
        enable_knapsack: bool = True,
    ) -> PackedRecallResult:
        """Pack candidates into recall context, dynamically selecting packing mode."""
        budget_cfg = budget or BilledTokenBudget()

        if enable_knapsack:
            return self._packer.pack(candidates, budget_cfg)

        # Legacy passthrough: Sort simply by relevance score up to max_items_limit
        sorted_candidates = sorted(candidates, key=lambda c: c.relevance_score, reverse=True)
        packed_items: list[PackedCandidateItem] = []
        dropped_items: list[DroppedCandidateItem] = []
        cumulative_tokens = 0

        for idx, cand in enumerate(sorted_candidates):
            m = MarginalValueMetrics(
                base_utility=cand.relevance_score * cand.confidence_score,
                redundancy_score=0.0,
                marginal_info_gain=1.0,
                marginal_value=cand.relevance_score * cand.confidence_score,
                marginal_value_density=round((cand.relevance_score * cand.confidence_score) / max(1, cand.billed_tokens), 6),
            )
            if idx < budget_cfg.max_items_limit and (cumulative_tokens + cand.billed_tokens <= budget_cfg.max_billed_tokens):
                cumulative_tokens += cand.billed_tokens
                packed_items.append(
                    PackedCandidateItem(
                        candidate=cand,
                        metrics=m,
                        order_index=len(packed_items),
                        cumulative_billed_tokens=cumulative_tokens,
                    )
                )
            else:
                dropped_items.append(
                    DroppedCandidateItem(
                        candidate=cand,
                        metrics=m,
                        reason=PackingDecisionReason.BUDGET_EXHAUSTED if idx < budget_cfg.max_items_limit else PackingDecisionReason.MAX_ITEMS_REACHED,
                    )
                )

        total_storage = sum(c.storage_tokens for c in candidates)
        accounting = TokenAccountingReport(
            total_candidates_examined=len(candidates),
            items_packed_count=len(packed_items),
            items_dropped_count=len(dropped_items),
            billed_tokens_spent=cumulative_tokens,
            billed_tokens_budget=budget_cfg.max_billed_tokens,
            billed_tokens_remaining=max(0, budget_cfg.max_billed_tokens - cumulative_tokens),
            storage_tokens_total=total_storage,
            storage_tokens_saved=max(0, total_storage - sum(p.candidate.storage_tokens for p in packed_items)),
            budget_utilization_pct=round((cumulative_tokens / max(1, budget_cfg.max_billed_tokens)) * 100.0, 2),
            redundant_tokens_filtered=0,
            average_marginal_density=round(sum(p.metrics.marginal_value_density for p in packed_items) / max(1, len(packed_items)), 6),
        )

        prompt_block = _format_recalled_prompt_block(
            tuple(packed_items), cumulative_tokens, budget_cfg.max_billed_tokens
        )
        return PackedRecallResult(
            packed_items=tuple(packed_items),
            dropped_candidates=tuple(dropped_items),
            accounting=accounting,
            composed_prompt_block=prompt_block,
            active_mode="legacy_limit_passthrough",
        )

    def inspect_marginal_evaluation(
        self,
        candidates: tuple[RecallCandidate, ...] | list[RecallCandidate],
        budget: BilledTokenBudget | None = None,
    ) -> list[tuple[RecallCandidate, MarginalValueMetrics]]:
        """Inspect marginal value breakdown for each candidate sequentially."""
        budget_cfg = budget or BilledTokenBudget()
        evaluator = MarginalValueEvaluator(budget_cfg)
        inspected: list[tuple[RecallCandidate, MarginalValueMetrics]] = []
        packed_so_far: list[RecallCandidate] = []

        for cand in candidates:
            metrics = evaluator.evaluate_candidate(cand, tuple(packed_so_far))
            inspected.append((cand, metrics))
            if metrics.marginal_value >= budget_cfg.min_marginal_value_threshold:
                packed_so_far.append(cand)

        return inspected
