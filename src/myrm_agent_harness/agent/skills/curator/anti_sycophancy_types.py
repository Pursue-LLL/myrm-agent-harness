# ============================================================================
# # Anti-Sycophancy & Self-Dismantling Curator Types (Item 149)
# # Strict typed contracts for adversarial review, critic personas,
# # in-context RL exemplars, and transparent memory/skill curation.
# ============================================================================

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import StrEnum


class AdversarialCriticRole(StrEnum):
    """Specialized critic persona to shatter sycophantic alignment traps."""

    ARCHITECT_CRITIC = "architect_critic"  # Attacks design flaws, complexity, and debt
    SECURITY_REDTEAM = "security_redteam"  # Attacks security boundaries, injections, blast radius
    PERFORMANCE_AUDITOR = "performance_auditor"  # Attacks I/O bottlenecks, memory overhead, latency


class CuratedAction(StrEnum):
    """Lifecycle actions determined by the self-dismantling curator."""

    RETAIN = "retain"  # High quality, fresh, active utility
    DISTILL = "distill"  # Redundant or verbose; distilled into concise essence
    PRUNE = "prune"  # Stale, obsolete, or sub-threshold junk
    DEPRECATE = "deprecate"  # Flagged for phased removal


@dataclass(slots=True)
class AdversarialReviewResult:
    """Outcome of adversarial review to eliminate sycophancy and highlight blindspots."""

    critic_role: AdversarialCriticRole
    is_sycophantic: bool
    detected_sycophancy_signals: list[str] = field(default_factory=list)
    critique_summary: str = ""
    potential_pitfalls: list[str] = field(default_factory=list)
    alternative_proposals: list[str] = field(default_factory=list)
    in_context_rl_exemplar: str = ""
    reviewed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, str | bool | float | list[str]]:
        """Serializes review result to standard dictionary."""
        return {
            "critic_role": str(self.critic_role),
            "is_sycophantic": self.is_sycophantic,
            "detected_sycophancy_signals": list(self.detected_sycophancy_signals),
            "critique_summary": self.critique_summary,
            "potential_pitfalls": list(self.potential_pitfalls),
            "alternative_proposals": list(self.alternative_proposals),
            "in_context_rl_exemplar": self.in_context_rl_exemplar,
            "reviewed_at": self.reviewed_at,
        }


@dataclass(slots=True)
class CuratorEvaluationMetric:
    """Quantitative scoring for a memory or skill artifact."""

    relevance_score: float  # 0.0 ~ 1.0 (utility to current goals)
    staleness_score: float  # 0.0 ~ 1.0 (1.0 = completely stale)
    redundancy_score: float  # 0.0 ~ 1.0 (similarity with existing items)
    overall_health: float  # Aggregated composite health index


@dataclass(slots=True)
class CuratedItemVerdict:
    """Curator verdict for an individual memory or skill item."""

    item_id: str
    item_type: str  # "skill" | "memory" | "fact"
    action: CuratedAction
    reason: str
    metric: CuratorEvaluationMetric
    distilled_content: str | None = None


@dataclass(slots=True)
class CuratorCustomRules:
    """User-customizable curation rules powering transparent governance."""

    user_guidelines: list[str] = field(default_factory=list)
    prune_threshold: float = 0.40
    max_staleness_days: int = 30
    dedup_similarity_threshold: float = 0.80
    auto_distill_verbose_items: bool = True


@dataclass(slots=True)
class CuratorDismantlingReport:
    """Full execution report of a self-dismantling curation sweep."""

    scanned_items_count: int
    pruned_count: int
    distilled_count: int
    retained_count: int
    verdicts: list[CuratedItemVerdict] = field(default_factory=list)
    summary_markdown: str = ""
    executed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, int | float | str]:
        """Serializes curation report summary to dictionary."""
        return {
            "scanned_items_count": self.scanned_items_count,
            "pruned_count": self.pruned_count,
            "distilled_count": self.distilled_count,
            "retained_count": self.retained_count,
            "summary_markdown": self.summary_markdown,
            "executed_at": self.executed_at,
        }
