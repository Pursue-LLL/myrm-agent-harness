"""Unit tests for ChangeGuard review decision lanes and evidence hardening suite (WS1-WS5)."""

from __future__ import annotations

from myrm_agent_harness.core.security.change_guard import (
    CanonicalOutcome,
    ChangeClass,
    ChangeGuard,
    ChangeGuardException,
    ChangeGuardPolicyConfig,
    DecisionLane,
    EvidenceType,
    Gateability,
    HardenedFinding,
    ProvenanceClass,
    build_hardened_finding,
)


def test_clean_evaluation_passes() -> None:
    guard = ChangeGuard()
    result = guard.evaluate_changes(findings=())

    assert result.overall_outcome == CanonicalOutcome.PASS
    assert result.lane_a.outcome == CanonicalOutcome.PASS
    assert result.lane_b.outcome == CanonicalOutcome.PASS
    assert result.lane_a.lane == DecisionLane.LANE_A
    assert result.lane_b.lane == DecisionLane.LANE_B
    assert len(result.lane_a.findings) == 0
    assert len(result.lane_b.findings) == 0
    assert result.highest_change_class == ChangeClass.NO_CHANGE


def test_ws1_lane_a_vs_lane_b_separation() -> None:
    guard = ChangeGuard()
    finding_a: HardenedFinding = build_hardened_finding(
        finding_id="FIND-001",
        rule_id="ENV_SECRET_EXPOSURE",
        category="security",
        target_object="settings.yaml",
        message="Plaintext secret detected in config",
        change_class=ChangeClass.HIGH_RISK_CHANGE,
        provenance_class=ProvenanceClass.DETECTED,
        gateability=Gateability.DETERMINISTIC,
        evidence_type=EvidenceType.STATIC_CONFIG,
    )
    finding_b: HardenedFinding = build_hardened_finding(
        finding_id="FIND-002",
        rule_id="GOV_AGENT_AUTONOMY",
        category="governance",
        target_object="agent.yaml",
        message="Unattended subagent delegation enabled",
        change_class=ChangeClass.LOW_CHANGE,
        provenance_class=ProvenanceClass.DECLARED,
        gateability=Gateability.REVIEW_ONLY,
        evidence_type=EvidenceType.STATIC_CONFIG,
    )

    result = guard.evaluate_changes(findings=(finding_a, finding_b))

    # Blocking Lane A gate verdict takes precedence over Lane B review
    assert result.overall_outcome == CanonicalOutcome.BLOCK
    assert result.lane_a.outcome == CanonicalOutcome.BLOCK
    assert len(result.lane_a.findings) == 1
    assert result.lane_a.findings[0].finding_id == "FIND-001"

    # Lane B review question is isolated and not blended with Lane A gates
    assert result.lane_b.outcome == CanonicalOutcome.REVIEW_REQUIRED
    assert len(result.lane_b.findings) == 1
    assert result.lane_b.findings[0].finding_id == "FIND-002"
    assert len(result.lane_b.unresolved_questions) == 1


def test_ws1_review_floor_enforcement() -> None:
    config = ChangeGuardPolicyConfig(enforce_definition_review_floor=True)
    guard = ChangeGuard(config=config)
    finding: HardenedFinding = build_hardened_finding(
        finding_id="FIND-003",
        rule_id="PROMPT_SYSTEM_DIRECTIVE_MODIFIED",
        category="prompt",
        target_object="agent/prompt.py",
        message="System prompt instructions altered",
        change_class=ChangeClass.LOW_CHANGE,
        provenance_class=ProvenanceClass.DETECTED,
        gateability=Gateability.REVIEW_ONLY,
        evidence_type=EvidenceType.DIFF_INSPECTION,
    )

    result = guard.evaluate_changes(findings=(finding,))

    # Review floor forces definition change into review-required
    assert result.overall_outcome == CanonicalOutcome.REVIEW_REQUIRED
    assert result.lane_b.outcome == CanonicalOutcome.REVIEW_REQUIRED
    assert any("Review floor" in q or "PROMPT_" in q for q in result.lane_b.unresolved_questions)


def test_ws2_material_change_authority_gate() -> None:
    config = ChangeGuardPolicyConfig(fail_on_authority_change=ChangeClass.MATERIAL_CHANGE)
    guard = ChangeGuard(config=config)

    # Inferred finding should NOT trip the deterministic gate
    inferred_finding = build_hardened_finding(
        finding_id="FIND-004",
        rule_id="DEP_EXTERNAL_API",
        category="dependencies",
        target_object="client.py",
        message="Inferred outbound API call",
        change_class=ChangeClass.MATERIAL_CHANGE,
        provenance_class=ProvenanceClass.INFERRED,
        gateability=Gateability.DETERMINISTIC,
        evidence_type=EvidenceType.STATIC_PATTERN,
    )
    res_inferred = guard.evaluate_changes(findings=(inferred_finding,))
    assert res_inferred.lane_a.outcome == CanonicalOutcome.PASS
    assert res_inferred.lane_b.outcome == CanonicalOutcome.REVIEW_REQUIRED

    # Detected material change DOES trip the deterministic authority gate
    detected_finding = build_hardened_finding(
        finding_id="FIND-005",
        rule_id="TOOL_SUBPROCESS_ADDITION",
        category="capabilities",
        target_object="executor.py",
        message="Subprocess execution capability added",
        change_class=ChangeClass.MATERIAL_CHANGE,
        provenance_class=ProvenanceClass.DETECTED,
        gateability=Gateability.DETERMINISTIC,
        evidence_type=EvidenceType.DIFF_INSPECTION,
    )
    res_detected = guard.evaluate_changes(findings=(detected_finding,))
    assert res_detected.overall_outcome == CanonicalOutcome.BLOCK
    assert res_detected.lane_a.outcome == CanonicalOutcome.BLOCK


def test_ws4_file_backed_exceptions_and_expiration() -> None:
    guard = ChangeGuard()
    finding: HardenedFinding = build_hardened_finding(
        finding_id="FIND-006",
        rule_id="ENV_SECRET_EXPOSURE",
        category="security",
        target_object="workspace/dev.env",
        message="Local dev dummy key",
        change_class=ChangeClass.HIGH_RISK_CHANGE,
        provenance_class=ProvenanceClass.DETECTED,
        gateability=Gateability.DETERMINISTIC,
        evidence_type=EvidenceType.STATIC_CONFIG,
    )

    exception = ChangeGuardException(
        exception_id="EXC-2026-001",
        finding_or_rule_id="ENV_SECRET_EXPOSURE",
        scope="workspace/dev.env",
        risk_owner="alice@company.com",
        rationale="Dev sandbox environment only",
        compensating_controls="Network isolation active",
        expires_at="2026-12-31T23:59:59Z",
    )
    guard.add_exception(exception)

    # Active exception suppresses the finding
    res_active = guard.evaluate_changes(
        findings=(finding,),
        current_time_iso="2026-06-01T00:00:00Z",
    )
    assert res_active.overall_outcome == CanonicalOutcome.PASS
    assert "EXC-2026-001" in res_active.applied_exceptions

    # Expired exception cannot suppress the finding
    res_expired = guard.evaluate_changes(
        findings=(finding,),
        current_time_iso="2027-01-01T00:00:00Z",
    )
    assert res_expired.overall_outcome == CanonicalOutcome.BLOCK
    assert "EXC-2026-001" in res_expired.stale_or_expired_exceptions
