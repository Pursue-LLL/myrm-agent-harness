"""Unit tests for Security Audit Explicit Coverage & Replayable Repair Bundle Suite."""

from __future__ import annotations

import pytest

from myrm_agent_harness.core.security.audit_coverage import (
    ApplicationModel,
    AuditCoverageEngine,
    AuditFinding,
    ChallengeVerdict,
    CoverageCategory,
    CoverageScopeItem,
    CoverageStatus,
    FindingSeverity,
    RepairBundleVerificationError,
    RepairPatch,
    UnsupportedFindingError,
    VerificationTier,
)


@pytest.fixture
def sample_app_model() -> ApplicationModel:
    return ApplicationModel(
        name="PaymentGatewayService",
        tech_stack=("Python 3.13", "FastAPI", "PostgreSQL", "Redis"),
        entrypoints=("/api/v1/charge", "/api/v1/refund", "/webhooks/stripe"),
        trust_boundaries=("External Internet -> Ingress WAF", "API Gateway -> Internal DB"),
        data_flows=("Payment token from client", "Webhook verification"),
        supported_finding_categories=(
            "AUTH_ACCESS_CONTROL",
            "INPUT_VALIDATION_INJECTION",
            "SECRET_LEAKAGE",
        ),
    )


def test_explicit_coverage_disclosure(sample_app_model: ApplicationModel) -> None:
    engine = AuditCoverageEngine(application_model=sample_app_model)

    # Explicitly register audited scopes
    engine.register_scope(
        CoverageScopeItem(
            category=CoverageCategory.AUTH_ACCESS_CONTROL,
            status=CoverageStatus.COVERED,
            audit_surface="Checked JWT, RBAC scopes, and API endpoint gates",
            coverage_percentage=100.0,
        )
    )
    engine.register_scope(
        CoverageScopeItem(
            category=CoverageCategory.INPUT_VALIDATION_INJECTION,
            status=CoverageStatus.PARTIALLY_COVERED,
            audit_surface="Pydantic schema validation checked; SQL injection covered",
            coverage_percentage=80.0,
        )
    )

    report = engine.generate_coverage_report()

    # All 6 standard categories must be explicitly disclosed
    assert len(report.scopes) == len(CoverageCategory)

    # Check that unregistered categories are explicitly marked as UNCOVERED
    secret_scope = next(s for s in report.scopes if s.category == CoverageCategory.SECRET_LEAKAGE)
    assert secret_scope.status == CoverageStatus.UNCOVERED_UNSUPPORTED
    assert secret_scope.uncovered_reason is not None
    assert secret_scope.coverage_percentage == 0.0

    # Overall coverage is accurately computed
    assert report.overall_coverage_percentage == round((100.0 + 80.0) / len(CoverageCategory), 2)


def test_application_model_boundary_contract(sample_app_model: ApplicationModel) -> None:
    engine = AuditCoverageEngine(application_model=sample_app_model)

    # Finding category within supported model categories is accepted
    valid_finding = AuditFinding(
        finding_id="find_01",
        category="AUTH_ACCESS_CONTROL",
        severity=FindingSeverity.HIGH,
        title="Missing scope check on /api/v1/refund",
        description="Endpoint allows refund without refund:write permission",
        application_model_ref="/api/v1/refund",
        evidence="def refund(): pass without Depends(verify_scope)",
    )
    recorded = engine.record_finding(valid_finding, codebase_context="")
    assert recorded.finding_id == "find_01"

    # Unsupported category outside application model raises UnsupportedFindingError
    invalid_finding = AuditFinding(
        finding_id="find_02",
        category="CONCURRENCY_STATE_INTEGRITY",  # Not in supported_finding_categories
        severity=FindingSeverity.MEDIUM,
        title="Race condition in ledger balance",
        description="Concurrent updates may desync balance",
        application_model_ref="/api/v1/charge",
        evidence="No distributed lock found",
    )
    with pytest.raises(UnsupportedFindingError, match="outside the supported categories"):
        engine.record_finding(invalid_finding)


def test_independent_adversarial_challenge_refutation(sample_app_model: ApplicationModel) -> None:
    engine = AuditCoverageEngine(application_model=sample_app_model)

    finding = AuditFinding(
        finding_id="find_rate_limit",
        category="AUTH_ACCESS_CONTROL",
        severity=FindingSeverity.MEDIUM,
        title="Potential brute force risk on login",
        description="No throttling seen in raw handler",
        application_model_ref="/api/v1/charge",
        evidence="def charge(): ...",
    )

    # When codebase context shows active mitigation (e.g. rate_limit decorator)
    context_with_defense = "@rate_limit(limit='10/minute')\ndef charge(): pass"
    challenged = engine.record_finding(finding, codebase_context=context_with_defense)

    assert challenged.challenge_status == ChallengeVerdict.CHALLENGED_REFUTED
    assert "Mitigation 'rate_limit' is present" in challenged.challenge_notes

    # Refuted findings are omitted from active audit report
    report = engine.generate_coverage_report()
    assert len(report.findings) == 0


def test_replayable_repair_bundle_creation_and_verification(
    sample_app_model: ApplicationModel,
) -> None:
    engine = AuditCoverageEngine(application_model=sample_app_model)

    finding = AuditFinding(
        finding_id="find_secret",
        category="SECRET_LEAKAGE",
        severity=FindingSeverity.CRITICAL,
        title="Hardcoded API key in client.py",
        description="Found test secret in source code",
        application_model_ref="/api/v1/charge",
        evidence='API_KEY = "sk-live-123"',
    )
    engine.record_finding(finding, codebase_context="")

    patches = [
        RepairPatch(
            file_path="src/client.py",
            target_checksum="hash_abc",
            diff_content="- API_KEY = 'sk-live-123'\n+ API_KEY = os.environ['API_KEY']",
            replay_command="git apply repair.patch",
        )
    ]

    # Attach and verify repair bundle
    bundle = engine.attach_repair_bundle(
        finding_id="find_secret",
        patches=patches,
        replay_script="pytest tests/test_client.py",
        verify_immediately=True,
    )

    assert bundle.is_verified is True
    assert bundle.checksum != ""
    assert len(bundle.patches) == 1

    # Finding tier should be upgraded from SELF_REPORTED to TESTED
    report = engine.generate_coverage_report()
    assert len(report.findings) == 1
    updated_finding = report.findings[0]
    assert updated_finding.verification_tier == VerificationTier.TESTED
    assert len(report.repair_bundles) == 1


def test_tampered_repair_bundle_fails_verification(sample_app_model: ApplicationModel) -> None:
    from myrm_agent_harness.core.security.audit_coverage.repair_bundle import (
        ReplayableRepairEngine,
    )

    repair_engine = ReplayableRepairEngine()
    finding = AuditFinding(
        finding_id="find_tmp",
        category="SECRET_LEAKAGE",
        severity=FindingSeverity.LOW,
        title="Dummy finding",
        description="",
        application_model_ref="",
        evidence="",
    )
    patches = [
        RepairPatch(
            file_path="foo.py",
            target_checksum="hash1",
            diff_content="diff1",
            replay_command="cmd1",
        )
    ]
    bundle = repair_engine.create_bundle(finding, patches, "replay.sh")

    with pytest.raises(RepairBundleVerificationError, match="Checksum mismatch"):
        repair_engine.verify_bundle(bundle, expected_checksum="corrupted_checksum_value")
