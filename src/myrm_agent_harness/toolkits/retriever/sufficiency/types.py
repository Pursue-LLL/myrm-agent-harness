"""Retrieval sufficiency evaluation types.

[INPUT]
- (none — self-contained stdlib dataclass types)

[OUTPUT]
- SufficiencyVerdict: evaluation result (is_sufficient, missing_aspects, suggested_queries, etc.)
- SufficiencyConfig: evaluation configuration (confidence_threshold, max_iterations, etc.)

[POS]
Type definitions for the Retrieval Sufficiency Guard (RSG). Provides structured
result types for sufficiency evaluation and configuration for activation conditions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SufficiencyVerdict:
    """Result of a sufficiency evaluation.

    Attributes:
        is_sufficient: Whether retrieved context adequately covers the query.
        confidence: Evaluator's self-assessed confidence in this judgment (0.0–1.0).
        missing_aspects: Specific information gaps identified.
        suggested_queries: Recommended follow-up search queries to fill gaps.
        negative_constraint_violations: Items in results that violate user's exclusion criteria.
    """

    is_sufficient: bool
    confidence: float = 1.0
    missing_aspects: tuple[str, ...] = ()
    suggested_queries: tuple[str, ...] = ()
    negative_constraint_violations: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SufficiencyConfig:
    """Configuration for sufficiency evaluation activation and behavior.

    Attributes:
        enabled: Master switch. When False, evaluation is never triggered.
        confidence_threshold: Minimum evaluator confidence to act on the verdict.
            Below this, the verdict is discarded (silent pass-through).
        max_iterations: Maximum sufficiency-triggered re-search rounds per query.
        max_snippets_for_eval: Maximum snippet characters sent to the evaluator
            to keep evaluation fast and within lite model context limits.
    """

    enabled: bool = False
    confidence_threshold: float = 0.6
    max_iterations: int = 3
    max_snippets_for_eval: int = 4000
