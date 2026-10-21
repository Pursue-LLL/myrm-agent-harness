"""Marginal value evaluator for recall candidates.

Calculates redundancy against previously accepted candidates using Jaccard and n-gram overlap,
and derives marginal information gain, marginal value, and value density.

[INPUT]
- models::RecallCandidate, BilledTokenBudget, MarginalValueMetrics (POS: Domain models)

[OUTPUT]
- MarginalValueEvaluator: Stateless evaluator calculating marginal utility and diversity metrics.

[POS]
Semantic overlap and marginal value calculation engine.
"""

from __future__ import annotations

import re
from typing import Final

from myrm_agent_harness.toolkits.memory.budget_packing.models import (
    BilledTokenBudget,
    MarginalValueMetrics,
    RecallCandidate,
)

_WORD_SPLIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\w\u4e00-\u9fa5]+", re.UNICODE)
_STOP_WORDS: Final[set[str]] = {
    "the", "a", "an", "is", "are", "was", "were", "to", "in", "on", "at", "by", "for", "with",
    "and", "or", "of", "it", "this", "that", "these", "those", "be", "as", "from",
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一", "一个", "上", "也", "很", "到", "说", "要", "去",
}


def _tokenize(text: str) -> set[str]:
    """Extract lowercased tokens and bi-grams from text, excluding common stopwords."""
    raw_tokens = [w.lower() for w in _WORD_SPLIT_PATTERN.findall(text)]
    filtered_tokens = [w for w in raw_tokens if w not in _STOP_WORDS and len(w) > 0]
    token_set: set[str] = set(filtered_tokens)

    # Add character bi-grams for short CJK words to catch semantic overlap
    for token in filtered_tokens:
        if len(token) >= 2:
            for i in range(len(token) - 1):
                token_set.add(token[i : i + 2])

    return token_set


def compute_text_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    """Compute Jaccard similarity between two token sets in [0.0, 1.0]."""
    if not tokens_a or not tokens_b:
        return 0.0
    intersection_size = len(tokens_a & tokens_b)
    union_size = len(tokens_a | tokens_b)
    if union_size == 0:
        return 0.0
    return float(intersection_size) / float(union_size)


class MarginalValueEvaluator:
    """Stateless marginal value evaluator for recall candidates."""

    def __init__(self, budget_config: BilledTokenBudget | None = None) -> None:
        self._config = budget_config or BilledTokenBudget()

    def evaluate_candidate(
        self,
        candidate: RecallCandidate,
        already_packed: tuple[RecallCandidate, ...],
    ) -> MarginalValueMetrics:
        """Evaluate marginal value of candidate given already selected items."""
        base_utility = max(0.0, min(1.0, candidate.relevance_score * candidate.confidence_score))

        if not already_packed:
            # First item has zero redundancy, maximum marginal gain
            marginal_value = base_utility
            density = marginal_value / max(1, candidate.billed_tokens)
            return MarginalValueMetrics(
                base_utility=base_utility,
                redundancy_score=0.0,
                marginal_info_gain=1.0,
                marginal_value=round(marginal_value, 5),
                marginal_value_density=round(density, 6),
            )

        candidate_tokens = _tokenize(candidate.content)

        # Max redundancy against any already packed candidate
        max_redundancy = 0.0
        for packed_item in already_packed:
            packed_tokens = _tokenize(packed_item.content)
            sim = compute_text_similarity(candidate_tokens, packed_tokens)
            if sim > max_redundancy:
                max_redundancy = sim

        max_redundancy = min(1.0, max_redundancy)
        penalty_lambda = max(0.0, min(1.0, self._config.diversity_penalty_lambda))

        # Marginal Information Gain = 1.0 - lambda * redundancy
        marginal_info_gain = max(0.0, 1.0 - (penalty_lambda * max_redundancy))
        marginal_value = base_utility * marginal_info_gain
        density = marginal_value / max(1, candidate.billed_tokens)

        return MarginalValueMetrics(
            base_utility=round(base_utility, 5),
            redundancy_score=round(max_redundancy, 5),
            marginal_info_gain=round(marginal_info_gain, 5),
            marginal_value=round(marginal_value, 5),
            marginal_value_density=round(density, 6),
        )
