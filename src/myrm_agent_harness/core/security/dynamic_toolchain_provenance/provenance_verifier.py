"""
[POS] src/myrm_agent_harness/core/security/dynamic_toolchain_provenance/provenance_verifier.py
[INPUT] hashlib, hmac, logging, typing, .types
[OUTPUT] ProvenanceVerificationGate

Cryptographic supply chain provenance gate for dynamic toolchain packages.
Validates SHA-256 package hashes and publisher signatures before sandbox installation.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from .types import ProvenanceStatus, SkillProvenanceManifest

logger = logging.getLogger(__name__)


class ProvenanceVerificationGate:
    """Gatekeeper verifying package digests and publisher signatures against trusted registries."""

    DEFAULT_TRUSTED_PUBLISHERS: tuple[str, ...] = (
        "myrm-official",
        "verified-community",
        "enterprise-partner",
    )

    def __init__(
        self,
        trusted_publishers: tuple[str, ...] | list[str] | set[str] | None = None,
        signing_secret_salt: str = "myrm-provenance-anchor-salt",
    ) -> None:
        if trusted_publishers is None:
            self._trusted_publishers: set[str] = set(self.DEFAULT_TRUSTED_PUBLISHERS)
        else:
            self._trusted_publishers = set(trusted_publishers)
        self._signing_salt = signing_secret_salt.encode("utf-8")

    def register_trusted_publisher(self, publisher_id: str) -> None:
        """Add a publisher to trusted identity set."""
        self._trusted_publishers.add(publisher_id.strip())

    def revoke_trusted_publisher(self, publisher_id: str) -> None:
        """Revoke trust from a publisher identity."""
        self._trusted_publishers.discard(publisher_id.strip())

    def is_publisher_trusted(self, publisher_id: str) -> bool:
        """Check if publisher identity is currently trusted."""
        return publisher_id.strip() in self._trusted_publishers

    def compute_sha256(self, source_code: str) -> str:
        """Compute hex-encoded SHA-256 checksum of source code."""
        return hashlib.sha256(source_code.encode("utf-8")).hexdigest()

    def generate_valid_signature(self, publisher_id: str, source_sha256: str) -> str:
        """Generate deterministic HMAC provenance signature for verification testing."""
        message = f"{publisher_id}:{source_sha256}".encode()
        return "sig_v1_" + hmac.new(self._signing_salt, message, hashlib.sha256).hexdigest()

    def verify_provenance(
        self,
        source_code: str,
        manifest: SkillProvenanceManifest,
    ) -> tuple[ProvenanceStatus, str]:
        """Verify hash digest and cryptographic publisher signature for skill code."""
        # 1. Verify publisher trust
        if not self.is_publisher_trusted(manifest.publisher_id):
            explanation = (
                f"Publisher '{manifest.publisher_id}' is not in trusted registry. "
                "Untrusted dynamic extensions cannot be mounted into sandbox."
            )
            logger.warning(explanation)
            return ProvenanceStatus.UNTRUSTED_PUBLISHER, explanation

        # 2. Check for empty signature
        if not manifest.signature or not manifest.signature.strip():
            explanation = "Package signature is missing. Unsigned toolchains are forbidden."
            logger.warning(explanation)
            return ProvenanceStatus.UNSIGNED, explanation

        # 3. Verify content SHA-256 digest
        computed_sha256 = self.compute_sha256(source_code)
        if computed_sha256.lower() != manifest.source_sha256.lower():
            explanation = (
                f"Package SHA-256 digest mismatch! Computed: {computed_sha256}, "
                f"Declared in manifest: {manifest.source_sha256}. Possible tampering detected."
            )
            logger.error(explanation)
            return ProvenanceStatus.HASH_MISMATCH, explanation

        # 4. Verify cryptographic signature
        expected_sig = self.generate_valid_signature(manifest.publisher_id, manifest.source_sha256)
        if not hmac.compare_digest(manifest.signature.strip(), expected_sig):
            explanation = (
                f"Cryptographic signature invalid for publisher '{manifest.publisher_id}'. "
                "Signature verification failed."
            )
            logger.error(explanation)
            return ProvenanceStatus.SIGNATURE_INVALID, explanation

        explanation = (
            f"Provenance verified successfully for '{manifest.skill_id}@{manifest.version}' "
            f"from trusted publisher '{manifest.publisher_id}'."
        )
        logger.info(explanation)
        return ProvenanceStatus.VERIFIED, explanation
