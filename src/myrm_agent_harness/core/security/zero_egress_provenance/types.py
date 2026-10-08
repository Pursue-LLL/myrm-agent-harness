"""Domain types and models for Enterprise Zero-Egress Audit Ledger & Asset Provenance.

[INPUT]
- None.

[OUTPUT]
- Typed dataclasses and enums representing tamper-evident audit records,
  zero-egress attestation certificates, and generative asset provenance dossiers.

[POS]
- Harness core security domain models ensuring enterprise compliance (HIPAA, SOC2)
  and intellectual property indemnification for AI-generated code and assets.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class AttestationLevel(StrEnum):
    """Compliance tier of the zero-egress commitment."""

    STANDARD = "STANDARD"
    ENTERPRISE_ZERO_EGRESS = "ENTERPRISE_ZERO_EGRESS"
    HIPAA_SOC2_CERTIFIED = "HIPAA_SOC2_CERTIFIED"


class EgressBoundaryState(StrEnum):
    """Network confinement status of an operation."""

    SANDBOX_CONFINED = "SANDBOX_CONFINED"
    APPROVED_EGRESS_TUNNEL = "APPROVED_EGRESS_TUNNEL"
    DISALLOWED_VIOLATION = "DISALLOWED_VIOLATION"


class IPCleanlinessTier(StrEnum):
    """Intellectual property cleanliness and indemnification tier."""

    ENTERPRISE_INDEMNIFIED = "ENTERPRISE_INDEMNIFIED"
    PROVENANCE_VERIFIED = "PROVENANCE_VERIFIED"
    UNVERIFIED_COMMUNITY = "UNVERIFIED_COMMUNITY"


@dataclass(frozen=True)
class ZeroEgressAttestationCertificate:
    """Cryptographically signed compliance attestation guaranteeing zero private data leakage."""

    certificate_id: str
    session_id: str
    tenant_id: str
    sandbox_id: str
    attestation_level: AttestationLevel
    zero_data_retention_guaranteed: bool
    no_model_training_guaranteed: bool
    environment_digest_sha256: str
    signature: str
    issued_at_iso: str
    issuer: str = "Myrm-Enterprise-Security-Authority"


@dataclass(frozen=True)
class AuditLedgerRecord:
    """Tamper-evident chained audit log entry for cross-system actions."""

    record_id: str
    sequence_number: int
    timestamp_utc: str
    actor: str
    action_type: str
    resource_target: str
    input_sha256: str
    output_sha256: str
    boundary_state: EgressBoundaryState
    previous_record_hash: str
    current_record_hash: str
    compliance_standard: str = "HIPAA_SOC2_COMPLIANT"


@dataclass(frozen=True)
class AssetProvenanceDossier:
    """Intellectual property provenance record for an AI-generated code or media asset."""

    dossier_id: str
    asset_id: str
    asset_name: str
    media_type: str
    content_sha256: str
    session_id: str
    origin_prompt_sha256: str
    foundation_model_id: str
    ip_tier: IPCleanlinessTier
    license_type: str
    digital_signature: str
    created_at_iso: str
    metadata: tuple[tuple[str, str], ...] = field(default_factory=tuple)


class AuditLedgerTamperError(Exception):
    """Raised when chained hash verification reveals audit ledger corruption or tampering."""


class ProvenanceVerificationError(Exception):
    """Raised when an asset content digest does not match its declared provenance dossier."""
