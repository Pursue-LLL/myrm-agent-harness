"""
[POS] src/myrm_agent_harness/core/security/code_signing_gate/facade.py
[INPUT] threading, time, typing, .types, .manifest_hasher, .signature_verifier, .trust_policy_engine
[OUTPUT] CodeSigningGateSuite

Unified facade for Developer Identity Attestation & Agent Package Code Signing Gate Suite.
Coordinates manifest hashing, Ed25519 asymmetric signature verification, developer certificate
lifespan checks, and enterprise supply chain policy enforcement.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import threading
import time

from .manifest_hasher import PackageManifestHasher
from .signature_verifier import CodeSignatureVerifier
from .trust_policy_engine import SupplyChainTrustPolicyEngine
from .types import (
    CodeSigningGateMetrics,
    DeveloperCertificateInfo,
    PackageVerificationResult,
    PackageVerificationVerdictEnum,
    SignedPackageDescriptor,
    SupplyChainTrustPolicyEnum,
)


class CodeSigningGateSuite:
    """Thread-safe facade coordinating code signing, payload integrity, and supply chain policy."""

    def __init__(
        self,
        default_policy: SupplyChainTrustPolicyEnum = SupplyChainTrustPolicyEnum.VERIFIED_CA_ONLY,
    ) -> None:
        self._lock = threading.Lock()
        self.manifest_hasher = PackageManifestHasher()
        self.signature_verifier = CodeSignatureVerifier()
        self.policy_engine = SupplyChainTrustPolicyEngine(default_policy=default_policy)
        self._metrics = CodeSigningGateMetrics()

    def sign_package(
        self,
        package_id: str,
        package_name: str,
        version: str,
        files: dict[str, str | bytes],
        private_key_pem: str,
        cert_info: DeveloperCertificateInfo | None = None,
    ) -> SignedPackageDescriptor:
        """Create a cryptographic manifest and generate an Ed25519 detached signature."""
        manifest_entries, canonical_digest = self.manifest_hasher.build_manifest(files)
        signature_b64 = self.signature_verifier.sign_digest(private_key_pem, canonical_digest)

        return SignedPackageDescriptor(
            package_id=package_id,
            package_name=package_name,
            version=version,
            manifest_entries=manifest_entries,
            canonical_manifest_digest=canonical_digest,
            signature_b64=signature_b64,
            cert_info=cert_info,
        )

    def verify_package(
        self,
        package: SignedPackageDescriptor,
        actual_files: dict[str, str | bytes] | None = None,
        current_time: float | None = None,
    ) -> PackageVerificationResult:
        """Verify package code signature, asset digest integrity, and supply chain trust policy."""
        now = current_time if current_time is not None else time.time()

        with self._lock:
            self._metrics.total_verifications += 1

        # 1. Verify physical file assets against manifest (if provided)
        if actual_files is not None:
            is_match, discrepancies = self.manifest_hasher.verify_files_against_manifest(
                actual_files, package.manifest_entries
            )
            if not is_match:
                with self._lock:
                    self._metrics.tampered_count += 1
                return PackageVerificationResult(
                    is_allowed=False,
                    verdict=PackageVerificationVerdictEnum.TAMPERED_MANIFEST_DIGEST,
                    reason=f"Payload tampering detected: {'; '.join(discrepancies)}",
                )

        # 2. Verify canonical manifest digest consistency
        expected_digest = self.manifest_hasher.compute_canonical_digest(package.manifest_entries)
        if expected_digest != package.canonical_manifest_digest:
            with self._lock:
                self._metrics.tampered_count += 1
            return PackageVerificationResult(
                is_allowed=False,
                verdict=PackageVerificationVerdictEnum.TAMPERED_MANIFEST_DIGEST,
                reason="Manifest entries do not match declared canonical digest.",
            )

        # 3. Handle unsigned packages
        if package.cert_info is None:
            is_allowed, verdict, reason = self.policy_engine.evaluate_trust(None)
            if not is_allowed:
                with self._lock:
                    self._metrics.blocked_untrusted_count += 1
            return PackageVerificationResult(
                is_allowed=is_allowed,
                verdict=verdict,
                reason=reason,
            )

        cert_info = package.cert_info

        # 4. Check certificate validity period
        is_cert_valid, cert_msg = self.signature_verifier.is_certificate_valid(cert_info, now)
        if not is_cert_valid:
            with self._lock:
                self._metrics.blocked_untrusted_count += 1
            return PackageVerificationResult(
                is_allowed=False,
                verdict=PackageVerificationVerdictEnum.EXPIRED_CERTIFICATE,
                reason=cert_msg,
                verified_developer=cert_info.developer_name,
                cert_serial=cert_info.cert_serial,
            )

        # 5. Verify cryptographic signature
        is_sig_valid = self.signature_verifier.verify_signature(
            public_key_pem=cert_info.public_key_pem,
            canonical_digest=package.canonical_manifest_digest,
            signature_b64=package.signature_b64,
        )
        if not is_sig_valid:
            with self._lock:
                self._metrics.signature_failures += 1
            return PackageVerificationResult(
                is_allowed=False,
                verdict=PackageVerificationVerdictEnum.INVALID_SIGNATURE,
                reason="Cryptographic Ed25519 signature verification failed.",
                verified_developer=cert_info.developer_name,
                cert_serial=cert_info.cert_serial,
            )

        # 6. Evaluate organizational trust policy
        is_trusted, policy_verdict, policy_reason = self.policy_engine.evaluate_trust(cert_info)
        if not is_trusted:
            with self._lock:
                self._metrics.blocked_untrusted_count += 1
            return PackageVerificationResult(
                is_allowed=False,
                verdict=policy_verdict,
                reason=policy_reason,
                verified_developer=cert_info.developer_name,
                cert_serial=cert_info.cert_serial,
                is_enterprise_verified=cert_info.is_internal_enterprise,
            )

        # Signature and policy both pass
        with self._lock:
            self._metrics.verified_count += 1

        return PackageVerificationResult(
            is_allowed=True,
            verdict=PackageVerificationVerdictEnum.VERIFIED,
            reason=policy_reason,
            verified_developer=cert_info.developer_name,
            cert_serial=cert_info.cert_serial,
            is_enterprise_verified=cert_info.is_internal_enterprise,
        )

    def get_policy(self) -> SupplyChainTrustPolicyEnum:
        """Get active enterprise trust policy."""
        return self.policy_engine.get_policy()

    def set_policy(self, policy: SupplyChainTrustPolicyEnum) -> None:
        """Update enterprise trust policy."""
        self.policy_engine.set_policy(policy)

    def add_trusted_ca(self, ca_name: str) -> None:
        """Add authorized CA to trust store."""
        self.policy_engine.add_trusted_ca(ca_name)

    def revoke_certificate(self, cert_serial: str) -> None:
        """Revoke a developer certificate serial."""
        self.policy_engine.revoke_certificate(cert_serial)

    def get_metrics(self) -> CodeSigningGateMetrics:
        """Retrieve telemetry counters for code signing gate."""
        with self._lock:
            return CodeSigningGateMetrics(
                total_verifications=self._metrics.total_verifications,
                verified_count=self._metrics.verified_count,
                blocked_untrusted_count=self._metrics.blocked_untrusted_count,
                tampered_count=self._metrics.tampered_count,
                signature_failures=self._metrics.signature_failures,
            )
