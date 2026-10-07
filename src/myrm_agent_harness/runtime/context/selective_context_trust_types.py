"""Types for selective context preference optimization and misleading signal gate (SCOPE).

Defines taxonomy for four-condition context evaluation (Clean, Correct, Irrelevant, Misleading),
selective trust arbitration decisions, conflict assessments, and SC2W defense telemetry.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class ContextConditionKind(StrEnum):
    """Four-condition context taxonomy from SCOPE benchmark."""

    CLEAN = "CLEAN"  # Baseline with no external adversarial noise
    CORRECT = "CORRECT"  # Verifiable external evidence supporting ground truth
    IRRELEVANT = "IRRELEVANT"  # Distracting noise with no utility
    MISLEADING = "MISLEADING"  # Fabricated, adversarial, or stale misinformation


class TrustDecisionKind(StrEnum):
    """Selective trust arbitration outcome."""

    TRUST_EXTERNAL = "TRUST_EXTERNAL"  # Accept external evidence into context
    RELY_ON_INTERNAL_PRIOR = "RELY_ON_INTERNAL_PRIOR"  # Discard external signal, keep prior
    SANITIZE_AND_WARN = "SANITIZE_AND_WARN"  # Strip conflicting segments and attach warning
    DISCARD_IRRELEVANT = "DISCARD_IRRELEVANT"  # Filter out irrelevant noise to save tokens


@dataclass(frozen=True)
class ContextEvidenceSignal:
    """External retrieved context snippet or tool execution output."""

    signal_id: str
    source: str
    content: str
    confidence_score: float = 1.0
    timestamp: str = ""


@dataclass(frozen=True)
class PriorFactAssertion:
    """Established internal prior fact or system invariant."""

    fact_id: str
    statement: str
    is_immutable: bool = True
    domain_tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ConflictAssessmentResult:
    """Detailed conflict analysis between external evidence and established priors."""

    condition: ContextConditionKind
    contradiction_score: float
    prior_consistency_score: float
    identified_conflicts: list[str] = field(default_factory=list)
    relevance_score: float = 1.0


@dataclass(frozen=True)
class SelectiveTrustDecision:
    """Arbitration verdict indicating whether and how to incorporate external context."""

    decision: TrustDecisionKind
    condition: ContextConditionKind
    reason: str
    accepted_content: str | None = None
    warning_annotation: str | None = None
    is_misleading_intercepted: bool = False


@dataclass
class SCOPETelemetryStats:
    """Telemetry counters monitoring selective trust accuracy and SC2W defense."""

    total_evaluated: int = 0
    clean_count: int = 0
    correct_count: int = 0
    irrelevant_count: int = 0
    misleading_intercepted_count: int = 0
    sc2w_prevented_count: int = 0
