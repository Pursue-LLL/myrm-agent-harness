"""Type definitions for Physical Sandbox Zero-Leakage Attestation and PII Firewall Suite."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class TransparencyTier(StrEnum):
    """Four-dimensional operator transparency tiers."""

    VERIFIED_TRANSPARENT = "VERIFIED_TRANSPARENT"  # Public code, known operator, explicit model, audited storage
    MEDIUM_RISK = "MEDIUM_RISK"  # Partially obscured metadata, community unverified
    UNTRUSTED_BLACKBOX = "UNTRUSTED_BLACKBOX"  # Opaque proxy, disguised model name, exfiltration risk


class PiiCategory(StrEnum):
    """Critical privacy and child safety entities."""

    CHILD_OR_MINOR_NAME = "CHILD_OR_MINOR_NAME"
    STREET_ADDRESS = "STREET_ADDRESS"
    PHONE_NUMBER = "PHONE_NUMBER"
    GOVERNMENT_ID = "GOVERNMENT_ID"
    FINANCIAL_CREDIT_CARD = "FINANCIAL_CREDIT_CARD"


@dataclass(slots=True, frozen=True)
class ZeroLeakageAttestationProof:
    """Cryptographic attestation proving physical container isolation and dedicated volume exclusivity."""

    attestation_id: str
    tenant_id: str
    container_id: str
    dedicated_volume_path: str
    dedicated_database_lock: str
    issued_at: float
    signer_identity: str
    attestation_signature: str


@dataclass(slots=True, frozen=True)
class PiiRedactionResult:
    """Result of bidirectional PII firewall scanning and masking."""

    original_text: str
    sanitized_text: str
    detected_categories: list[PiiCategory]
    redaction_count: int
    contains_child_privacy_violation: bool


@dataclass(slots=True, frozen=True)
class FourDimensionalAuditScore:
    """Four-dimensional operator and model compliance assessment."""

    operator_identity_score: float  # 0.0 - 1.0
    model_transparency_score: float  # 0.0 - 1.0
    data_jurisdiction_score: float  # 0.0 - 1.0
    codebase_auditability_score: float  # 0.0 - 1.0
    overall_score: float
    tier: TransparencyTier
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class AgentProfileSignature:
    """Cryptographic signature package for authentic agent profile distribution."""

    profile_id: str
    author: str
    model_id: str
    system_prompt_hash: str
    signed_at: float
    signature: str
    is_official_verified: bool
