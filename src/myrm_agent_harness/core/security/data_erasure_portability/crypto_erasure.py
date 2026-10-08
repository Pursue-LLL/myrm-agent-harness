"""Cryptographic erasure engine and verifiable deletion certificate generator."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time

from myrm_agent_harness.core.security.data_erasure_portability.types import (
    DeletionCertificate,
    ErasureMethod,
    ErasureResult,
)

logger = logging.getLogger(__name__)

_DEFAULT_SIGNING_KEY: bytes = b"myrm-erasure-certificate-authority-v1"


class CryptographicErasureEngine:
    """Engine managing tenant Data Encryption Keys (DEKs) and generating verifiable deletion certificates."""

    def __init__(self, authority_secret: bytes | None = None) -> None:
        self._authority_secret: bytes = authority_secret or _DEFAULT_SIGNING_KEY
        # In-memory store for active tenant DEKs
        self._tenant_keys: dict[str, bytearray] = {}

    def register_tenant_key(self, tenant_id: str, key_bytes: bytes | None = None) -> str:
        """Register or generate a 256-bit cryptographic DEK for a tenant."""
        key = bytearray(key_bytes if key_bytes is not None else secrets.token_bytes(32))
        self._tenant_keys[tenant_id] = key
        return hashlib.sha256(key).hexdigest()

    def get_tenant_key_fingerprint(self, tenant_id: str) -> str | None:
        """Retrieve key SHA-256 fingerprint without exposing raw key bytes."""
        key = self._tenant_keys.get(tenant_id)
        if key is None:
            return None
        return hashlib.sha256(key).hexdigest()

    def execute_cryptographic_erasure(
        self,
        tenant_id: str,
        target_resource_types: list[str],
        shredded_bytes: int = 0,
        signer_identity: str = "myrm-security-ledger",
    ) -> ErasureResult:
        """Irreversibly destroy tenant DEK in memory and issue a signed DeletionCertificate.

        Mathematical property: Without the DEK, ciphertext encrypted under AES-256-GCM
        or ChaCha20-Poly1305 cannot be decrypted under standard computational assumptions.
        """
        prior_key = self._tenant_keys.get(tenant_id)
        if prior_key is not None:
            prior_fingerprint = hashlib.sha256(prior_key).hexdigest()
            # Overwrite key material in-place before removing
            length = len(prior_key)
            prior_key[:] = b"\x00" * length
            del self._tenant_keys[tenant_id]
        else:
            prior_fingerprint = "NO_ACTIVE_KEY_FOUND"

        now = time.time()
        cert_id = f"del-cert-{secrets.token_hex(12)}"

        cert_body = json.dumps(
            {
                "certificate_id": cert_id,
                "tenant_id": tenant_id,
                "method": ErasureMethod.CRYPTOGRAPHIC.value,
                "resources": sorted(target_resource_types),
                "bytes": shredded_bytes,
                "prior_fingerprint": prior_fingerprint,
                "timestamp": int(now),
                "signer": signer_identity,
            },
            sort_keys=True,
        )

        signature = hmac.new(
            self._authority_secret,
            cert_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        cert = DeletionCertificate(
            certificate_id=cert_id,
            tenant_id=tenant_id,
            erasure_method=ErasureMethod.CRYPTOGRAPHIC,
            target_resource_types=list(target_resource_types),
            shredded_bytes=shredded_bytes,
            payload_checksum_prior=prior_fingerprint,
            timestamp=now,
            signer_identity=signer_identity,
            certificate_signature=signature,
        )

        logger.info(
            "Cryptographic erasure executed for tenant '%s', cert '%s'.",
            tenant_id,
            cert_id,
        )
        return ErasureResult(
            success=True,
            tenant_id=tenant_id,
            erasure_method=ErasureMethod.CRYPTOGRAPHIC,
            certificate=cert,
        )

    def verify_deletion_certificate(self, certificate: DeletionCertificate) -> bool:
        """Verify the cryptographic authenticity and integrity of a DeletionCertificate."""
        cert_body = json.dumps(
            {
                "certificate_id": certificate.certificate_id,
                "tenant_id": certificate.tenant_id,
                "method": certificate.erasure_method.value,
                "resources": sorted(certificate.target_resource_types),
                "bytes": certificate.shredded_bytes,
                "prior_fingerprint": certificate.payload_checksum_prior,
                "timestamp": int(certificate.timestamp),
                "signer": certificate.signer_identity,
            },
            sort_keys=True,
        )

        expected_sig = hmac.new(
            self._authority_secret,
            cert_body.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(certificate.certificate_signature, expected_sig)
