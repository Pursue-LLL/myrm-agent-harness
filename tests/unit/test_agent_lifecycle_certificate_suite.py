import time

from myrm_agent_harness.core.security.agent_lifecycle_certificate import (
    AgentDigitalCertificateSpec,
    AgentLifecycleCertificateSuite,
    CertificateHealthStatusEnum,
    CertificateStatusEnum,
    RevocationReasonEnum,
)


def test_agent_certificate_minting_and_signature_verification() -> None:
    suite = AgentLifecycleCertificateSuite()
    cert = suite.mint_certificate(
        agent_id="agent-finance-001",
        subject_dn="CN=Finance Agent 001, O=Enterprise Dept, C=CN",
        validity_days=30,
        attributes={"clearance": "top-secret"},
    )

    assert cert.agent_id == "agent-finance-001"
    assert cert.status == CertificateStatusEnum.ACTIVE
    assert len(cert.fingerprint_sha256) == 64
    assert len(cert.signature_hex) == 64
    assert cert.serial_number.startswith("SN-")
    assert suite.ca.verify_signature(cert) is True


def test_pre_execution_guard_allows_valid_certificate() -> None:
    suite = AgentLifecycleCertificateSuite()
    cert = suite.mint_certificate(
        agent_id="agent-ops-002",
        subject_dn="CN=DevOps Agent 002, O=Platform, C=CN",
        validity_days=90,
    )

    verdict = suite.verify_execution(cert)
    assert verdict.is_allowed is True
    assert verdict.status == CertificateStatusEnum.ACTIVE
    assert verdict.signature_valid is True
    assert verdict.not_expired is True
    assert verdict.not_revoked is True
    assert verdict.issuer_trusted is True


def test_pre_execution_guard_blocks_revoked_certificate() -> None:
    suite = AgentLifecycleCertificateSuite()
    cert = suite.mint_certificate(
        agent_id="agent-malicious-003",
        subject_dn="CN=Untrusted Agent, O=Unknown, C=CN",
        validity_days=30,
    )

    # Initial check passes
    assert suite.verify_execution(cert).is_allowed is True

    # Emergency revoke
    rec = suite.emergency_revoke(
        serial_number=cert.serial_number,
        cert_id=cert.cert_id,
        agent_id=cert.agent_id,
        reason=RevocationReasonEnum.MALICIOUS_BACKDOOR_DETECTED,
        revoked_by="sec-ops-admin",
    )
    assert rec.serial_number == cert.serial_number
    assert rec.reason == RevocationReasonEnum.MALICIOUS_BACKDOOR_DETECTED

    # Subsequent preflight blocked immediately
    verdict = suite.verify_execution(cert)
    assert verdict.is_allowed is False
    assert verdict.status == CertificateStatusEnum.REVOKED
    assert verdict.not_revoked is False


def test_pre_execution_guard_blocks_expired_certificate() -> None:
    suite = AgentLifecycleCertificateSuite()
    cert = suite.mint_certificate(
        agent_id="agent-expiring-004",
        subject_dn="CN=Expiring Agent, O=Platform, C=CN",
        validity_days=10,
    )

    # Check at 20 days in future
    simulated_future_time = time.time() + (20 * 86400)
    verdict = suite.verify_execution(cert, current_time=simulated_future_time)
    assert verdict.is_allowed is False
    assert verdict.status == CertificateStatusEnum.EXPIRED
    assert verdict.not_expired is False


def test_pre_execution_guard_blocks_tampered_signature() -> None:
    suite = AgentLifecycleCertificateSuite()
    original_cert = suite.mint_certificate(
        agent_id="agent-legit-005",
        subject_dn="CN=Legit Agent, O=Platform, C=CN",
    )

    # Tamper the subject DN without re-signing
    tampered_cert = AgentDigitalCertificateSpec(
        cert_id=original_cert.cert_id,
        agent_id=original_cert.agent_id,
        issuer_dn=original_cert.issuer_dn,
        subject_dn="CN=Hacked Agent, O=Malicious, C=CN",
        serial_number=original_cert.serial_number,
        fingerprint_sha256=original_cert.fingerprint_sha256,
        not_before=original_cert.not_before,
        not_after=original_cert.not_after,
        status=original_cert.status,
        signature_hex=original_cert.signature_hex,
        public_key_pem=original_cert.public_key_pem,
        attributes=original_cert.attributes,
    )

    verdict = suite.verify_execution(tampered_cert)
    assert verdict.is_allowed is False
    assert verdict.signature_valid is False


def test_certificate_health_evaluation_and_expiry_warning() -> None:
    suite = AgentLifecycleCertificateSuite()
    cert = suite.mint_certificate(
        agent_id="agent-lifecycle-006",
        subject_dn="CN=Lifecycle Agent, O=Platform, C=CN",
        validity_days=60,
    )

    now = time.time()

    # Day 0: HEALTHY (>30 days remaining)
    health_0 = suite.evaluate_health(cert, current_time=now)
    assert health_0.health_status == CertificateHealthStatusEnum.HEALTHY
    assert health_0.requires_renewal is False

    # Day 40: EXPIRING_SOON (20 days remaining)
    health_40 = suite.evaluate_health(cert, current_time=now + (40 * 86400))
    assert health_40.health_status == CertificateHealthStatusEnum.EXPIRING_SOON
    assert health_40.requires_renewal is True

    # Day 55: CRITICAL_EXPIRY (5 days remaining)
    health_55 = suite.evaluate_health(cert, current_time=now + (55 * 86400))
    assert health_55.health_status == CertificateHealthStatusEnum.CRITICAL_EXPIRY
    assert health_55.requires_renewal is True

    # Day 65: EXPIRED
    health_65 = suite.evaluate_health(cert, current_time=now + (65 * 86400))
    assert health_65.health_status == CertificateHealthStatusEnum.EXPIRED
    assert health_65.requires_renewal is True

    # Revoked certificate health
    suite.emergency_revoke(
        serial_number=cert.serial_number,
        cert_id=cert.cert_id,
        agent_id=cert.agent_id,
        reason=RevocationReasonEnum.ADMIN_EMERGENCY_SHUTDOWN,
    )
    health_revoked = suite.evaluate_health(cert, current_time=now)
    assert health_revoked.health_status == CertificateHealthStatusEnum.REVOKED
    assert health_revoked.is_revoked is True
