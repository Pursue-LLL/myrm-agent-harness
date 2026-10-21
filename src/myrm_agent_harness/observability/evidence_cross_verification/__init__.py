"""[INPUT] models and verifier components.
[OUTPUT] Public API exports for multi-source evidence cross-verification and 4-tier confidence scoring.
[POS] myrm_agent_harness.observability.evidence_cross_verification.__init__
"""

from .models import (
    ConfidenceLevel,
    EvidenceItem,
    EvidenceSourceType,
    VerificationDiagnosisRequest,
    VerificationFinding,
)
from .verifier import (
    EvidenceCrossVerificationEngine,
    get_default_evidence_verifier,
)

__all__ = [
    "ConfidenceLevel",
    "EvidenceItem",
    "EvidenceSourceType",
    "VerificationDiagnosisRequest",
    "VerificationFinding",
    "EvidenceCrossVerificationEngine",
    "get_default_evidence_verifier",
]
