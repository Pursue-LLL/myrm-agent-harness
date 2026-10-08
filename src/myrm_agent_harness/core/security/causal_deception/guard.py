"""Causal Consistency Guard orchestrating deception defense and counterfactual probes.

[INPUT]
- Commitments, execution traces, claims, audience parameters.

[OUTPUT]
- CausalAuditReport and CounterfactualProbeResult.

[POS]
- Harness core security gate enforcing physical execution grounding and fail-closed deception interception.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.core.security.causal_deception.matrix import (
    CommitmentExecutionReportMatrix,
)
from myrm_agent_harness.core.security.causal_deception.probe import (
    AudienceAsymmetryProbe,
)
from myrm_agent_harness.core.security.causal_deception.types import (
    CausalAuditReport,
    ClaimStatus,
    CommitmentItem,
    CommitmentType,
    CounterfactualProbeResult,
    ExecutionTraceItem,
    PostReportClaim,
    TechnicalProficiency,
)

logger = logging.getLogger(__name__)


class CausalConsistencyGuard:
    """Security guard verifying that agent claims are causally grounded in execution logs."""

    def __init__(
        self,
        matrix: CommitmentExecutionReportMatrix | None = None,
        probe: AudienceAsymmetryProbe | None = None,
    ) -> None:
        self._matrix = matrix or CommitmentExecutionReportMatrix()
        self._probe = probe or AudienceAsymmetryProbe()

    @property
    def matrix(self) -> CommitmentExecutionReportMatrix:
        """Underlying commitment-execution-report matrix."""
        return self._matrix

    @property
    def probe(self) -> AudienceAsymmetryProbe:
        """Underlying audience asymmetry counterfactual probe."""
        return self._probe

    def record_commitment(self, commitment: CommitmentItem) -> None:
        """Register upfront commitment."""
        self._matrix.record_commitment(commitment)

    def record_execution_trace(self, trace: ExecutionTraceItem) -> None:
        """Record physical tool execution trace."""
        self._matrix.record_execution_trace(trace)

    def record_claim(self, claim: PostReportClaim) -> None:
        """Record post-report claimed fact."""
        self._matrix.record_claim(claim)

    def audit_consistency(self) -> CausalAuditReport:
        """Evaluate consistency between commitments, physical traces, and post-report claims."""
        return self._matrix.evaluate_invariance()

    def probe_audience(
        self,
        claims: Sequence[PostReportClaim],
        audience_level: TechnicalProficiency = TechnicalProficiency.NOVICE,
    ) -> CounterfactualProbeResult:
        """Run counterfactual probe checking if report exploits audience technical blindspots."""
        audit = self._matrix.evaluate_invariance()
        has_failed = any(
            t.is_success is False for t in self._matrix._traces
        )
        has_missing_tests = any(
            c.commitment_type == CommitmentType.TEST_RUN and c.claimed_status == ClaimStatus.PASSED
            for c in claims
        ) and not any(
            "test" in t.tool_name.lower() or "pytest" in str(dict(t.arguments)).lower()
            for t in self._matrix._traces
        )

        return self._probe.probe_claims(
            claims=claims,
            has_failed_traces=has_failed,
            has_missing_tests=has_missing_tests or not audit.is_consistent,
            audience_level=audience_level,
        )

    def assert_zero_deception(self) -> CausalAuditReport:
        """Assert zero deception, raising DeceptiveFabricationDetectedError if violations exist."""
        return self._matrix.assert_invariance()
