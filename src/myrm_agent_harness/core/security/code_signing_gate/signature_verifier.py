"""
[POS] src/myrm_agent_harness/core/security/code_signing_gate/signature_verifier.py
[INPUT] base64, time, typing, cryptography.hazmat.primitives, .types (DeveloperCertificateInfo)
[OUTPUT] CodeSignatureVerifier

Cryptographic asymmetric signing and verification of agent package manifests using Ed25519.
Strict typing applied: No `Any` types allowed.
"""

from __future__ import annotations

import base64
import time

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from .types import DeveloperCertificateInfo


class CodeSignatureVerifier:
    """Handles asymmetric Ed25519 signing and verification of package manifest digests."""

    @staticmethod
    def generate_keypair() -> tuple[str, str]:
        """Generate a fresh Ed25519 keypair formatted in standard PEM."""
        private_key = ed25519.Ed25519PrivateKey.generate()
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode("utf-8")

        public_pem = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode("utf-8")

        return private_pem, public_pem

    @staticmethod
    def sign_digest(private_key_pem: str, canonical_digest: str) -> str:
        """Sign a canonical manifest digest using developer private key and return base64 signature."""
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode("utf-8"),
            password=None,
        )
        if not isinstance(private_key, ed25519.Ed25519PrivateKey):
            raise ValueError("Only Ed25519 private keys are supported for code signing.")

        signature_bytes = private_key.sign(canonical_digest.encode("utf-8"))
        return base64.b64encode(signature_bytes).decode("ascii")

    @staticmethod
    def verify_signature(
        public_key_pem: str,
        canonical_digest: str,
        signature_b64: str,
    ) -> bool:
        """Verify detached Ed25519 base64 signature against canonical digest."""
        try:
            public_key = serialization.load_pem_public_key(public_key_pem.encode("utf-8"))
            if not isinstance(public_key, ed25519.Ed25519PublicKey):
                return False

            sig_bytes = base64.b64decode(signature_b64.encode("ascii"))
            public_key.verify(sig_bytes, canonical_digest.encode("utf-8"))
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    @staticmethod
    def is_certificate_valid(
        cert_info: DeveloperCertificateInfo,
        current_time: float | None = None,
    ) -> tuple[bool, str]:
        """Verify whether developer certificate is within its valid operational lifespan."""
        now = current_time if current_time is not None else time.time()
        if now > cert_info.valid_until:
            return False, f"Certificate expired on timestamp {cert_info.valid_until} (current: {now})."
        return True, "Certificate is valid."
