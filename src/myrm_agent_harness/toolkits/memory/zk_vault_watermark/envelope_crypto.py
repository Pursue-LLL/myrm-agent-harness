"""Local master key envelope encryption engine (Item 159).

[INPUT]
- User secret passphrase, plaintext memory payload, and EncryptedEnvelope.

[OUTPUT]
- EncryptedEnvelope containers and decrypted plaintext strings.

[POS]
- Envelope encryption in myrm_agent_harness/toolkits/memory/zk_vault_watermark/.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timezone

from .models import EncryptedEnvelope


class EnvelopeCryptoEngine:
    """Envelope encryption utilizing KEK derived from local passphrase and transient per-item DEKs."""

    def __init__(self, pbkdf2_iterations: int = 100_000) -> None:
        self.iterations = max(10_000, pbkdf2_iterations)

    def derive_kek(self, passphrase: str, salt: bytes) -> bytes:
        """Derive 256-bit Key Encryption Key (KEK) using PBKDF2-HMAC-SHA256."""
        return hashlib.pbkdf2_hmac(
            "sha256",
            passphrase.encode("utf-8"),
            salt,
            self.iterations,
            dklen=32,
        )

    @staticmethod
    def _keystream_cipher(data: bytes, key: bytes, iv: bytes) -> bytes:
        """Symmetric stream cipher utilizing HMAC-SHA256 blocks for portable zero-dependency encryption."""
        keystream = bytearray()
        block_idx = 0
        while len(keystream) < len(data):
            block_mac = hmac.new(
                key,
                iv + block_idx.to_bytes(4, byteorder="big"),
                hashlib.sha256,
            ).digest()
            keystream.extend(block_mac)
            block_idx += 1

        return bytes(b ^ k for b, k in zip(data, keystream[: len(data)]))

    def encrypt_payload(
        self,
        plaintext: str,
        passphrase: str,
    ) -> EncryptedEnvelope:
        """Encrypt memory payload with transient DEK sealed by passphrase-derived KEK."""
        salt = secrets.token_bytes(16)
        kek = self.derive_kek(passphrase, salt)

        # Transient 256-bit Data Encryption Key (DEK)
        dek = secrets.token_bytes(32)
        dek_iv = secrets.token_bytes(12)
        encrypted_dek = self._keystream_cipher(dek, kek, dek_iv)
        sealed_dek_payload = dek_iv + encrypted_dek

        # Encrypt plaintext with DEK
        data_iv = secrets.token_bytes(12)
        ciphertext = self._keystream_cipher(
            plaintext.encode("utf-8"), dek, data_iv
        )

        # Calculate HMAC tag for integrity check
        tag = hmac.new(dek, data_iv + ciphertext, hashlib.sha256).digest()[:16]
        final_ciphertext = tag + ciphertext

        now_str = datetime.now(timezone.utc).isoformat()
        return EncryptedEnvelope(
            ciphertext_hex=final_ciphertext.hex(),
            iv_hex=data_iv.hex(),
            salt_hex=salt.hex(),
            encrypted_dek_hex=sealed_dek_payload.hex(),
            algorithm="AES-256-GCM-Simulated-HMAC",
            created_at=now_str,
        )

    def decrypt_payload(
        self,
        envelope: EncryptedEnvelope,
        passphrase: str,
    ) -> str:
        """Unseal DEK using KEK derived from passphrase and decrypt payload with integrity validation."""
        salt = bytes.fromhex(envelope.salt_hex)
        kek = self.derive_kek(passphrase, salt)

        # Unseal DEK
        sealed_dek = bytes.fromhex(envelope.encrypted_dek_hex)
        if len(sealed_dek) < 12 + 32:
            raise ValueError("Malformed sealed DEK payload")
        dek_iv = sealed_dek[:12]
        encrypted_dek = sealed_dek[12:]
        dek = self._keystream_cipher(encrypted_dek, kek, dek_iv)

        # Decrypt ciphertext
        raw_payload = bytes.fromhex(envelope.ciphertext_hex)
        if len(raw_payload) < 16:
            raise ValueError("Malformed ciphertext payload: missing tag")
        tag = raw_payload[:16]
        ciphertext = raw_payload[16:]
        data_iv = bytes.fromhex(envelope.iv_hex)

        # Verify integrity
        expected_tag = hmac.new(dek, data_iv + ciphertext, hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(tag, expected_tag):
            raise ValueError("Decryption failed: invalid passphrase or corrupted payload")

        plaintext_bytes = self._keystream_cipher(ciphertext, dek, data_iv)
        return plaintext_bytes.decode("utf-8", errors="strict")
