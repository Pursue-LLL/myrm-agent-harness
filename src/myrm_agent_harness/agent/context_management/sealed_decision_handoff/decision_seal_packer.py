# [INPUT] HandoffDecisionPackage, SealedReceipt, bytes key
# [OUTPUT] DecisionSealPacker
# [POS] Cryptographic AEAD seal packer, in-memory pipe hydrator, and anti-injection barrier

"""Cryptographic decision seal packer and hydrator enforcing key-in-pipe custody."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from myrm_agent_harness.agent.context_management.sealed_decision_handoff.sealed_decision_types import (
    HandoffDecisionPackage,
    SealedDecisionVerificationError,
    SealedReceipt,
)

_AES_256_KEY_BYTES = 32
_GCM_NONCE_BYTES = 12


class DecisionSealPacker:
    """Packer for sealed decision continuity with AES-256-GCM and SHA-256 validation."""

    def __init__(self) -> None:
        pass

    @staticmethod
    def generate_cryptographic_key() -> bytes:
        """Generate a random cryptographically secure 256-bit AES key."""
        return AESGCM.generate_key(bit_length=256)

    def seal_package(
        self,
        package: HandoffDecisionPackage,
        key: bytes,
        key_ref: str,
        summary: str,
        receipt_id: str | None = None,
        extra_metadata: dict[str, str] | None = None,
    ) -> tuple[SealedReceipt, bytes]:
        """Seal decision package into AES-256-GCM ciphertext without disk staging.

        Args:
            package: The structured decision package to seal.
            key: 32-byte AES key handled strictly in memory pipe.
            key_ref: Non-secret reference identifier for the key in vault/keystore.
            summary: Brief non-sensitive label describing the context scope.
            receipt_id: Optional unique receipt ID; derived from digest if omitted.
            extra_metadata: Optional non-sensitive metadata for receipt.

        Returns:
            Tuple of (SealedReceipt, ciphertext_bytes).
        """
        if len(key) != _AES_256_KEY_BYTES:
            raise ValueError(
                f"AES key must be exactly 32 bytes (256 bits), got {len(key)}"
            )

        # 1. Serialize package to canonical bytes
        plaintext_str = package.to_json()
        plaintext_bytes = plaintext_str.encode("utf-8")

        # 2. Compute canonical SHA-256 digest across boundaries
        sha256_digest = hashlib.sha256(plaintext_bytes).hexdigest()

        # 3. Generate distinct random nonce for GCM
        nonce = os.urandom(_GCM_NONCE_BYTES)

        # 4. Encrypt with AES-GCM (nonce + ciphertext + 16-byte tag)
        aesgcm = AESGCM(key)
        # Associated Data includes topic and sha256 to bind ciphertext to metadata
        associated_data = f"{package.topic}:{sha256_digest}".encode("utf-8")
        encrypted_payload = aesgcm.encrypt(nonce, plaintext_bytes, associated_data)

        # Combine nonce (12 bytes) + encrypted_payload
        final_ciphertext = nonce + encrypted_payload

        # 5. Form structured receipt contract
        actual_receipt_id = receipt_id or f"rcpt_{sha256_digest[:16]}"
        now_iso = datetime.now(timezone.utc).isoformat()

        receipt = SealedReceipt(
            receipt_id=actual_receipt_id,
            topic=package.topic,
            enc="aes-256-gcm",
            key_ref=key_ref,
            sha256_digest=sha256_digest,
            summary=summary,
            payload_bytes_len=len(final_ciphertext),
            created_at_iso=now_iso,
            metadata=extra_metadata or {},
        )

        return receipt, final_ciphertext

    def unseal_package(
        self,
        ciphertext: bytes,
        receipt: SealedReceipt,
        key: bytes,
    ) -> HandoffDecisionPackage:
        """Unseal ciphertext in memory and verify SHA-256 digest and AEAD auth tag.

        Guarantees zero partial files written on failed decryption.
        """
        if len(key) != _AES_256_KEY_BYTES:
            raise SealedDecisionVerificationError(
                f"Invalid key length for unsealing: expected 32, got {len(key)}"
            )

        if receipt.enc != "aes-256-gcm":
            raise SealedDecisionVerificationError(
                f"Unsupported encryption algorithm in receipt: '{receipt.enc}'"
            )

        if len(ciphertext) <= _GCM_NONCE_BYTES:
            raise SealedDecisionVerificationError(
                "Ciphertext payload is truncated or invalid"
            )

        nonce = ciphertext[:_GCM_NONCE_BYTES]
        encrypted_payload = ciphertext[_GCM_NONCE_BYTES:]

        aesgcm = AESGCM(key)
        associated_data = f"{receipt.topic}:{receipt.sha256_digest}".encode("utf-8")

        try:
            plaintext_bytes = aesgcm.decrypt(nonce, encrypted_payload, associated_data)
        except Exception as err:
            raise SealedDecisionVerificationError(
                f"Authentication tag or decryption verification failed: {err}"
            ) from err

        # Verify plaintext SHA-256 digest against receipt contract
        computed_digest = hashlib.sha256(plaintext_bytes).hexdigest()
        if computed_digest != receipt.sha256_digest:
            raise SealedDecisionVerificationError(
                f"SHA-256 digest mismatch: expected '{receipt.sha256_digest}', got '{computed_digest}'"
            )

        # Deserialize with pure data-never-instructions parsing
        try:
            plaintext_str = plaintext_bytes.decode("utf-8")
            return HandoffDecisionPackage.from_json(plaintext_str)
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as err:
            raise SealedDecisionVerificationError(
                f"Plaintext payload corrupt or invalid schema: {err}"
            ) from err
