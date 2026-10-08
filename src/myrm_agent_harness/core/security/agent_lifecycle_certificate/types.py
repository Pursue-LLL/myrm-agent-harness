from dataclasses import dataclass, field
from enum import StrEnum


class CertificateStatusEnum(StrEnum):
    """Lifecycle status of an agent digital certificate."""

    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUSPENDED = "SUSPENDED"


class RevocationReasonEnum(StrEnum):
    """Standard RFC 5280 compliant certificate revocation reasons."""

    KEY_COMPROMISE = "KEY_COMPROMISE"
    CA_COMPROMISE = "CA_COMPROMISE"
    AFFILIATION_CHANGED = "AFFILIATION_CHANGED"
    SUPERSEDED = "SUPERSEDED"
    CESSATION_OF_OPERATION = "CESSATION_OF_OPERATION"
    MALICIOUS_BACKDOOR_DETECTED = "MALICIOUS_BACKDOOR_DETECTED"
    ADMIN_EMERGENCY_SHUTDOWN = "ADMIN_EMERGENCY_SHUTDOWN"


class CertificateHealthStatusEnum(StrEnum):
    """Health classification based on expiry and revocation status."""

    HEALTHY = "HEALTHY"
    EXPIRING_SOON = "EXPIRING_SOON"  # <= 30 days
    CRITICAL_EXPIRY = "CRITICAL_EXPIRY"  # <= 7 days
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


@dataclass(frozen=True)
class AgentDigitalCertificateSpec:
    """Cryptographic X.509/SM2-style digital certificate issued for an AI Agent."""

    cert_id: str
    agent_id: str
    issuer_dn: str
    subject_dn: str
    serial_number: str
    fingerprint_sha256: str
    not_before: float
    not_after: float
    status: CertificateStatusEnum
    signature_hex: str
    public_key_pem: str
    attributes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RevocationRecord:
    """Record of an emergency certificate revocation in CRL."""

    serial_number: str
    cert_id: str
    agent_id: str
    revocation_timestamp: float
    reason: RevocationReasonEnum
    revoked_by: str


@dataclass(frozen=True)
class PreExecutionVerificationResult:
    """Forensic verification result produced before granting agent execution."""

    is_allowed: bool
    status: CertificateStatusEnum
    message: str
    signature_valid: bool
    not_expired: bool
    not_revoked: bool
    issuer_trusted: bool


@dataclass(frozen=True)
class CertificateHealthSummary:
    """Diagnostic health summary for a digital certificate."""

    cert_id: str
    agent_id: str
    health_status: CertificateHealthStatusEnum
    days_until_expiry: float
    is_revoked: bool
    requires_renewal: bool
