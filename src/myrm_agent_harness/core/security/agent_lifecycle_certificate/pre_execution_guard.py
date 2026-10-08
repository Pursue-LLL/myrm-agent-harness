import time

from .cert_authority import AgentCertificateAuthority
from .crl_manager import CertificateRevocationManager
from .types import (
    AgentDigitalCertificateSpec,
    CertificateHealthStatusEnum,
    CertificateHealthSummary,
    CertificateStatusEnum,
    PreExecutionVerificationResult,
    RevocationReasonEnum,
    RevocationRecord,
)


class PreExecutionCertificateGuard:
    """Pre-execution guard enforcing cryptographic certificate validity before sandbox invocation."""

    def __init__(
        self,
        ca: AgentCertificateAuthority,
        crl_manager: CertificateRevocationManager,
    ) -> None:
        self._ca = ca
        self._crl_manager = crl_manager

    def verify_preflight(
        self,
        cert: AgentDigitalCertificateSpec,
        current_time: float | None = None,
    ) -> PreExecutionVerificationResult:
        """Perform comprehensive pre-execution checks on an agent digital certificate."""
        now = current_time if current_time is not None else time.time()

        # 1. Check CRL revocation status
        is_revoked = (
            self._crl_manager.is_revoked(cert.serial_number)
            or self._crl_manager.is_cert_id_revoked(cert.cert_id)
            or cert.status == CertificateStatusEnum.REVOKED
        )
        if is_revoked:
            return PreExecutionVerificationResult(
                is_allowed=False,
                status=CertificateStatusEnum.REVOKED,
                message="Certificate is revoked in CRL. Execution blocked immediately.",
                signature_valid=True,
                not_expired=True,
                not_revoked=False,
                issuer_trusted=True,
            )

        # 2. Check trusted issuer DN
        if cert.issuer_dn != self._ca.issuer_dn:
            return PreExecutionVerificationResult(
                is_allowed=False,
                status=CertificateStatusEnum.SUSPENDED,
                message=f"Untrusted certificate issuer: '{cert.issuer_dn}'. Expected: '{self._ca.issuer_dn}'.",
                signature_valid=False,
                not_expired=True,
                not_revoked=True,
                issuer_trusted=False,
            )

        # 3. Check time validity (expiry & not-before)
        if now < cert.not_before:
            return PreExecutionVerificationResult(
                is_allowed=False,
                status=CertificateStatusEnum.SUSPENDED,
                message="Certificate is not yet valid (not_before in future).",
                signature_valid=True,
                not_expired=False,
                not_revoked=True,
                issuer_trusted=True,
            )

        if now > cert.not_after:
            return PreExecutionVerificationResult(
                is_allowed=False,
                status=CertificateStatusEnum.EXPIRED,
                message="Certificate has expired. Renewal required.",
                signature_valid=True,
                not_expired=False,
                not_revoked=True,
                issuer_trusted=True,
            )

        # 4. Check cryptographic signature
        if not self._ca.verify_signature(cert):
            return PreExecutionVerificationResult(
                is_allowed=False,
                status=CertificateStatusEnum.SUSPENDED,
                message="Certificate cryptographic signature is invalid or forged.",
                signature_valid=False,
                not_expired=True,
                not_revoked=True,
                issuer_trusted=True,
            )

        return PreExecutionVerificationResult(
            is_allowed=True,
            status=CertificateStatusEnum.ACTIVE,
            message="Certificate is valid, trusted, and verified.",
            signature_valid=True,
            not_expired=True,
            not_revoked=True,
            issuer_trusted=True,
        )

    def evaluate_health(
        self,
        cert: AgentDigitalCertificateSpec,
        current_time: float | None = None,
    ) -> CertificateHealthSummary:
        """Evaluate diagnostic health and time-to-expiry for a certificate."""
        now = current_time if current_time is not None else time.time()
        is_revoked = (
            self._crl_manager.is_revoked(cert.serial_number)
            or self._crl_manager.is_cert_id_revoked(cert.cert_id)
            or cert.status == CertificateStatusEnum.REVOKED
        )

        days_remaining = max(0.0, (cert.not_after - now) / 86400.0)

        if is_revoked:
            return CertificateHealthSummary(
                cert_id=cert.cert_id,
                agent_id=cert.agent_id,
                health_status=CertificateHealthStatusEnum.REVOKED,
                days_until_expiry=days_remaining,
                is_revoked=True,
                requires_renewal=False,
            )

        if days_remaining <= 0.0:
            return CertificateHealthSummary(
                cert_id=cert.cert_id,
                agent_id=cert.agent_id,
                health_status=CertificateHealthStatusEnum.EXPIRED,
                days_until_expiry=0.0,
                is_revoked=False,
                requires_renewal=True,
            )

        if days_remaining <= 7.0:
            status = CertificateHealthStatusEnum.CRITICAL_EXPIRY
            renewal = True
        elif days_remaining <= 30.0:
            status = CertificateHealthStatusEnum.EXPIRING_SOON
            renewal = True
        else:
            status = CertificateHealthStatusEnum.HEALTHY
            renewal = False

        return CertificateHealthSummary(
            cert_id=cert.cert_id,
            agent_id=cert.agent_id,
            health_status=status,
            days_until_expiry=days_remaining,
            is_revoked=False,
            requires_renewal=renewal,
        )


class AgentLifecycleCertificateSuite:
    """Unified facade for agent digital certificate lifecycle, verification, and revocation."""

    def __init__(
        self,
        issuer_dn: str = AgentCertificateAuthority.DEFAULT_ISSUER_DN,
        ca_signing_secret: str = "MYRM_CA_ROOT_PRIVATE_SIGNING_KEY_2026",
    ) -> None:
        self.ca = AgentCertificateAuthority(
            issuer_dn=issuer_dn,
            ca_signing_secret=ca_signing_secret,
        )
        self.crl_manager = CertificateRevocationManager()
        self.guard = PreExecutionCertificateGuard(self.ca, self.crl_manager)

    def mint_certificate(
        self,
        agent_id: str,
        subject_dn: str,
        validity_days: int = 365,
        attributes: dict[str, str] | None = None,
    ) -> AgentDigitalCertificateSpec:
        """Mint a signed digital certificate."""
        return self.ca.mint_certificate(
            agent_id=agent_id,
            subject_dn=subject_dn,
            validity_days=validity_days,
            attributes=attributes,
        )

    def verify_execution(
        self,
        cert: AgentDigitalCertificateSpec,
        current_time: float | None = None,
    ) -> PreExecutionVerificationResult:
        """Verify certificate before allowing agent to run."""
        return self.guard.verify_preflight(cert, current_time=current_time)

    def emergency_revoke(
        self,
        serial_number: str,
        cert_id: str,
        agent_id: str,
        reason: RevocationReasonEnum,
        revoked_by: str = "security-admin",
    ) -> RevocationRecord:
        """Emergency revoke a certificate and broadcast to CRL."""
        return self.crl_manager.revoke_certificate(
            serial_number=serial_number,
            cert_id=cert_id,
            agent_id=agent_id,
            reason=reason,
            revoked_by=revoked_by,
        )

    def evaluate_health(
        self,
        cert: AgentDigitalCertificateSpec,
        current_time: float | None = None,
    ) -> CertificateHealthSummary:
        """Evaluate certificate health and expiration timeline."""
        return self.guard.evaluate_health(cert, current_time=current_time)
