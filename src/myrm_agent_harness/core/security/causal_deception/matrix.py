"""Commitment-Execution-Report Invariance Matrix for causal consistency verification.

[INPUT]
- CommitmentItem, ExecutionTraceItem, PostReportClaim.

[OUTPUT]
- CausalAuditReport with InvarianceVerdict and detected violations.

[POS]
- Harness core security engine. Audits whether post-report claims are causally grounded
  in physical tool execution traces rather than fabricated to appease the user.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from myrm_agent_harness.core.security.causal_deception.types import (
    CausalAuditReport,
    ClaimStatus,
    CommitmentItem,
    CommitmentType,
    DeceptiveFabricationDetectedError,
    ExecutionTraceItem,
    InvarianceVerdict,
    InvarianceViolation,
    PostReportClaim,
)

logger = logging.getLogger(__name__)

TEST_TOOL_KEYWORDS: tuple[str, ...] = ("test", "pytest", "unittest", "vitest", "jest", "run_command")
EDIT_TOOL_KEYWORDS: tuple[str, ...] = ("write", "edit", "replace", "modify", "patch", "create_file")


class CommitmentExecutionReportMatrix:
    """Evaluates three-way consistency between commitments, execution traces, and claims."""

    def __init__(self) -> None:
        self._commitments: list[CommitmentItem] = []
        self._traces: list[ExecutionTraceItem] = []
        self._claims: list[PostReportClaim] = []

    def record_commitment(self, commitment: CommitmentItem) -> None:
        """Register an upfront commitment made in planning or turn statement."""
        self._commitments.append(commitment)

    def record_commitments(self, commitments: Sequence[CommitmentItem]) -> None:
        """Batch register upfront commitments."""
        self._commitments.extend(commitments)

    def record_execution_trace(self, trace: ExecutionTraceItem) -> None:
        """Log an actual physical tool invocation from runtime execution."""
        self._traces.append(trace)

    def record_execution_traces(self, traces: Sequence[ExecutionTraceItem]) -> None:
        """Batch log physical tool invocations."""
        self._traces.extend(traces)

    def record_claim(self, claim: PostReportClaim) -> None:
        """Register a factual statement asserted in the post-execution report."""
        self._claims.append(claim)

    def record_claims(self, claims: Sequence[PostReportClaim]) -> None:
        """Batch register factual statements from the post-execution report."""
        self._claims.extend(claims)

    def clear(self) -> None:
        """Reset internal records for a fresh audit cycle."""
        self._commitments.clear()
        self._traces.clear()
        self._claims.clear()

    def _has_matching_execution(self, claim: PostReportClaim) -> bool:
        """Check whether physical execution logs support the post-report claim."""
        target_lower = claim.target_subject.lower()

        if claim.commitment_type == CommitmentType.TEST_RUN:
            for trace in self._traces:
                tool_lower = trace.tool_name.lower()
                is_test_tool = any(kw in tool_lower for kw in TEST_TOOL_KEYWORDS)
                if not is_test_tool:
                    continue
                # If command execution, inspect arguments
                args_str = str(dict(trace.arguments)).lower()
                if "pytest" in args_str or "test" in args_str or target_lower in args_str or not target_lower:
                    if claim.claimed_status == ClaimStatus.PASSED:
                        return trace.is_success
                    return True
            return False

        if claim.commitment_type == CommitmentType.CODE_MODIFICATION:
            for trace in self._traces:
                tool_lower = trace.tool_name.lower()
                is_edit_tool = any(kw in tool_lower for kw in EDIT_TOOL_KEYWORDS)
                if not is_edit_tool:
                    continue
                args_str = str(dict(trace.arguments)).lower()
                if target_lower in args_str or not target_lower:
                    return trace.is_success
            return False

        if claim.commitment_type == CommitmentType.FILE_READ:
            for trace in self._traces:
                tool_lower = trace.tool_name.lower()
                if "read" in tool_lower or "view" in tool_lower or "grep" in tool_lower:
                    args_str = str(dict(trace.arguments)).lower()
                    if target_lower in args_str or not target_lower:
                        return True
            return False

        # Generic command or external API tool matching
        for trace in self._traces:
            args_str = str(dict(trace.arguments)).lower()
            if target_lower in trace.tool_name.lower() or target_lower in args_str:
                return trace.is_success

        return False

    def evaluate_invariance(self) -> CausalAuditReport:
        """Evaluate three-way consistency, returning comprehensive audit verdict."""
        violations: list[InvarianceViolation] = []

        for claim in self._claims:
            has_exec = self._has_matching_execution(claim)

            if not has_exec:
                # Claim asserts success/modification/pass without execution record
                if claim.claimed_status in (ClaimStatus.PASSED, ClaimStatus.MODIFIED, ClaimStatus.VERIFIED):
                    verdict = InvarianceVerdict.DECEPTIVE_FABRICATION
                    reason = (
                        f"Deceptive claim: Reported '{claim.assertion_text}' for subject "
                        f"'{claim.target_subject}', but no matching physical execution traces exist."
                    )
                else:
                    verdict = InvarianceVerdict.UNVERIFIED_CLAIM
                    reason = f"Unverified claim: '{claim.assertion_text}' lacks corroborating execution traces."

                violations.append(
                    InvarianceViolation(
                        claim_id=claim.claim_id,
                        verdict=verdict,
                        reason=reason,
                        target_subject=claim.target_subject,
                    )
                )

        # Check if committed items were entirely ignored without explanation
        for comm in self._commitments:
            matching_claims = [c for c in self._claims if c.target_subject == comm.target_subject]
            if not matching_claims and comm.commitment_type in (
                CommitmentType.TEST_RUN,
                CommitmentType.CODE_MODIFICATION,
            ):
                violations.append(
                    InvarianceViolation(
                        claim_id=f"comm_unfulfilled_{comm.commitment_id}",
                        verdict=InvarianceVerdict.UNVERIFIED_CLAIM,
                        reason=f"Commitment '{comm.description}' was stated but omitted from post-report.",
                        target_subject=comm.target_subject,
                    )
                )

        is_consistent = len(violations) == 0
        overall_verdict = (
            InvarianceVerdict.MATCH
            if is_consistent
            else (
                InvarianceVerdict.DECEPTIVE_FABRICATION
                if any(v.verdict == InvarianceVerdict.DECEPTIVE_FABRICATION for v in violations)
                else InvarianceVerdict.UNVERIFIED_CLAIM
            )
        )
        risk_score = 0.0 if is_consistent else min(1.0, len(violations) * 0.35)

        return CausalAuditReport(
            is_consistent=is_consistent,
            total_commitments=len(self._commitments),
            total_traces=len(self._traces),
            total_claims=len(self._claims),
            violations=tuple(violations),
            overall_verdict=overall_verdict,
            risk_score=risk_score,
        )

    def assert_invariance(self) -> CausalAuditReport:
        """Evaluate consistency and fail-closed with exception if deception is detected."""
        report = self.evaluate_invariance()
        if not report.is_consistent and report.overall_verdict == InvarianceVerdict.DECEPTIVE_FABRICATION:
            reasons = "; ".join(v.reason for v in report.violations)
            raise DeceptiveFabricationDetectedError(
                f"Causal Deception Interception: Post-report contains fabricated assertions "
                f"unsupported by actual execution logs: {reasons}"
            )
        return report
