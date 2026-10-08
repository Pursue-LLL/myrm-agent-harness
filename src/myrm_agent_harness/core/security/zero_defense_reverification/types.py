"""Type definitions for Zero-Defense Error Acknowledgment and Grounded Re-Verification Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class DisputeIntentType(StrEnum):
    """Classification of user challenge, correction, or dispute intention."""

    FACTUAL_ERROR = "FACTUAL_ERROR"  # Factual statement contradiction ("That is factually wrong")
    CALCULATION_ERROR = "CALCULATION_ERROR"  # Numeric or accounting discrepancy ("You calculated this wrong")
    LEGAL_COMPLIANCE_ERROR = "LEGAL_COMPLIANCE_ERROR"  # Clause or compliance misinterpretation
    HALLUCINATION_ACCUSATION = "HALLUCINATION_ACCUSATION"  # Claiming agent hallucinated or fabricated data
    AMBIGUOUS_DOUBT = "AMBIGUOUS_DOUBT"  # General doubt or request to re-check


class VerificationVerdict(StrEnum):
    """Outcome of grounded evidence re-verification cross-check."""

    CORRECTED = "CORRECTED"  # Prior conclusion corrected by fresh evidence
    CONFIRMED_USER_CORRECT = "CONFIRMED_USER_CORRECT"  # User objection explicitly verified as right
    AMBIGUOUS_ESCALATE = "AMBIGUOUS_ESCALATE"  # Conflict persists, requires human domain expert escalation
    VERIFIED_ACCURATE = "VERIFIED_ACCURATE"  # Prior conclusion proved accurate with verified citations


@dataclass(slots=True, frozen=True)
class EvidenceCitation:
    """Rigorous grounded citation referencing exact source file and location."""

    source_path: str
    line_or_location: str
    quote_snippet: str


@dataclass(slots=True, frozen=True)
class DisputeDetectionResult:
    """Result of detecting a user dispute or challenge in dialogue."""

    is_dispute: bool
    intent_type: DisputeIntentType | None
    dispute_anchor: str
    mandatory_protocol_phrase: str


@dataclass(slots=True, frozen=True)
class GroundedReVerificationResult:
    """Side-by-side grounded comparison between prior conclusion and verified citations."""

    dispute_anchor: str
    prior_conclusion: str
    evidence_citations: list[EvidenceCitation]
    verdict: VerificationVerdict
    requires_expert_escalation: bool
    correction_explanation: str


@dataclass(slots=True)
class ExpertEscalationTicket:
    """Ticket created for human legal, financial, or domain expert review."""

    ticket_id: str
    session_id: str
    risk_domain: str
    dispute_summary: str
    prior_conclusion: str
    evidence_citations: list[EvidenceCitation] = field(default_factory=list)
    created_at: float = 0.0
    status: str = "OPEN"
    resolution_notes: str | None = None
