"""
[POS] src/myrm_agent_harness/core/security/code_signing_gate/__init__.py
[INPUT] .types, .manifest_hasher, .signature_verifier, .trust_policy_engine, .facade
[OUTPUT] DeveloperIdentityAttestationAndAgentPackageCodeSigningGateSuite exports

Developer Identity Attestation & Agent Package Code Signing Gate Suite package exports.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

from .facade import CodeSigningGateSuite
from .manifest_hasher import PackageManifestHasher
from .signature_verifier import CodeSignatureVerifier
from .trust_policy_engine import SupplyChainTrustPolicyEngine
from .types import (
    CodeSigningGateMetrics,
    DeveloperCertificateInfo,
    PackageManifestEntry,
    PackageVerificationResult,
    PackageVerificationVerdictEnum,
    SignedPackageDescriptor,
    SupplyChainTrustPolicyEnum,
)

__all__ = [
    "CodeSignatureVerifier",
    "CodeSigningGateMetrics",
    "CodeSigningGateSuite",
    "DeveloperCertificateInfo",
    "PackageManifestEntry",
    "PackageVerificationResult",
    "PackageVerificationVerdictEnum",
    "PackageManifestHasher",
    "SignedPackageDescriptor",
    "SupplyChainTrustPolicyEngine",
    "SupplyChainTrustPolicyEnum",
]
