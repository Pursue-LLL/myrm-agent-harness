"""Type definitions for ChangeGuard review decision lanes and evidence hardening.

[INPUT]
- None.

[OUTPUT]
- Strongly typed enums, dataclasses, and evidence structures for ChangeGuard (WS1-WS5).

[POS]
- Harness core security module implementing deterministic vs review lanes,
  material-change classification, and hardened evidence bindings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CanonicalOutcome(StrEnum):
    """Canonical review decision outcome mapped from policy DSL."""

    PASS = "pass"
    WARN = "warn"
    REVIEW_REQUIRED = "review-required"
    BLOCK = "block"


class DecisionLane(StrEnum):
    """Review decision lane (WS1).

    LANE_A: Deterministic automated gate (Pass/Block/Warn).
    LANE_B: Mandatory-review human governance questions (Review-required).
    """

    LANE_A = "lane_a"
    LANE_B = "lane_b"


class ChangeClass(StrEnum):
    """Classification of material authority or configuration delta (WS2)."""

    NO_CHANGE = "NO_CHANGE"
    UNKNOWN = "UNKNOWN"
    LOW_CHANGE = "LOW_CHANGE"
    MATERIAL_CHANGE = "MATERIAL_CHANGE"
    HIGH_RISK_CHANGE = "HIGH_RISK_CHANGE"


class ProvenanceClass(StrEnum):
    """Classification of evidence origin and certainty (WS3)."""

    DECLARED = "declared"
    DETECTED = "detected"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class Gateability(StrEnum):
    """Whether finding can trip an automated gate or requires review (WS3)."""

    DETERMINISTIC = "deterministic"
    REVIEW_ONLY = "review-only"


class EvidenceType(StrEnum):
    """Hardened evidence type specification (WS3)."""

    STATIC_CONFIG = "static-config"
    STATIC_PATTERN = "static-pattern"
    RUNTIME_OBSERVED = "runtime-observed"
    DIFF_INSPECTION = "diff-inspection"


@dataclass(frozen=True)
class EvidenceRecord:
    """Immutable, auditable evidence item attached to a change finding."""

    evidence_type: EvidenceType
    source_file: str
    line_number: int | None = None
    pattern_matched: str | None = None
    sha256_digest: str | None = None
    description: str = ""


@dataclass(frozen=True)
class HardenedFinding:
    """Security or governance change finding carrying hardened evidence."""

    finding_id: str
    rule_id: str
    category: str
    target_object: str
    change_class: ChangeClass
    provenance_class: ProvenanceClass
    gateability: Gateability
    evidence: EvidenceRecord
    message: str


@dataclass(frozen=True)
class ChangeGuardException:
    """File-backed auditable exemption record (WS4)."""

    exception_id: str
    finding_or_rule_id: str
    scope: str
    risk_owner: str
    rationale: str
    compensating_controls: str
    expires_at: str
    review_trigger: str = "manual"

    def is_expired(self, current_time_iso: str) -> bool:
        """Check whether the exception has expired against current ISO timestamp."""
        return current_time_iso >= self.expires_at


@dataclass(frozen=True)
class LaneDecisionSummary:
    """Summary of decisions and unresolved questions within a specific lane."""

    lane: DecisionLane
    outcome: CanonicalOutcome
    findings: tuple[HardenedFinding, ...]
    unresolved_questions: tuple[str, ...]


@dataclass(frozen=True)
class ChangeGuardPolicyConfig:
    """Configuration for ChangeGuard authority and lane enforcement."""

    fail_on_authority_change: ChangeClass | None = None
    enforce_definition_review_floor: bool = True
    strict_exceptions: bool = False


@dataclass(frozen=True)
class ChangeGuardEvaluationResult:
    """Final auditable outcome of ChangeGuard evaluation across all lanes."""

    overall_outcome: CanonicalOutcome
    lane_a: LaneDecisionSummary
    lane_b: LaneDecisionSummary
    highest_change_class: ChangeClass
    applied_exceptions: tuple[str, ...]
    stale_or_expired_exceptions: tuple[str, ...]
