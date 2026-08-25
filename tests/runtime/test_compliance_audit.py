"""Tests for compliance audit engine."""

from myrm_agent_harness.core.security.tool_registry.registry import (
    MCPAnnotations,
    SafetyMetadata,
    evict_skill_safety_metadata,
    register_ptc_safety_metadata,
)
from myrm_agent_harness.runtime.compliance import (
    ComplianceAuditEngine,
    ComplianceStatus,
)


def test_compliance_audit_engine_clean():
    # Initial state clean
    report = ComplianceAuditEngine.evaluate_full_compliance()
    assert report.status == ComplianceStatus.COMPLIANT
    assert report.compliance_score == 100
    assert report.is_fully_compliant is True
    assert len(report.violations) == 0

    d = report.to_dict()
    assert d["status"] == "compliant"
    assert d["compliance_score"] == 100


def test_compliance_audit_detects_unregistered_ghost_skill():
    skill_name = "ghost_plugin_alpha"
    tool_name = "ghost_tool"
    register_ptc_safety_metadata(
        skill_name, tool_name, SafetyMetadata(), MCPAnnotations()
    )

    try:
        # Active list does not include ghost_plugin_alpha
        report = ComplianceAuditEngine.evaluate_full_compliance(
            active_skill_names=[skill_name]
        )
        assert report.is_fully_compliant is True

        eviction_needed_report = ComplianceAuditEngine.evaluate_full_compliance(
            active_skill_names=["authorized_plugin_beta"]
        )
        assert eviction_needed_report.status in (
            ComplianceStatus.WARNING,
            ComplianceStatus.NON_COMPLIANT,
        )
        assert eviction_needed_report.compliance_score < 100
        assert eviction_needed_report.is_fully_compliant is False
        assert any(
            "ghost_plugin_alpha" in v.target
            for v in eviction_needed_report.violations
        )
        assert eviction_needed_report.questions["Q2_REGISTRY_CLEAN"] is False
    finally:
        evict_skill_safety_metadata(skill_name)

    # After eviction, clean again
    clean_report = ComplianceAuditEngine.evaluate_full_compliance()
    assert clean_report.is_fully_compliant is True


def test_compliance_audit_custom_business_checks():
    custom_checks = [
        ("Q3_CRON_CLEAN", False, "orphan_cron_job_123", "Found orphan cron job for removed plugin"),
    ]
    report = ComplianceAuditEngine.evaluate_full_compliance(custom_checks=custom_checks)
    assert report.status == ComplianceStatus.WARNING
    assert report.questions["Q3_CRON_CLEAN"] is False
    assert len(report.violations) == 1
    assert report.violations[0].question_id == "Q3_CRON_CLEAN"
