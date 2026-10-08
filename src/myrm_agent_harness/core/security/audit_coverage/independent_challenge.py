"""Independent adversarial challenge reviewer for security audit findings.

[INPUT]
- AuditFinding, challenge context or counter-evidence.

[OUTPUT]
- Challenged AuditFinding with updated ChallengeVerdict and notes.

[POS]
- Harness core security engine. Subject findings to independent adversarial
  re-evaluation to eliminate false positives before final disclosure.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.core.security.audit_coverage.types import (
    AuditFinding,
    ChallengeVerdict,
)

logger = logging.getLogger(__name__)

COMMON_MITIGATION_INDICATORS: tuple[str, ...] = (
    "csrf_token",
    "ratelimit",
    "rate_limit",
    "param_binding",
    "prepared_statement",
    "jwt_verify",
    "oauth2",
    "constant_time_compare",
)


class IndependentChallengeReviewer:
    """Adversarially challenges security findings to refute false positives."""

    def __init__(self, mitigation_indicators: Sequence[str] | None = None) -> None:
        self._indicators = tuple(mitigation_indicators or COMMON_MITIGATION_INDICATORS)

    def challenge_finding(
        self,
        finding: AuditFinding,
        codebase_context: str = "",
    ) -> AuditFinding:
        """Evaluate finding against existing codebase defenses to confirm or refute."""
        context_lower = codebase_context.lower()
        evidence_lower = finding.evidence.lower()

        # Check if an existing mitigation disproves the vulnerability
        refutation_reasons: list[str] = []
        for ind in self._indicators:
            if ind in context_lower and ind not in evidence_lower:
                refutation_reasons.append(f"Mitigation '{ind}' is present in active context")

        if refutation_reasons:
            verdict = ChallengeVerdict.CHALLENGED_REFUTED
            notes = f"Finding refuted: {'; '.join(refutation_reasons)}"
            logger.info("Adversarial challenge refuted finding %s: %s", finding.finding_id, notes)
        else:
            verdict = ChallengeVerdict.CHALLENGED_CONFIRMED
            notes = "Adversarial challenge confirmed: No mitigating controls detected."

        return AuditFinding(
            finding_id=finding.finding_id,
            category=finding.category,
            severity=finding.severity,
            title=finding.title,
            description=finding.description,
            application_model_ref=finding.application_model_ref,
            evidence=finding.evidence,
            challenge_status=verdict,
            challenge_notes=notes,
            verification_tier=finding.verification_tier,
        )
