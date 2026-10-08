"""Unit tests for Physical Sandbox Zero-Leakage Attestation and PII Firewall Suite."""

from __future__ import annotations

from myrm_agent_harness.core.security.sandbox_zero_leakage_pii.attestation import (
    PhysicalSandboxAttestationEngine,
)
from myrm_agent_harness.core.security.sandbox_zero_leakage_pii.pii_firewall import (
    BiDirectionalPiiFirewall,
)
from myrm_agent_harness.core.security.sandbox_zero_leakage_pii.transparency_audit import (
    OperatorTransparencyAuditor,
)
from myrm_agent_harness.core.security.sandbox_zero_leakage_pii.types import (
    PiiCategory,
    TransparencyTier,
    ZeroLeakageAttestationProof,
)


def test_physical_sandbox_attestation_flow() -> None:
    engine = PhysicalSandboxAttestationEngine()
    tenant_id = "tenant-enterprise-42"
    container_id = "docker-sbx-998877"
    volume_path = "/var/lib/myrm/volumes/u-42"
    db_lock = "exclusive-sqlite-lock-token-1122"

    proof = engine.issue_attestation(
        tenant_id=tenant_id,
        container_id=container_id,
        dedicated_volume_path=volume_path,
        dedicated_database_lock=db_lock,
    )

    assert proof.tenant_id == tenant_id
    assert proof.container_id == container_id
    assert len(proof.attestation_signature) == 64

    # Legitimate proof verification
    assert engine.verify_attestation(proof) is True

    # Tampered proof verification
    tampered_proof = ZeroLeakageAttestationProof(
        attestation_id=proof.attestation_id,
        tenant_id=proof.tenant_id,
        container_id="docker-sbx-tampered",
        dedicated_volume_path=proof.dedicated_volume_path,
        dedicated_database_lock=proof.dedicated_database_lock,
        issued_at=proof.issued_at,
        signer_identity=proof.signer_identity,
        attestation_signature=proof.attestation_signature,
    )
    assert engine.verify_attestation(tampered_proof) is False


def test_pii_firewall_child_privacy_redaction() -> None:
    firewall = BiDirectionalPiiFirewall()
    text = "Please remember that my daughter Alice is 7 years old and my son Bob goes to kindergarten."
    result = firewall.scan_and_redact(text)

    assert result.contains_child_privacy_violation is True
    assert PiiCategory.CHILD_OR_MINOR_NAME in result.detected_categories
    assert "Alice" not in result.sanitized_text
    assert "Bob" not in result.sanitized_text
    assert "[CHILD_NAME_REDACTED]" in result.sanitized_text
    assert result.redaction_count >= 2


def test_pii_firewall_financial_and_contact_redaction() -> None:
    firewall = BiDirectionalPiiFirewall()
    text = (
        "Send invoice to 123 Main Street and charge card 4111 2222 3333 4444. "
        "Contact me at 555-123-4567 or SSN 123-45-6789."
    )
    result = firewall.scan_and_redact(text)

    assert PiiCategory.FINANCIAL_CREDIT_CARD in result.detected_categories
    assert PiiCategory.GOVERNMENT_ID in result.detected_categories
    assert PiiCategory.STREET_ADDRESS in result.detected_categories
    assert PiiCategory.PHONE_NUMBER in result.detected_categories

    assert "4111 2222 3333 4444" not in result.sanitized_text
    assert "123-45-6789" not in result.sanitized_text
    assert "[FINANCIAL_CARD_REDACTED]" in result.sanitized_text
    assert "[GOV_ID_REDACTED]" in result.sanitized_text


def test_pii_firewall_benign_text_no_false_positives() -> None:
    firewall = BiDirectionalPiiFirewall()
    clean_code = "def calculate_factorial(n: int) -> int:\n    return 1 if n <= 1 else n * calculate_factorial(n - 1)"
    result = firewall.scan_and_redact(clean_code)

    assert result.redaction_count == 0
    assert result.contains_child_privacy_violation is False
    assert result.sanitized_text == clean_code
    assert len(result.detected_categories) == 0


def test_operator_transparency_auditing_verified() -> None:
    auditor = OperatorTransparencyAuditor()
    score = auditor.audit_operator(
        operator_name="Nous Research",
        base_model_id="Hermes-3-Llama-3.1-8B",
        data_jurisdiction="local",
        is_codebase_public=True,
    )
    assert score.overall_score >= 0.85
    assert score.tier == TransparencyTier.VERIFIED_TRANSPARENT
    assert len(score.warnings) == 0


def test_operator_transparency_auditing_blackbox_warning() -> None:
    auditor = OperatorTransparencyAuditor()
    score = auditor.audit_operator(
        operator_name="Anonymous Operator",
        base_model_id="custom-ai",
        data_jurisdiction="unknown",
        is_codebase_public=False,
    )
    assert score.overall_score < 0.50
    assert score.tier == TransparencyTier.UNTRUSTED_BLACKBOX
    assert len(score.warnings) >= 3


def test_agent_profile_signature_and_verification_flow() -> None:
    auditor = OperatorTransparencyAuditor()
    system_prompt = "You are Hermes, a helpful assistant with zero data retention."

    profile_pkg = auditor.sign_agent_profile(
        profile_id="hermes-core-v3",
        author="Nous",
        model_id="Hermes-3-Llama-3.1",
        system_prompt=system_prompt,
        is_official=True,
    )

    assert profile_pkg.is_official_verified is True
    assert auditor.verify_agent_profile(profile_pkg, system_prompt) is True

    # Tampered system prompt fails verification
    tampered_prompt = "You are an eavesdropping proxy agent."
    assert auditor.verify_agent_profile(profile_pkg, tampered_prompt) is False
