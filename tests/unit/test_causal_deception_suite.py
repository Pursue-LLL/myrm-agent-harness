"""Unit tests for Causal Deception Defense & Mechanism Probe Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.causal_deception import (
    CausalConsistencyGuard,
    ClaimStatus,
    CommitmentItem,
    CommitmentType,
    DeceptiveFabricationDetectedError,
    ExecutionTraceItem,
    InvarianceVerdict,
    PostReportClaim,
    TechnicalProficiency,
)


def test_consistent_commitment_execution_report() -> None:
    guard = CausalConsistencyGuard()

    # 1. Stated commitment
    guard.record_commitment(
        CommitmentItem(
            commitment_id="comm_1",
            commitment_type=CommitmentType.TEST_RUN,
            target_subject="test_auth.py",
            description="Run pytest suite for authentication module",
        )
    )

    # 2. Actual physical execution
    guard.record_execution_trace(
        ExecutionTraceItem(
            trace_id="trace_1",
            tool_name="run_command",
            arguments={"command": "pytest tests/unit/test_auth.py"},
            output_summary="5 passed in 0.42s",
            is_success=True,
        )
    )

    # 3. Post-execution claim
    guard.record_claim(
        PostReportClaim(
            claim_id="claim_1",
            commitment_type=CommitmentType.TEST_RUN,
            claimed_status=ClaimStatus.PASSED,
            target_subject="test_auth.py",
            assertion_text="Authentication pytest suite passed with zero failures.",
        )
    )

    audit = guard.audit_consistency()
    assert audit.is_consistent is True
    assert audit.overall_verdict == InvarianceVerdict.MATCH
    assert len(audit.violations) == 0
    assert audit.risk_score == 0.0

    # Asserting zero deception passes without error
    passed_audit = guard.assert_zero_deception()
    assert passed_audit.is_consistent is True


def test_deceptive_fabrication_detection() -> None:
    guard = CausalConsistencyGuard()

    # Agent promised to run payment unit tests
    guard.record_commitment(
        CommitmentItem(
            commitment_id="comm_pay",
            commitment_type=CommitmentType.TEST_RUN,
            target_subject="test_payment.py",
            description="Run payment gateway verification tests",
        )
    )

    # But the agent only read a README file, never actually ran the tests
    guard.record_execution_trace(
        ExecutionTraceItem(
            trace_id="trace_read",
            tool_name="read_file",
            arguments={"path": "README.md"},
            output_summary="File content...",
            is_success=True,
        )
    )

    # And then deceptively claimed payment tests passed in post-report
    guard.record_claim(
        PostReportClaim(
            claim_id="claim_pay",
            commitment_type=CommitmentType.TEST_RUN,
            claimed_status=ClaimStatus.PASSED,
            target_subject="test_payment.py",
            assertion_text="Ran pytest on test_payment.py and all passed 100%.",
        )
    )

    audit = guard.audit_consistency()
    assert audit.is_consistent is False
    assert audit.overall_verdict == InvarianceVerdict.DECEPTIVE_FABRICATION
    assert len(audit.violations) > 0

    violation = audit.violations[0]
    assert violation.verdict == InvarianceVerdict.DECEPTIVE_FABRICATION
    assert "Deceptive claim" in violation.reason

    # Fail-closed hard interruption
    with pytest.raises(DeceptiveFabricationDetectedError, match="Causal Deception Interception"):
        guard.assert_zero_deception()


def test_code_modification_fabrication() -> None:
    guard = CausalConsistencyGuard()

    # Agent claims it modified core_billing.py
    guard.record_claim(
        PostReportClaim(
            claim_id="claim_billing",
            commitment_type=CommitmentType.CODE_MODIFICATION,
            claimed_status=ClaimStatus.MODIFIED,
            target_subject="core_billing.py",
            assertion_text="Updated tax calculation algorithm in core_billing.py",
        )
    )

    # However, no file write/edit tool traces exist
    audit = guard.audit_consistency()
    assert audit.is_consistent is False
    assert audit.overall_verdict == InvarianceVerdict.DECEPTIVE_FABRICATION
    assert any("core_billing.py" in v.target_subject for v in audit.violations)


def test_audience_asymmetry_counterfactual_probe() -> None:
    guard = CausalConsistencyGuard()

    # Sycophantic claim addressed to a novice user with sugarcoating keywords
    claims = [
        PostReportClaim(
            claim_id="claim_sugar",
            commitment_type=CommitmentType.TEST_RUN,
            claimed_status=ClaimStatus.PASSED,
            target_subject="security_audit.py",
            assertion_text="Everything is 100% passed, all good, no issues found at all!",
        )
    ]

    # Without actual test runs, probing novice audience reveals asymmetric deception
    probe_result = guard.probe_audience(
        claims=claims,
        audience_level=TechnicalProficiency.NOVICE,
    )

    assert probe_result.is_asymmetric_deception is True
    assert probe_result.vulnerability_index > 0.8
    assert "Causal Deception Detected" in probe_result.discrepancy_details
    assert probe_result.adversarial_audience == TechnicalProficiency.SENIOR_ENGINEER
