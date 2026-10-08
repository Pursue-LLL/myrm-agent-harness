# [POS]: myrm_agent_harness.toolkits.memory.budget_packing.greedy_packer
# [INPUT]: RecallCandidate, BilledTokenBudget, MarginalValueMetrics, PackedCandidateItem, DroppedCandidateItem, TokenAccountingReport, PackedRecallResult, MarginalValueEvaluator
# [OUTPUT]: GreedyMarginalValuePacker

"""Greedy knapsack packing engine for recall context optimization.

Implements marginal value density greedy packing against strict token budget,
supporting backfill for small high-utility fragments and dual-track accounting.

[INPUT]
- models::RecallCandidate, BilledTokenBudget, MarginalValueMetrics, PackedCandidateItem,
  DroppedCandidateItem, TokenAccountingReport, PackedRecallResult, PackingDecisionReason
- marginal_value_evaluator::MarginalValueEvaluator

[OUTPUT]
- GreedyMarginalValuePacker: Core knapsack solver balancing utility, diversity, and token cost.

[POS]
Algorithmic heart of Item 122: Budget Greedy Marginal Value Recall Packing Suite.
"""

from __future__ import annotations

from typing import Final

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

_DEFAULT_PROMPT_HEADER: Final[str] = "recalled_memories"


def _format_recalled_prompt_block(
    packed_items: tuple[PackedCandidateItem, ...],
    billed_spent: int,
    budget_limit: int,
) -> str:
    """Format accepted recall fragments into a standardized XML context block."""
    if not packed_items:
        return ""

    lines: list[str] = [
        f'<{_DEFAULT_PROMPT_HEADER} billed_tokens="{billed_spent}" budget="{budget_limit}" count="{len(packed_items)}">'
    ]
    for item in packed_items:
        c = item.candidate
        m = item.metrics
        domain_attr = f' domain="{" ".join(c.domain_tags)}"' if c.domain_tags else ""
        lines.append(
            f'  <memory_item id="{c.id}" rank="{item.order_index + 1}" '
            f'utility="{m.marginal_value:.3f}" tokens="{c.billed_tokens}"{domain_attr}>'
        )
        lines.append(f"    {c.content.strip()}")
        lines.append("  </memory_item>")
    lines.append(f"</{_DEFAULT_PROMPT_HEADER}>")
    return "\n".join(lines)


class GreedyMarginalValuePacker:
    """Iterative knapsack packer selecting items by marginal value density."""

    def __init__(self, evaluator: MarginalValueEvaluator | None = None) -> None:
        self._evaluator = evaluator or MarginalValueEvaluator()

    def pack(
        self,
        candidates: tuple[RecallCandidate, ...] | list[RecallCandidate],
        budget: BilledTokenBudget | None = None,
    ) -> PackedRecallResult:
        """Execute greedy knapsack packing over input candidates."""
        budget_cfg = budget or BilledTokenBudget()
        evaluator = MarginalValueEvaluator(budget_cfg)

        remaining_candidates: list[RecallCandidate] = list(candidates)
        packed_items: list[PackedCandidateItem] = []
        dropped_candidates: list[DroppedCandidateItem] = []

        total_storage_tokens = sum(c.storage_tokens for c in remaining_candidates)
        cumulative_billed_tokens = 0

        while remaining_candidates and len(packed_items) < budget_cfg.max_items_limit:
            current_packed_candidates = tuple(p.candidate for p in packed_items)

            # Evaluate marginal utility of all remaining candidates given currently packed set
            evaluated_pool: list[tuple[RecallCandidate, MarginalValueMetrics]] = []
            low_utility_to_drop: list[tuple[RecallCandidate, MarginalValueMetrics, PackingDecisionReason]] = []

            for cand in remaining_candidates:
                metrics = evaluator.evaluate_candidate(cand, current_packed_candidates)
                if metrics.redundancy_score >= budget_cfg.max_redundancy_threshold:
                    low_utility_to_drop.append(
                        (cand, metrics, PackingDecisionReason.REDUNDANCY_SUPPRESSED)
                    )
                elif metrics.marginal_value < budget_cfg.min_marginal_value_threshold:
                    low_utility_to_drop.append(
                        (cand, metrics, PackingDecisionReason.BELOW_THRESHOLD)
                    )
                else:
                    evaluated_pool.append((cand, metrics))

            # Prune candidates below quality or diversity threshold
            for cand, m, r in low_utility_to_drop:
                remaining_candidates.remove(cand)
                dropped_candidates.append(DroppedCandidateItem(candidate=cand, metrics=m, reason=r))

            if not evaluated_pool:
                break

            # Sort candidate pool by marginal value density descending (break ties by utility, then lower tokens)
            evaluated_pool.sort(
                key=lambda item: (
                    item[1].marginal_value_density,
                    item[1].marginal_value,
                    -item[0].billed_tokens,
                ),
                reverse=True,
            )

            # Try to pack best candidate within remaining token capacity
            selected: tuple[RecallCandidate, MarginalValueMetrics] | None = None
            budget_left = budget_cfg.max_billed_tokens - cumulative_billed_tokens

            for cand, metrics in evaluated_pool:
                if cand.billed_tokens <= budget_left:
                    selected = (cand, metrics)
                    break
                if not budget_cfg.allow_greedy_backfill:
                    # Without backfill, first budget overflow terminates packing
                    break

            if selected is None:
                # No remaining candidate can fit into budget_left
                for cand, metrics in evaluated_pool:
                    remaining_candidates.remove(cand)
                    dropped_candidates.append(
                        DroppedCandidateItem(
                            candidate=cand,
                            metrics=metrics,
                            reason=PackingDecisionReason.BUDGET_EXHAUSTED,
                        )
                    )
                break

            best_cand, best_metrics = selected
            remaining_candidates.remove(best_cand)
            cumulative_billed_tokens += best_cand.billed_tokens

            packed_items.append(
                PackedCandidateItem(
                    candidate=best_cand,
                    metrics=best_metrics,
                    order_index=len(packed_items),
                    cumulative_billed_tokens=cumulative_billed_tokens,
                )
            )

        # Mark any remaining candidates as max items reached if loop broke due to item count
        for remaining in remaining_candidates:
            current_packed_candidates = tuple(p.candidate for p in packed_items)
            m = evaluator.evaluate_candidate(remaining, current_packed_candidates)
            dropped_candidates.append(
                DroppedCandidateItem(
                    candidate=remaining,
                    metrics=m,
                    reason=PackingDecisionReason.MAX_ITEMS_REACHED,
                )
            )

        # Compile accounting report
        packed_storage_tokens = sum(p.candidate.storage_tokens for p in packed_items)
        storage_saved = total_storage_tokens - packed_storage_tokens
        redundant_filtered = sum(
            d.candidate.billed_tokens
            for d in dropped_candidates
            if d.reason == PackingDecisionReason.REDUNDANCY_SUPPRESSED
        )

        avg_density = (
            sum(p.metrics.marginal_value_density for p in packed_items) / len(packed_items)
            if packed_items
            else 0.0
        )
        util_pct = (
            (cumulative_billed_tokens / max(1, budget_cfg.max_billed_tokens)) * 100.0
            if budget_cfg.max_billed_tokens > 0
            else 0.0
        )

        accounting = TokenAccountingReport(
            total_candidates_examined=len(candidates),
            items_packed_count=len(packed_items),
            items_dropped_count=len(dropped_candidates),
            billed_tokens_spent=cumulative_billed_tokens,
            billed_tokens_budget=budget_cfg.max_billed_tokens,
            billed_tokens_remaining=max(0, budget_cfg.max_billed_tokens - cumulative_billed_tokens),
            storage_tokens_total=total_storage_tokens,
            storage_tokens_saved=max(0, storage_saved),
            budget_utilization_pct=round(util_pct, 2),
            redundant_tokens_filtered=redundant_filtered,
            average_marginal_density=round(avg_density, 6),
        )

        prompt_block = _format_recalled_prompt_block(
            tuple(packed_items),
            cumulative_billed_tokens,
            budget_cfg.max_billed_tokens,
        )

        return PackedRecallResult(
            packed_items=tuple(packed_items),
            dropped_candidates=tuple(dropped_candidates),
            accounting=accounting,
            composed_prompt_block=prompt_block,
            active_mode="greedy_marginal_knapsack",
        )
