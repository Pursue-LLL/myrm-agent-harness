"""
[POS] src/myrm_agent_harness/core/security/code_signing_gate/types.py
[INPUT] dataclasses, enum, typing
[OUTPUT] SupplyChainTrustPolicyEnum, PackageVerificationVerdictEnum, DeveloperCertificateInfo, PackageManifestEntry, SignedPackageDescriptor, PackageVerificationResult, CodeSigningGateMetrics

Data structures and specifications for Developer Identity Attestation & Agent Package Code Signing Gate Suite.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SupplyChainTrustPolicyEnum(StrEnum):
    """Enterprise supply chain trust enforcement policies."""

    STRICT_ENTERPRISE_ONLY = "STRICT_ENTERPRISE_ONLY"
    VERIFIED_CA_ONLY = "VERIFIED_CA_ONLY"
    ALLOW_COMMUNITY_WARNING = "ALLOW_COMMUNITY_WARNING"
    DENY_ALL = "DENY_ALL"


class PackageVerificationVerdictEnum(StrEnum):
    """Decision verdict for package code signature and supply chain trust."""

    VERIFIED = "VERIFIED"
    UNSIGNED_COMMUNITY = "UNSIGNED_COMMUNITY"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    EXPIRED_CERTIFICATE = "EXPIRED_CERTIFICATE"
    REVOKED_CERTIFICATE = "REVOKED_CERTIFICATE"
    TAMPERED_MANIFEST_DIGEST = "TAMPERED_MANIFEST_DIGEST"
    POLICY_REJECTED = "POLICY_REJECTED"


@dataclass(frozen=True)
class DeveloperCertificateInfo:
    """Developer real-name certificate attributes and public verification material."""

    developer_id: str
    developer_name: str
    org_dn: str
    issuer_ca: str
    cert_serial: str
    valid_until: float
    public_key_pem: str
    is_internal_enterprise: bool = False


@dataclass(frozen=True)
class PackageManifestEntry:
    """Cryptographic digest entry for an individual file asset within an agent/skill package."""

    file_path: str
    sha256_hash: str
    size_bytes: int


@dataclass(frozen=True)
class SignedPackageDescriptor:
    """Complete package manifest with attached detached digital signature."""

    package_id: str
    package_name: str
    version: str
    manifest_entries: list[PackageManifestEntry]
    canonical_manifest_digest: str
    signature_b64: str
    cert_info: DeveloperCertificateInfo | None = None


@dataclass(frozen=True)
class PackageVerificationResult:
    """Outcome of verifying package code signing and supply chain policy."""

    is_allowed: bool
    verdict: PackageVerificationVerdictEnum
    reason: str
    verified_developer: str | None = None
    cert_serial: str | None = None
    is_enterprise_verified: bool = False


@dataclass
class CodeSigningGateMetrics:
    """Cumulative operational metrics for supply chain code signing gate."""

    total_verifications: int = 0
    verified_count: int = 0
    blocked_untrusted_count: int = 0
    tampered_count: int = 0
    signature_failures: int = 0
