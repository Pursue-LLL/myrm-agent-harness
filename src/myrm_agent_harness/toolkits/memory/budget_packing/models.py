# [POS]: src/myrm_agent_harness/toolkits/memory/budget_packing/models.py
# [INPUT]: Raw candidate memory records, scoring signals, and budget configurations.
# [OUTPUT]: Strongly-typed Pydantic domain models for greedy marginal-value recall packing.

"""Domain models for Budget Greedy Marginal Value Recall Packing Suite (Item 122 P2).

Benchmarked against FrankHu-HK/mnemosyne knapsack algorithm:
Defines candidate records, dual-track token budget constraints,
marginal utility metrics, and packing outcome reports.

[INPUT]
- Third-party: pydantic

[OUTPUT]
- PackingDecisionReason: Reason why a memory candidate was packed or dropped.
- PackingItemTier: Fidelity tier of an item packed into the budgeted prompt context.
- RecallCandidate: Raw candidate memory record retrieved from vector or keyword storage.
- BilledTokenBudget: Token budget constraints and heuristic tuning parameters.
- MarginalValueMetrics: Marginal value evaluation breakdown for a candidate.
- PackedCandidateItem: Candidate memory record selected and packed into the budget.
- DroppedCandidateItem: Candidate memory record rejected from the budget.
- TokenAccountingReport: Dual-track token accounting and cost efficiency metrics.
- PackedRecallResult: Complete outcome of greedy marginal value recall packing.

[POS]
Domain models for Budget Greedy Marginal Value Recall Packing Suite (Item 122 P2).
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PackingDecisionReason(StrEnum):
    """Reason why a memory candidate was packed or dropped."""

    ACCEPTED = "accepted"
    BUDGET_EXHAUSTED = "budget_exhausted"
    REDUNDANCY_SUPPRESSED = "redundancy_suppressed"
    BELOW_THRESHOLD = "below_threshold"
    MAX_ITEMS_REACHED = "max_items_reached"


class PackingItemTier(StrEnum):
    """Fidelity tier of an item packed into the budgeted prompt context."""

    FULL = "full"
    DOWNGRADED = "downgraded"
    REFERENCE = "reference"


class RecallCandidate(BaseModel):
    """Raw candidate memory record retrieved from vector or keyword storage."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique memory identifier or URI")
    content: str = Field(..., description="Full text payload of the memory record")
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Raw semantic similarity score")
    confidence_score: float = Field(default=0.8, ge=0.0, le=1.0, description="Confidence or truthfulness score")
    billed_tokens: int = Field(default=50, ge=0, description="Estimated billed tokens consumed in prompt context")
    storage_tokens: int = Field(default=80, ge=0, description="Physical storage token weight")
    domain_tags: tuple[str, ...] = Field(default_factory=tuple, description="Domain or category tags")
    source_session_id: str | None = Field(default=None, description="Originating session identifier")
    summary_l1: str | None = Field(default=None, description="Optional concise L1 overview")
    metadata: dict[str, str] = Field(default_factory=dict, description="Arbitrary metadata attributes")


# Alias for compatibility
RecallCandidateItem = RecallCandidate


class BilledTokenBudget(BaseModel):
    """Token budget constraints and heuristic tuning parameters."""

    model_config = ConfigDict(frozen=True)

    max_billed_tokens: int = Field(default=1024, ge=1, description="Hard token ceiling for prompt injection")
    max_items_limit: int = Field(default=10, ge=1, description="Maximum number of items to pack")
    diversity_penalty_lambda: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Redundancy penalty multiplier in [0.0, 1.0]"
    )
    max_redundancy_threshold: float = Field(
        default=0.6, ge=0.0, le=1.0, description="Jaccard overlap cutoff beyond which items are dropped"
    )
    min_marginal_value_threshold: float = Field(
        default=0.1, ge=0.0, description="Minimum marginal utility required for inclusion"
    )
    allow_greedy_backfill: bool = Field(
        default=True, description="Whether to continue scanning smaller candidates when large item overflows"
    )


class MarginalValueMetrics(BaseModel):
    """Marginal value evaluation breakdown for a candidate."""

    model_config = ConfigDict(frozen=True)

    base_utility: float = Field(..., ge=0.0, le=1.0, description="relevance_score * confidence_score")
    redundancy_score: float = Field(..., ge=0.0, le=1.0, description="Max Jaccard overlap with packed items")
    marginal_info_gain: float = Field(..., ge=0.0, le=1.0, description="1.0 - (lambda * redundancy_score)")
    marginal_value: float = Field(..., ge=0.0, description="base_utility * marginal_info_gain")
    marginal_value_density: float = Field(..., ge=0.0, description="marginal_value / billed_tokens")


class PackedCandidateItem(BaseModel):
    """Candidate memory record selected and packed into the budget."""

    model_config = ConfigDict(frozen=True)

    candidate: RecallCandidate
    metrics: MarginalValueMetrics
    order_index: int = Field(..., ge=0, description="0-based sequence order in which item was packed")
    cumulative_billed_tokens: int = Field(..., ge=0, description="Total billed tokens after adding this item")
    tier: PackingItemTier = Field(default=PackingItemTier.FULL, description="Fidelity tier of packed item")


# Alias for compatibility
PackedRecallItem = PackedCandidateItem


class DroppedCandidateItem(BaseModel):
    """Candidate memory record rejected from the budget."""

    model_config = ConfigDict(frozen=True)

    candidate: RecallCandidate
    metrics: MarginalValueMetrics
    reason: PackingDecisionReason


class TokenAccountingReport(BaseModel):
    """Dual-track token accounting and cost efficiency metrics."""

    model_config = ConfigDict(frozen=True)

    total_candidates_examined: int = Field(..., ge=0)
    items_packed_count: int = Field(..., ge=0)
    items_dropped_count: int = Field(..., ge=0)
    billed_tokens_spent: int = Field(..., ge=0)
    billed_tokens_budget: int = Field(..., ge=0)
    billed_tokens_remaining: int = Field(..., ge=0)
    storage_tokens_total: int = Field(..., ge=0)
    storage_tokens_saved: int = Field(..., ge=0)
    budget_utilization_pct: float = Field(..., ge=0.0, le=100.0)
    redundant_tokens_filtered: int = Field(..., ge=0)
    average_marginal_density: float = Field(..., ge=0.0)


class PackedRecallResult(BaseModel):
    """Complete outcome of greedy marginal value recall packing."""

    model_config = ConfigDict(frozen=True)

    packed_items: tuple[PackedCandidateItem, ...]
    dropped_candidates: tuple[DroppedCandidateItem, ...]
    accounting: TokenAccountingReport
    composed_prompt_block: str
    active_mode: str = Field(default="greedy_marginal_knapsack")


# Alias for compatibility
RecallPackingResult = PackedRecallResult
