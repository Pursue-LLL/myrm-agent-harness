"""Score-discontinuity autocut for reranked search results.

Detects the largest score gap in reranked results and truncates below the gap,
keeping only the high-relevance cluster. Operates purely on cross-encoder rerank
scores (the most reliable relevance signal).

[INPUT]
(no external module dependencies — pure algorithm)

[OUTPUT]
- AutocutConfig: dataclass — autocut configuration
- AutocutDecision: dataclass — autocut decision metadata (for logging/debugging)
- apply_autocut: function — compute autocut decision from a sorted score list

[POS]
Score-discontinuity autocut. Detects the largest normalised gap in a
descending-sorted list of rerank scores. If the gap exceeds `jump_ratio`,
results below the gap are truncated. Safe no-op when no significant gap is
found or when fewer than `min_keep + 1` results exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AutocutConfig:
    """Autocut configuration.

    Attributes:
        enabled: Whether autocut is active.
        jump_ratio: Minimum normalised gap to trigger truncation (0.0–1.0).
            Larger values require a bigger score drop before cutting.
        min_keep: Minimum results to keep regardless of score distribution.
    """

    enabled: bool = True
    jump_ratio: float = 0.2
    min_keep: int = 1


@dataclass(frozen=True, slots=True)
class AutocutDecision:
    """Autocut decision metadata (for logging/debugging).

    Attributes:
        original_count: Number of results before autocut.
        kept_count: Number of results after autocut.
        cut_index: Index at which the cut was made (None if no cut).
        max_gap: Largest normalised gap found (None if not applicable).
    """

    original_count: int
    kept_count: int
    cut_index: int | None = None
    max_gap: float | None = None

    @property
    def was_cut(self) -> bool:
        return self.cut_index is not None


def apply_autocut(
    scores: list[float],
    config: AutocutConfig | None = None,
) -> AutocutDecision:
    """Detect the largest score gap and return a truncation decision.

    Algorithm:
    1. Normalise scores to [0, 1] by dividing by max score.
    2. Compute gaps between consecutive normalised scores.
    3. Find the largest gap starting from position `min_keep`.
    4. If the largest gap exceeds `jump_ratio`, truncate at that position.

    Args:
        scores: Descending-sorted rerank scores (highest first).
        config: Autocut configuration (uses defaults if None).

    Returns:
        AutocutDecision with truncation metadata.
    """
    if config is None:
        config = AutocutConfig()

    n = len(scores)

    if not config.enabled or n <= config.min_keep:
        return AutocutDecision(original_count=n, kept_count=n)

    max_score = scores[0]
    if max_score <= 0:
        return AutocutDecision(original_count=n, kept_count=n)

    best_gap = 0.0
    best_gap_idx: int | None = None

    for i in range(max(config.min_keep, 1), n):
        normalised_prev = scores[i - 1] / max_score
        normalised_curr = scores[i] / max_score
        gap = normalised_prev - normalised_curr

        if gap > best_gap:
            best_gap = gap
            best_gap_idx = i

    if best_gap_idx is not None and best_gap >= config.jump_ratio:
        decision = AutocutDecision(
            original_count=n,
            kept_count=best_gap_idx,
            cut_index=best_gap_idx,
            max_gap=best_gap,
        )
        logger.debug(
            f"Autocut triggered: {n} → {best_gap_idx} results "
            f"(gap={best_gap:.3f} at index {best_gap_idx}, "
            f"threshold={config.jump_ratio})"
        )
        return decision

    return AutocutDecision(original_count=n, kept_count=n, max_gap=best_gap)
