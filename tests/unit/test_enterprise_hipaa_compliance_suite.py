"""
[POS] tests/unit/test_enterprise_hipaa_compliance_suite.py
Unit tests for Enterprise BAA/HIPAA Compliance Conduit Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from myrm_agent_harness.core.security.enterprise_hipaa_compliance import (
    BYOCompliantProvider,
    ComplianceStandard,
    EnterpriseHipaaComplianceFacade,
    HipaaAuditChainEngine,
    ProviderComplianceTier,
)


def test_hipaa_audit_chain_sequential_hashing_and_tamper_detection() -> None:
    engine = HipaaAuditChainEngine()

    # Append 3 sequential events
    e0 = engine.append_event(
        event_type="FILE_READ",
        agent_id="medical-agent",
        session_id="sess-01",
        action_summary="Read patient medical record",
        phi_detected=True,
        timestamp=1000.0,
    )
    assert e0.sequence_index == 0
    assert e0.prev_hash == "0" * 64
    assert len(e0.current_hash) == 64

    e1 = engine.append_event(
        event_type="LLM_INFERENCE",
        agent_id="medical-agent",
        session_id="sess-01",
        action_summary="Executed diagnostic query on Azure OpenAI",
        phi_detected=False,
        timestamp=1001.0,
    )
    assert e1.sequence_index == 1
    assert e1.prev_hash == e0.current_hash

    # Verify integrity
    valid, diag = engine.verify_chain_integrity()
    assert valid is True
    assert "Verified cryptographic integrity" in diag

    # Test export package
    pkg = engine.export_package(standard=ComplianceStandard.HIPAA, current_time=1002.0)
    assert pkg.total_events == 2
    assert pkg.chain_valid is True
    assert len(pkg.summary_digest) == 64


def test_phi_screening_and_egress_guard() -> None:
    facade = EnterpriseHipaaComplianceFacade()

    # Register an unverified public provider
    unverified = BYOCompliantProvider(
        provider_id="unverified-public-ai",
        provider_name="Shadow Public LLM",
        base_url="https://api.shadow-llm.com",
        tier=ProviderComplianceTier.UNVERIFIED_PUBLIC,
        baa_agreement_id=None,
        is_zero_training_mandated=False,
    )
    facade.register_compliant_provider(unverified)

    # Clean message -> allowed even on public
    clean_msg = "Please analyze general medical statistics for influenza in 2025"
    clean_phi = facade.screen_phi_content(clean_msg)
    assert clean_phi.is_clean is True

    allowed_clean, _, _ = facade.validate_provider_egress("unverified-public-ai", clean_msg)
    assert allowed_clean is True

    # Message with PHI (MRN + SSN)
    phi_msg = "Patient Jane Doe, MRN: MRN-998877, SSN: 123-45-6789, requires surgery"
    phi_screen = facade.screen_phi_content(phi_msg)
    assert phi_screen.is_clean is False
    assert "MEDICAL_RECORD_NUMBER_MRN" in phi_screen.detected_phi_categories
    assert "SOCIAL_SECURITY_NUMBER_SSN" in phi_screen.detected_phi_categories
    assert "[REDACTED_MRN]" in phi_screen.sanitized_content
    assert "[REDACTED_SSN]" in phi_screen.sanitized_content

    # Attempt egress of PHI to unverified provider -> strictly BLOCKED
    allowed_unverified, _, unverified_diag = facade.validate_provider_egress("unverified-public-ai", phi_msg)
    assert allowed_unverified is False
    assert "lacks signed BAA agreement" in unverified_diag

    # Egress of PHI to verified BAA Azure endpoint -> ALLOWED with zero-training headers
    allowed_baa, headers, baa_diag = facade.validate_provider_egress(
        "azure-openai-enterprise-eastus", phi_msg
    )
    assert allowed_baa is True
    assert headers["X-Opt-Out-Training"] == "true"
    assert headers["X-Data-Sovereignty"] == "hipaa-strict"
    assert headers["X-BAA-Agreement-ID"] == "BAA-MSFT-CORP-2026-X9"
    assert "authorized" in baa_diag


def test_facade_end_to_end_audit_and_metrics() -> None:
    facade = EnterpriseHipaaComplianceFacade()

    # Record events
    facade.record_audit_event(
        event_type="EHR_INGESTION",
        agent_id="nurse-bot",
        session_id="sess-ehr-10",
        action_summary="Ingested lab results batch",
        phi_detected=True,
    )

    valid, _ = facade.verify_audit_integrity()
    assert valid is True

    export = facade.export_compliance_package(ComplianceStandard.BAA_ENTERPRISE)
    assert export.total_events == 1
    assert export.compliance_standard == ComplianceStandard.BAA_ENTERPRISE

    metrics = facade.metrics
    assert metrics.providers_registered_total >= 2
    assert metrics.audit_events_recorded_total == 1
    assert metrics.compliance_exports_generated_total == 1
